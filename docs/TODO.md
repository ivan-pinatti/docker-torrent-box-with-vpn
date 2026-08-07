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

## LazyLibrarian

- [ ] Drop `patches/lazylibrarian/lazylibrarian/auth.py` once it is no longer
  needed. Filed upstream:
  [LazyLibrarian/LazyLibrarian#3046](https://gitlab.com/LazyLibrarian/LazyLibrarian/-/work_items/3046)
  (login/logout redirect doubles `HTTP_ROOT` and 404s for pages reached via
  `check_auth()`'s redirect while logged out), with a fix submitted as
  [LazyLibrarian/LazyLibrarian!1832](https://gitlab.com/LazyLibrarian/LazyLibrarian/-/merge_requests/1832).
  Check whether it merged and reached a release before removing the patch
