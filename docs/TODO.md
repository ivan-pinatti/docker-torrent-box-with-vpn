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

## LazyLibrarian

- [ ] Drop `patches/lazylibrarian/lazylibrarian/auth.py` once it is no longer
  needed. Filed upstream:
  [LazyLibrarian/LazyLibrarian#3046](https://gitlab.com/LazyLibrarian/LazyLibrarian/-/work_items/3046)
  (login/logout redirect doubles `HTTP_ROOT` and 404s for pages reached via
  `check_auth()`'s redirect while logged out), with a fix submitted as
  [LazyLibrarian/LazyLibrarian!1832](https://gitlab.com/LazyLibrarian/LazyLibrarian/-/merge_requests/1832).
  Check whether it merged and reached a release before removing the patch
