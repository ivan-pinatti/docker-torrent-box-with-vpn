# Patches

Vendored source files from upstream projects, mounted into their containers to
replace the shipped copies at runtime. Each subdirectory mirrors the upstream
layout so a bind mount lands the file in the right place.

**These files are not covered by this repository's Apache License 2.0.** They
remain under their original upstream licenses, and are redistributed here
under those terms. See [NOTICE.md](../NOTICE.md).

## Contents

| Directory | Upstream project | Upstream license | Contents |
| --- | --- | --- | --- |
| `mylar/` | [MylarComics/mylar3](https://github.com/mylarcomics/mylar3) | GPL-3.0-or-later | Five complete source files, modified to add qBittorrent HTTPS support (self-signed certificate handling in the torrent client and its config UI) |
| `jdownloader2/` | [jlesage/docker-jdownloader-2](https://github.com/jlesage/docker-jdownloader-2) | MIT | `10-webauth.sh`, a modified copy of the image's own `cont-init.d` script, reading credentials from mounted compose secrets because the image's documented `CONT_ENV_*` Docker-secrets support does not fire |
| `lazylibrarian/` | [LazyLibrarian](https://gitlab.com/LazyLibrarian/LazyLibrarian) | GPL-3.0 | `auth.py`, fixing `login()`/`logout()` unconditionally prepending `HTTP_ROOT` to `from_page`, which `check_auth()`'s own redirect already prefixed since nginx forwards this app's URIs unstripped; 404'd the redirect back after logging in from a protected page reached while logged out |

`mylar/mylar/config.py` and `mylar/mylar/webserve.py` carry their original GPL
headers. Do not strip them. Because these are complete GPL-3.0 files rather
than small excerpts, anyone redistributing this repository is bound by GPL-3.0
for the contents of `mylar/`, regardless of the Apache License 2.0 covering
the rest.

## Why these are vendored rather than forked

Each patch tracks a specific upstream fix that is not yet in a release the
stack can pin. `docs/MYLAR.md` records the upstream commit each Mylar patch
corresponds to, so the whole directory can be deleted once a release carries
the change. `docs/TODO.md` tracks the removal.

## Tooling

`patches/` is excluded from the linters and secret scanners in
`.pre-commit-config.yaml`. Upstream code is not ours to reformat, and its
credential-handling code paths produce nothing but false positives.
