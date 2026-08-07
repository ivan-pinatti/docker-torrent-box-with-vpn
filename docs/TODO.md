# Todo

Open items only. Resolved work lives in git history, not here; see `git log`
for what was fixed and when.

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
