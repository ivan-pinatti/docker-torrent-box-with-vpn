# LazyLibrarian

LazyLibrarian is the books, audiobooks, and comics tracker/manager in this stack.

## Custom image

The upstream image uses `DOCKER_MODS: ghcr.io/linuxserver/mods:universal-calibre`,
which downloads and installs Calibre at every container start. This adds several
minutes to every restart.

This stack builds a custom image that pre-installs Calibre at build time using a
multi-stage Dockerfile that copies `calibre.txz` directly from the mod image and
runs `calibre_postinstall`. The result is a container that starts in seconds.

### Rebuild

Rebuild the image after pulling a new base image version or after changing
`LAZYLIBRARIAN_VERSION` in `.env`:

```shell
make build_images
```

Then recreate the container:

```shell
podman stop lazylibrarian && podman rm lazylibrarian && make start
```

### Dockerfile

`build/lazylibrarian/Dockerfile` — multi-stage build copying `calibre.txz` from
`ghcr.io/linuxserver/mods:universal-calibre` and installing the system library
dependencies required by Calibre before extracting the bundle.

---

## Session cookie scoping

LazyLibrarian and Mylar are both cherrypy apps that default to a session
cookie literally named `session_id`, scoped to `Path=/` unless told
otherwise. Left alone, the browser holds only one `session_id` cookie for
the whole domain, so visiting one app overwrites the other's session; the
app whose cookie got overwritten then bounces every subsequent request back
to its own login page, indistinguishable from a real login bug. `nginx`'s
`/lazylibrarian/` and `/mylar/` locations in
`configs/nginx/templates/default.conf.template` each carry a
`proxy_cookie_path` rewrite that scopes the cookie to its own prefix,
which stops the collision.

## NZBHydra2 connection

LazyLibrarian and NZBHydra2 both run on the `apps` network and reach each other
by container alias.

`NZBHYDRA2_PROFILE` defaults to `disabled` (see `.env.example`), so both of
the committed seed's NZBHydra2 entries ship disabled too, rather than pointing
at a container that never starts:

```ini
[Newznab_0]
host = https://nzbhydra2:5077/nzbhydra2
enabled = False

[Torznab_0]
host = https://nzbhydra2:5077/nzbhydra2
enabled = False
```

If you enable `NZBHYDRA2_PROFILE`, flip `[Newznab_0]`'s `enabled` to `True`
(stop LazyLibrarian first, per "Editing the config" below). Leave
`[Torznab_0]` disabled: it points at the same NZBHydra2 instance over the
wrong protocol for usenet indexing and would only duplicate results.

---

## Book sources

The committed `config.ini.example` ships only the indexer plumbing: NZBHydra2
over Newznab, and numbered Torznab entries pointing at Prowlarr. It configures
no direct book sources, so LazyLibrarian starts with nothing enabled beyond
what you add yourself.

LazyLibrarian supports several source types of its own (`[GEN_*]` generic
providers, plus per-service sections). Adding one means deciding what you are
entitled to download from it, which is your call to make rather than something
this repo should preselect. Refer to the
[upstream LazyLibrarian project](https://gitlab.com/LazyLibrarian/LazyLibrarian)
for the section keys each provider type expects.

## Editing the config

LazyLibrarian writes its in-memory config back to disk on shutdown. Editing
`config.ini` while the container is running and then restarting will cause
the container's in-memory state to overwrite the file on shutdown. Always stop
the container before editing:

```shell
podman stop lazylibrarian
# edit config.ini
podman start lazylibrarian
```
