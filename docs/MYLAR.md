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
