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
  run before removing the patch. `MYLAR_VERSION` is held at a fixed version
  in `.github/renovate.json5` for as long as this patch exists, so dropping it
  is also what unfreezes that pin

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
  Dockerfile before removing this patch. `JDOWNLOADER2_VERSION` is held at a
  fixed version in `.github/renovate.json5` for as long as this patch exists,
  so dropping it is also what unfreezes that pin

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
  and its removal is safe whenever upstream changes. `SABNZBD_VERSION` is held
  at a fixed version in `.github/renovate.json5` for as long as this patch
  exists, so dropping it is also what unfreezes that pin

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

## Concurrent checkouts

- [ ] Decide whether two checkouts should be able to run at the same time, and
  if so, drop the explicit `container_name` values. Thirty-seven services set
  one, and compose does not project prefix an explicit name, so the names are
  global: a second checkout cannot create `jellyfin` while the first one holds
  it, whatever `COMPOSE_PROJECT_NAME` says. Raised by CodeRabbit on #92, and
  correct. It is deliberately not part of that pull request, which makes a
  second checkout safe to run **one at a time** (its own networks, its own
  fstab entry, its own published ports) rather than concurrently.

  The reason it is its own change is the blast radius, not disagreement.
  Removing those names means every caller that addresses a container by its
  literal name has to move to the generated one: roughly 170 call sites across
  `scripts/wire-connections.sh`, `scripts/rotate-passwords.sh` and
  `scripts/rotate-api-keys.sh`, plus `tests/conftest.py`, plus the 68
  `proxy_pass` directives in `configs/nginx/templates/default.conf.template`
  that reach services by name on the shared networks, plus every compose
  `depends_on` and healthcheck that does the same. Note also that the names are
  a documented interface here: docs/APP_LINKS.md and the README tell people to
  run `podman exec qbittorrent ...`, and `make down` filters on the project
  label rather than on names, so it is unaffected either way.

  Worth weighing against the actual need. Running two full stacks at once also
  needs a second set of published ports, which is already manual, so the
  question is whether concurrent operation is wanted at all or whether one at a
  time is the honest supported model

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
  included-review quota **drops** a review rather than queueing it, so a push
  during exhaustion is lost. The published schema (`schema.v2.json`) has no
  retry, backoff or queue setting. Recovery is a manual `@coderabbitai review`.
  Treat a green CodeRabbit check as "no review blocked this", not as "a review
  happened": it is also green on a skipped draft and on a rate-limited decline,
  which is the item below
- [ ] Stop a rate limited decline reporting green, which is how three pull
  requests merged with no review on 2026-08-19. CodeRabbit reports through the
  legacy commit status API rather than check runs, and that API offers only
  `error`, `failure`, `pending` and `success`, with no `neutral`. An exhausted
  quota resolves the status to `success` with the description
  `Review rate limited`, which neither branch protection nor anything else
  reading the status can tell apart from `success` with `Review completed`.
  #86, #87 and #88 all ended there and all merged, and none of their status
  histories carries a `Review completed` entry, while #82, #85 and #90 do. #87
  is titled "Stagger dependency updates, and stop losing CodeRabbit reviews"
  and was itself never read. The quota figure is also unclear: the review on
  #90 reported "up to 10 included reviews per hour; 5 remain", not the 3 per
  hour previously recorded here.

  Raised as a follow-up on the existing support ticket, framed as one value
  meaning two opposite things rather than as the wrong state being chosen. The
  deadlock argument against holding `pending` forever is defensible, and a
  status that cannot tell the two apart is not, so that framing is the one that
  cannot be closed as intended behavior. `reviews.fail_commit_status` is the only related
  setting and does not cover this: it acts on review errors, not on declines.

  The fix that does not depend on them is a gate job asserting the description
  equals `Review completed`, in the same shape as `Integration Tests` gating
  `Integration Suite`. It has to special case bot pull requests, which get no
  status at all, because a required context that is absent blocks a merge
  indefinitely and would freeze every Renovate pull request. For the same
  reason, do not simply mark the `CodeRabbit` context required: it would cause
  that freeze while still passing every rate limited human pull request.
  `required_conversation_resolution` is already enabled on `main`, so the
  "every thread addressed" half is enforced today and only "a review happened"
  is missing

- [ ] `drafts: false` stays deliberate. CodeRabbit is a GitHub App posting a
  check, not a workflow job, so it cannot be ordered after pre-commit with a
  `needs:` dependency; skipping drafts is the lever that gets the mechanical
  defects fixed before a review slot is spent

## Repository settings

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

## Observability in CI

- [ ] Get `podman_exporter` and `podman_limits_exporter` running in CI, or record
  that they never will. Both set `userns_mode`, podman-compose puts every service
  in a pod, and podman 4.9.3 refuses the combination outright with `--userns and
  --pod cannot be set together`. CI runs the Ubuntu archive's 4.9.3 deliberately,
  so the version is not the thing to change. The options are podman-compose's
  `--in-pod=false`, which alters the topology CI tests against and would break
  `test_observability`'s assertions on the pod name, or dropping `userns_mode`,
  which is what lets those exporters read the podman socket as the right
  identity. Both work on a bench, verified on podman 5.8.4, so
  `make bootstrap_tests` still covers them: this is a CI coverage gap rather than
  a broken service. The workflow disables them explicitly, with the reason beside
  the line

## Test suite

- [ ] Stop `test_compose_available` failing when one compose flavour is merely
  slow. It probes `docker compose version` through conftest's `run()`, which
  passes `timeout=10` and therefore raises `TimeoutExpired` rather than returning
  non-zero, so a runner where that probe is slow aborts the test before it looks
  at `docker-compose` or `podman-compose`. The assertion only needs one of the
  three to exist, and podman-compose is present in CI, so the failure contradicts
  what the test is checking. Seen on 2026-08-20, green on a re-run of the same
  commit with nothing changed

- [ ] Make `test_arr_health_response_empty` fail, not warn, when an arr cannot
  reach its download client. It warns for every health message on the grounds
  that "some warnings are non-critical", which is true of "All indexers are
  unavailable due to failures" in an environment with no real indexers, and not
  true of "Unable to communicate with QBittorrent. Connection refused
  (172.28.0.10:8085)". A stack with every download client unreachable currently
  passes: found exactly that way, when a network subnet change left
  `GLUETUN_SERVICES_IP` behind and `wire-connections.sh` had written the stale
  address into every arr. The read-only tier reported 590 passed while nothing
  could talk to qBittorrent. Splitting the messages into a fail list and a warn
  list is the fix; the fail list wants to start with download client
  reachability and stay short, since the whole point of the warning was that
  most of what these endpoints report is environmental

## Renovate

- [ ] Give `LAZYLIBRARIAN_VERSION` a versioning scheme that can order it,
  before `patches/lazylibrarian/` is dropped and the hold on the pin lifts. Two
  separate things stop this pin moving and only one of them is temporary: the
  pin is switched off outright in `.github/renovate.json5` while the patch
  exists, and the `loose` scheme cannot order the tag correctly, which was true
  before the hold and stays true after it. Lifting the hold without fixing the ordering would
  leave the pin looking watched and still never bumping, which is the exact
  state the rest of this change set out to remove.
  `40a389ea-ls310` holds no version number, so `loose` reads the leading `40` as
  the version and ranks the current pin above `9a2c0d5e-ls334`, comparing a
  commit hash fragment as a number. `versioning=regex:^[0-9a-f]+-ls(?<major>\d+)$`
  keys on the `ls` counter and orders these correctly, and lazylibrarian's
  counter has not reset, unlike jackett's, which went `ls491` then `ls1`. Worth
  confirming first how Renovate labels the resulting update, since a scheme
  whose only numeric group is `major` makes every build a major bump, and major
  bumps match no automerge rule in `.github/renovate.json5` and would sit
  waiting for a person

- [ ] Decide whether `PODMAN_LIMITS_EXPORTER_VERSION` and `PYTHON_VERSION`
  should be the same number. The exporter runs Python 3.13 while
  `PYTHON_VERSION=3.14` is what lints and tests everything else in the
  repository, so `scripts/podman-limits-exporter.py` is checked under one
  interpreter and executed under another. Both are watched and both can move, so
  this is a question of whether the drift is deliberate rather than a gap

- [ ] Offset the live deployment's three network subnets so it and a test stack
  can run at once, then drop the offset from `.env.tests` if that turns out to be
  the tidier side to special case. Deferred because the share at
  `STORAGE_REMOTE=//vox114/torrentbox` was unmounted, and `storage_guard`
  correctly refuses to start a deployment whose data directory is not mounted, so
  neither the change nor the simultaneous run could be verified. Ports need
  nothing: all seven published mappings are already offset by 10000. What is left
  to check is the two stacks' containers up at the same time; their networks
  already coexist on this host

- [ ] Expand `${VAR}` from `.env` when `seed-configs.sh` copies a `.example`
  into place, or record why not. Five seeded configs still name an address
  literally, so an environment whose `.env` moves a subnet needs them edited by
  hand once: `configs/mylar/config/mylar/config.ini.example` (3),
  `configs/lazylibrarian/config/config.ini.example` (2),
  `configs/jellyfin/config/network.xml.example` (`KnownProxies`),
  `configs/nzbget/config/nzbget.conf` (`ControlIP`, legacy and disabled) and the
  stale comment in `configs/gluetun/.env.example`. Unlike the two templates this
  change parameterized, these only apply at first seed, so they cost one edit
  rather than recurring on every `make start`. Blanket expansion is not
  obviously safe: `grafana.ini.example` legitimately contains `${...}`, so this
  wants an allowlist or an opt-in marker rather than a global pass

- [ ] Audit the eighteen compose services absent from `SERVICES` in
  `tests/conftest.py`, adding each one or recording why it stays out. That
  registry parametrizes the container, connectivity, auth and service tiers, so
  a service outside it gets nothing from them: alloy, audiobookshelf, cadvisor,
  calibre, calibre-web, gluetun, homepage, jdownloader2, korsync, lazylibrarian,
  log_rotator, loki, mylar, nginx, nginx_exporter, nzbhydra2,
  podman_limits_exporter and vpn_mock. Three of those are covered another way and
  should come out of the list rather than into the registry: gluetun and vpn_mock
  by the vpn and killswitch tiers and by `test_vpn_container_running`, and nginx
  by every `proxy_path` case, which reaches its service through it. korsync is
  what prompted this, since it now tracks a release tag Renovate will bump on its
  own and a broken bump would fail nothing; it already carries a healthcheck in
  `docker-compose-media-library.yml`, and `recyclarr` and the three exporters show
  that an entry with every optional field `None` is a supported shape

## LazyLibrarian

- [ ] Drop `patches/lazylibrarian/lazylibrarian/auth.py` once it is no longer
  needed. Filed upstream:
  [LazyLibrarian/LazyLibrarian#3046](https://gitlab.com/LazyLibrarian/LazyLibrarian/-/work_items/3046)
  (login/logout redirect doubles `HTTP_ROOT` and 404s for pages reached via
  `check_auth()`'s redirect while logged out), with a fix submitted as
  [LazyLibrarian/LazyLibrarian!1832](https://gitlab.com/LazyLibrarian/LazyLibrarian/-/merge_requests/1832).
  Check whether it merged and reached a release before removing the patch.
  `LAZYLIBRARIAN_VERSION` is held at a fixed version in
  `.github/renovate.json5` for as long as this patch exists, so dropping it is
  also what unfreezes that pin
