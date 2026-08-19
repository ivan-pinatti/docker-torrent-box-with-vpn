# Todo

Open items only. Resolved work lives in git history, not here; see `git log`
for what was fixed and when.

## Mylar

- [ ] Drop `patches/mylar/` once it is no longer needed. Upstream PR
  [MylarComics/mylar3#23](https://github.com/MylarComics/mylar3/pull/23)
  (qBittorrent self-signed certificate support) merged into `nightly` on
  2026-07-23, but `stable` is still 9 commits behind as of 2026-08-07
  (`gh api repos/MylarComics/mylar3/compare/stable...70ff41c3014e48daf88763134d976ef042244db`
  still reports `ahead_by: 9`). See `docs/MYLAR.md` for the full check to
  run before removing the patch

## jDownloader2

- [ ] Drop `patches/jdownloader2/10-webauth.sh` once it is no longer needed.
  Upstream fixed `load_env_var()` in `docker-baseimage-gui` version 4.13.0,
  confirmed via the maintainer's own comment closing #196. But
  `docker-jdownloader-2`'s own Dockerfile still pins `baseimage-gui:alpine-3.24-v4.12.6`
  as of 2026-08-07 and no image tag newer than `v26.07.2` has been
  published, so the fix has not reached the actual `jlesage/jdownloader-2`
  image yet and the patch still applies. Asked the maintainer directly:
  <https://github.com/jlesage/docker-baseimage-gui/issues/196#issuecomment-5221788643>.
  Check for a `baseimage-gui` bump to 4.13.0+ in `docker-jdownloader-2`'s
  Dockerfile before removing this patch

## SABnzbd

- [ ] Drop `patches/sabnzbd/svc-sabnzbd/run` and its bind mount in
  `docker-compose-nzb.yml` once the image respects a configured host. The
  shipped service script passes `--server ::` on every start, which overrides
  `host` in `sabnzbd.ini` and is then persisted back into it, so a deliberate
  `host = 0.0.0.0` cannot survive a container start. This surfaced on the 5.0.1
  to 5.0.4 bump, where the suite went red on
  `test_sabnzbd_config_disables_ipv6`. Reported upstream twice before this
  repository hit it,
  [linuxserver/docker-sabnzbd#116](https://github.com/linuxserver/docker-sabnzbd/issues/116)
  (2021) and
  [#240](https://github.com/linuxserver/docker-sabnzbd/issues/240) (2024-12-07,
  closed `NOT_PLANNED` with "That's the intended behavior"), on the grounds that
  forcing the value stops anyone binding `127.0.0.1` and locking themselves out
  of the web UI. The patch keeps exactly that protection, imposing the family
  address when the configured host is missing or loopback, and respects a
  reachable one. Filed as
  [linuxserver/docker-sabnzbd#274](https://github.com/linuxserver/docker-sabnzbd/issues/274),
  framed as a feature request rather than a bug because the bug framing is what
  #240 was closed under, with the fix submitted as
  [#275](https://github.com/linuxserver/docker-sabnzbd/pull/275). The patch is
  deliberately identical to that pull request, so it becomes a no-op the moment
  the change ships and can simply be deleted. Temper expectations: the same
  behavior was reported in #2 (2016), #35 (2017), #42 (2018), #116 (2021) and
  #240 (2024), and every one was closed. Before deleting, check whether the
  upstream `run` script has
  gained any condition around `--server`, where `RAW` is
  `https://raw.githubusercontent.com/linuxserver/docker-sabnzbd/master`:

  ```shell
  curl -s "$RAW/root/etc/s6-overlay/s6-rc.d/svc-sabnzbd/run" | grep -n server
  ```

  Note that the bind address is not the control that matters in this stack:
  `test_vpn_namespace_has_no_global_ipv6_address` asserts the property
  `docker-compose-vpn.yml` actually relies on, so this patch is defense in depth
  and its removal is safe whenever upstream changes

- [ ] Report `linuxserver/github-workflows`' broken permission check, which is
  why [#275](https://github.com/linuxserver/docker-sabnzbd/pull/275) shows red.
  Their `init-svc-executable-permissions.yml@v1` runs `actions/checkout@v7.0.1`
  with `ref: github.event.pull_request.head.sha` from a `pull_request_target`
  caller, and 7.0.1 refuses a fork checkout in that context unless
  `allow-unsafe-pr-checkout: true` is set. The job dies before reading a single
  file, so this should be failing every fork pull request across their whole
  organization, not only ours. Nothing in our branch can fix it, and the file
  the pull request touches is already `100755`, so the check passes once it can
  run. Diagnosis and three suggested fixes are already in a comment on #275; the
  useful next step is raising it where the workflow lives

## Jellyfin wiring

- [ ] Stop `ensure_jellyfin_connection` failing silently, and work out why it
  fails for `lidarr`. `scripts/wire-connections.sh:1003` calls it with
  `|| true`, so a failure leaves the app without the connection while `make wire_connections`
  still reports success, and the first sign of it is
  `test_jellyfin_connection_matches_what_the_app_supports[lidarr]` failing later
  with `supports MediaBrowser=True but wired=False`. Seen on two runs on
  2026-08-18 (`32176749677` on #72 and `32179005406` on #77), both shortly after
  the Jellyfin 10.11.10 bump merged unattended in #76 at 19:17Z, and both passed
  on a retry, so the bump appears to have widened a race rather than broken
  anything outright. Two things to do, and the first stands on its own: the
  Prowlarr path in the same file already collects failures in `PROWLARR_FAILED`
  precisely "so the end of `wire_prowlarr_apps` can report them instead of
  letting a partial result look identical to a complete one", and the Jellyfin
  path should do the same rather than swallow. Then find the actual failure,
  which the reporting will finally make visible. This matters more than a normal
  flake now that dependency updates merge unattended: an intermittent test means
  a bot pull request stalls at random and waits for a person, which is the one
  outcome the automation exists to avoid

## CodeRabbit

- [ ] Chase the open support ticket: CodeRabbit does not auto-review pull
  requests opened by `renovate[bot]` or `dependabot[bot]`. Across #53 to #76 it
  posted a `CodeRabbit` status on 8 of 8 human pull requests and on 1 of 16 bot
  ones, and that single exception is #56, where the review was asked for by hand
  with `@coderabbitai review` and arrived in under three minutes. Rate limiting
  is ruled out: four of the human statuses read "Review rate limited", so a
  throttled review still reports a status, whereas the bot ones report nothing
  at all. Configuration is ruled out too, since `reviews.auto_review.ignore_usernames`
  is at its empty default and the published schema has no other setting that
  suppresses a review. GitHub's 2026-08-17 webhook incident is ruled out because
  the retest ran hours after it resolved and reproduced. This matters because
  docs/HARDENING.md names CodeRabbit as the only thing that reads a dependency
  bump for intent, and right now it is not reading them.

  Answered, and still open. Support confirmed that pull requests authored by
  bots are hardcoded to be ignored on their side, so this is neither our
  configuration nor the review quota. They are investigating and will come back.
  Keep this item open rather than closing it as answered, because the outcome
  wanted here is that behavior changed, not merely explained. Meanwhile
  `.github/workflows/coderabbit-review-queue.yml` asks on their behalf, hourly,
  one pull request per run, which is the only way a bot pull request gets read at
  all while the ignore list stands. Delete that workflow once they lift it
  <!-- cspell:ignore coderabbitai -->
- [ ] Confirm `auto_pause_after_reviewed_commits: 0` behaves as intended on
  the next long-lived branch here. It was changed from the default of `5` in
  `.coderabbit.yaml` because that default pauses automatic reviews after five
  reviewed commits **silently**: the CodeRabbit check stays green, so a pull
  request looks reviewed when nothing has read its head. Seen on
  `pre-commit-checklists#12` (seven commits), where reviews stopped after the
  fifth and twelve hours passed with no review and no warning
- [ ] Nothing to configure for the other half of the problem: the
  included-review quota (3/hour) **drops** a review rather than queueing it, so
  a push during exhaustion is lost. The published schema
  (`schema.v2.json`) has no retry, backoff or queue setting. Recovery is a
  manual `@coderabbitai review`. Treat a green CodeRabbit check as "no review
  blocked this", not as "a review happened": it is also green on a skipped
  draft and on a rate-limited decline
- [ ] `drafts: false` stays deliberate. CodeRabbit is a GitHub App posting a
  check, not a workflow job, so it cannot be ordered after pre-commit with a
  `needs:` dependency; skipping drafts is the lever that gets the mechanical
  defects fixed before a review slot is spent

## Repository settings

- [ ] Change Actions' default workflow permissions from write to read
  (Settings, Actions, General, Workflow permissions). Verified still `write` via
  `gh api repos/ivan-pinatti/docker-torrent-box-with-vpn/actions/permissions/workflow`.
  Every workflow in this repository already declares its own `permissions:`
  block, so nothing needs the permissive default today. It matters more than it
  used to: since code owner review came off `main`, a single approving review is
  enough to merge, and any future workflow that forgets a `permissions:` block
  would hold a token able to approve pull requests and push. Leave
  `can_approve_pull_request_reviews` enabled, since bot-auto-merge.yml depends
  on it

- [ ] Narrow `DOCKERHUB_TOKEN` to public read only. The integration suite
  authenticates to Docker Hub and then runs whatever image a dependency bump
  just introduced, in the same job, and those merges are now unattended. The
  blast radius is worth shrinking even though the token only exists to lift pull
  rate limits

- [ ] Decide whether `Security Reports` should gate rather than report. It is not
  a required check, so a dependency bump that introduces a new Trivy, checkov or
  gitleaks finding merges unattended with nobody seeing it. That was a reasonable
  trade while a person reviewed every bump, and it is a different trade now.
  docs/HARDENING.md explains why the job reports rather than gates today

- [ ] Weigh strict required status checks against the churn they cause. Every
  merge to `main` puts every other open pull request behind, so Renovate rebases
  it and the whole suite runs again, roughly fifteen minutes per pull request.
  On 2026-08-18 a single small change needed three suite runs for this reason.
  A merge queue is the usual answer; dropping strict is the cheap one. Note that
  merge queues are reported to interact badly with required approvals and
  Renovate, so check that before choosing

## Renovate

- [ ] Enable `dependencyDashboard` in `.github/renovate.json5`, and rewrite the
  comment above it that argues for leaving it off. That comment weighed a
  standing issue that never resolves against the noise, and missed the thing the
  dashboard is actually for: warnings. Two lookup failures sat on Mend's hosted
  dashboard for weeks, unseen because nothing in this repository surfaces it,
  while the checkov pin in `.pre-commit-config.yaml` silently stopped updating
  and drifted three patch versions behind the copy in the workflow. The
  `Renovate Config` job cannot catch that class of problem, because the config
  is valid, it just does the wrong thing. An issue in this repository would have
  shown it. The dashboard issue Renovate opened before the setting was turned
  off is #24, now closed

- [ ] Stop labelling every Renovate pull request `docker`. The root `labels`
  setting applies it unconditionally, so pypi and go updates arrive tagged as
  container images: #54, a checkov bump, carried it. Cosmetic, but the labels are
  load-bearing now that `automerge` is one of them

- [ ] Annotate the twelve container image pins Renovate cannot see. Each carries
  a digest but no `# renovate:` comment, so nothing watches it and the pin is
  frozen: `CADVISOR`, `MYLAR`, `NGINX_EXPORTER`, `NODE_EXPORTER`, `NOTIFIARR`,
  `PODMAN_LIMITS_EXPORTER`, `PODMAN_EXPORTER`, `ALLOY`, `LOG_ROTATOR`,
  `QBITTORRENT_EXPORTER`, `SABNZBD_EXPORTER` and `JACKETT`. Some are more than a
  year old. `NGINX_VERSION=stable-alpine`, `PLEX_VERSION=latest` and
  `WHISPARR_VERSION=v3` are deliberately floating and want no annotation.
  `LAZYLIBRARIAN_VERSION` is annotated but carries no digest, unlike every other
  managed pin, so `pinDigests` should be allowed to add one. Left out of the
  staggering change on purpose: annotating twelve images changes what arrives
  every week and deserves its own pull request and its own suite runs. See
  [docs/DEPENDENCY_UPDATES.md](DEPENDENCY_UPDATES.md) for how the managed set is
  divided today

- [ ] Add a test that fails when an image pin goes unwatched, so the gap above
  cannot recur silently. Walk `.env.example`, and for every variable naming a
  container image assert it carries a `# renovate:` annotation and a digest, with
  an explicit allowlist for the tags that are deliberately floating. Same shape
  as `tests/test_prerequisites.py` asserting runtime databases stay untracked,
  where the point is that a reintroduced mistake fails the suite rather than
  reaching a commit. It would have caught all twelve, and lazylibrarian's
  missing digest

## qBittorrent

- [ ] Decide what the 5.1.4 to 5.2.2 bump means for `tests/test_auth.py`, and
  unblock #83. Both `test_qbittorrent_api_login` and
  `test_qbittorrent_web_session_login` assert `status_code == 200` and a body of
  `Ok.`, and 5.2.2 answers with `204 No Content`, so both assertions fail and
  the pull request is correctly red. The suite caught it, which is the system
  working, and the bump has not merged.

  What is not yet known is whether authentication still succeeds. A 204 with no
  body could be the same successful login reported differently, or it could be a
  login that is no longer working, and the tests fail at the status assertion
  before reaching anything that would tell them apart. Check whether the
  response still carries the `SID` cookie. If it does, keep a status assertion and
  add the cookie: accept any successful 2xx and require a non-empty `SID`,
  dropping only the exact `200` and the `Ok.` body, which are the two parts
  upstream is free to change. Do not swap the status check out for a cookie check
  alone, or an error response that happens to set a cookie would pass. If the
  cookie is absent, hold the bump and find out what the new flow expects. Note both requests go through
  nginx, so rule that out as the source of the 204 before blaming qBittorrent

## LazyLibrarian

- [ ] Drop `patches/lazylibrarian/lazylibrarian/auth.py` once it is no longer
  needed. Filed upstream:
  [LazyLibrarian/LazyLibrarian#3046](https://gitlab.com/LazyLibrarian/LazyLibrarian/-/work_items/3046)
  (login/logout redirect doubles `HTTP_ROOT` and 404s for pages reached via
  `check_auth()`'s redirect while logged out), with a fix submitted as
  [LazyLibrarian/LazyLibrarian!1832](https://gitlab.com/LazyLibrarian/LazyLibrarian/-/merge_requests/1832).
  Check whether it merged and reached a release before removing the patch
