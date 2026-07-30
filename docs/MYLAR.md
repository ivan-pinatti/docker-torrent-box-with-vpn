# Mylar

Mylar is the comics tracker/manager in this stack.

## Custom image

The upstream image uses `DOCKER_MODS: linuxserver/mods:universal-package-install`
with `INSTALL_PIP_PACKAGES: pyOpenSSL`, which installs `pyOpenSSL` into the
linuxserver virtualenv (`/lsiopy`) at every container start.

This stack builds a custom image that pre-installs `pyOpenSSL` at build time,
eliminating the mod overhead on every restart.

### Rebuild

Rebuild the image after pulling a new base image version or after changing
`MYLAR_VERSION` in `.env`:

```shell
make build_images
```

Then recreate the container:

```shell
podman stop mylar && podman rm mylar && make start
```

### Dockerfile

`build/mylar/Dockerfile` installs `pyOpenSSL` directly into `/lsiopy` using the
linuxserver wheel index:

```dockerfile
RUN /lsiopy/bin/python3 -m pip install --no-cache-dir \
    -f https://wheel-index.linuxserver.io/ubuntu/ \
    pyOpenSSL
```

---

## qBittorrent with self-signed certificates

Mylar does not support self-signed certificates for qBittorrent connections out
of the box. A patch adds an "Ignore SSL warnings" toggle to the Settings UI. The
patched files are bind-mounted as read-only volumes in `docker-compose-servarr.yml`:

```yaml
- ./patches/mylar/lib/qbittorrent/client.py:/app/mylar3/lib/qbittorrent/client.py:ro,z
- ./patches/mylar/mylar/torrent/clients/qbittorrent.py:/app/mylar3/mylar/torrent/clients/qbittorrent.py:ro,z
- ./patches/mylar/mylar/config.py:/app/mylar3/mylar/config.py:ro,z
- ./patches/mylar/data/interfaces/default/config.html:/app/mylar3/data/interfaces/default/config.html:ro,z
- ./patches/mylar/mylar/webserve.py:/app/mylar3/mylar/webserve.py:ro,z
```

Enable the toggle in Mylar under Settings after start. The upstream pull request
tracking this fix is [MylarComics/mylar3#23](https://github.com/MylarComics/mylar3/pull/23).

### Status: merged upstream, waiting on a stable release

PR #23 merged into mylar3's `nightly` branch on 2026-07-23 (commit
`70ff41c3014e48daf88763134d976ef042244db`). Diffing our five patched files
against `nightly`'s current tip confirms the qBittorrent SSL logic is
byte-for-byte identical to what we carry, so the patch can be deleted
outright once the base image contains it.

`MYLAR_VERSION=latest` in `.env` pulls `linuxserver/mylar3:latest`, which
tracks the `stable` branch, not `nightly`. As of 2026-07-24, `stable`'s HEAD
(`70edba407fff224dba292f1e3b721215d26cd96e`, dated 2026-05-27) is 9 commits
behind the fix, so it is not yet in a stable release.

Before removing the patch, re-check whether `stable` has caught up:

```shell
gh api repos/MylarComics/mylar3/compare/stable...70ff41c3014e48daf88763134d976ef042244db
```

Once the fix commit is an ancestor of `stable` (`ahead_by: 0`), the next
`linuxserver/mylar3` stable image release will contain it. At that point:

1. Delete `patches/mylar/`.
2. Remove the five bind-mounted volumes from `docker-compose-servarr.yml`.
3. Delete this "Status" section, and the related lines in `README.md` known
   issue #3 and `docs/TODO.md`'s Mylar section.
4. Recreate the `mylar` container to pick up the base image's built-in fix.
