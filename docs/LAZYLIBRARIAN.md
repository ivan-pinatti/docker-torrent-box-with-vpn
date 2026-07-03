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

## Libgen providers

The classic libgen mirrors (`libgen.li`, `libgen.bz`, `libgen.vg`, `libgen.la`,
`libgen.gl`) use `index.php` as the search endpoint and return the `tablelibgen`
HTML table that LazyLibrarian's parser expects.

The newer `libgen.ad` frontend uses a different design and is not compatible with
LazyLibrarian's parser. Use the mirrors listed below.

Five mirrors are configured in `[GEN_0]` through `[GEN_4]`:

| Section | Host | Search endpoint |
| --------- | ------ | ----------------- |
| `GEN_0` | `libgen.li` | `index.php` |
| `GEN_1` | `libgen.bz` | `index.php` |
| `GEN_2` | `libgen.vg` | `index.php` |
| `GEN_3` | `libgen.la` | `index.php` |
| `GEN_4` | `libgen.gl` | `index.php` |

All five are aliases of the same database. Having multiple entries provides
automatic fallback if one mirror is slow or temporarily unreachable.

### Editing the config

LazyLibrarian writes its in-memory config back to disk on shutdown. Editing
`config.ini` while the container is running and then restarting will cause
the container's in-memory state to overwrite the file on shutdown. Always stop
the container before editing:

```shell
podman stop lazylibrarian
# edit config.ini
podman start lazylibrarian
```

---

## Z-Library

Z-Library requires a registered account. Configure credentials in
`configs/lazylibrarian/config/config.ini` under `[BOK]`:

```ini
[BOK]
bok = True
bok_host = z-lib.fm
bok_email = your@email.com
bok_pass = yourpassword
```

Alternatively, use session tokens from your browser cookies after logging in at
the configured host (more secure than storing a password):

```ini
[BOK]
bok = True
bok_host = z-lib.fm
bok_remix_userid = 12345678
bok_remix_userkey = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Z-Library rotates mirror domains periodically; update `bok_host` if the
configured mirror stops working.

---

## Anna's Archive

Pre-configured in `[ANNA]`:

```ini
[ANNA]
anna = True
anna_host = annas-archive.gl,annas-archive.pk,annas-archive.gd
```

Multiple hosts are tried in order. Update this list if any mirror becomes
unreachable.
