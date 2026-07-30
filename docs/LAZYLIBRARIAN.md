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

## NZBHydra2 connection

LazyLibrarian and NZBHydra2 both run on the `apps` network and reach each other
by container alias.

In `configs/lazylibrarian/config/config.ini`:

```ini
[Newznab_0]
host = https://nzbhydra2:5077/nzbhydra2
```

The Torznab entry for NZBHydra2 is disabled since LazyLibrarian uses the
Newznab protocol for usenet indexing.

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
[upstream LazyLibrarian wiki](https://gitlab.com/LazyLibrarian/LazyLibrarian/-/wikis/home)
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
