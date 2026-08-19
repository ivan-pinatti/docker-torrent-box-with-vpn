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
  bump for intent, and right now it is not reading them. Until it is fixed,
  `@coderabbitai review` on a bot pull request works as a manual fallback

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

## LazyLibrarian

- [ ] Drop `patches/lazylibrarian/lazylibrarian/auth.py` once it is no longer
  needed. Filed upstream:
  [LazyLibrarian/LazyLibrarian#3046](https://gitlab.com/LazyLibrarian/LazyLibrarian/-/work_items/3046)
  (login/logout redirect doubles `HTTP_ROOT` and 404s for pages reached via
  `check_auth()`'s redirect while logged out), with a fix submitted as
  [LazyLibrarian/LazyLibrarian!1832](https://gitlab.com/LazyLibrarian/LazyLibrarian/-/merge_requests/1832).
  Check whether it merged and reached a release before removing the patch
