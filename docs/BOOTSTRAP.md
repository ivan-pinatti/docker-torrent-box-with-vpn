# What `make bootstrap` does

`make bootstrap` is the one command for first-time setup. See
[README §2](../README.md#2-run-make-bootstrap) for the quick version; this
page is the full internals.

The stack runs containers as a non-root user (uid=1000 inside the container).
Under rootless Podman, uid=1000 inside a container maps to a sub-uid on the
host, not to your login user. `make bootstrap` takes care of all of this in
one pass:

1. Detects `UID`, `GID`, and `TIMEZONE` from your host and writes them into
   `.env` for you, creating `.env` from `.env.example` first if it doesn't
   exist yet.
2. Checks that `configs/gluetun/.secret` has been filled in with your own
   WireGuard key (see [docs/VPN_PROVIDERS.md](VPN_PROVIDERS.md)): in a
   terminal it walks through a full guided setup for Proton VPN, or points
   elsewhere for any other provider, if it's still missing or the example
   placeholder; in a non-interactive run it stops with instructions instead.
3. Remaps managed data, config, and storage paths into the container user
   namespace, and seeds every app's config from its committed `.example`
   templates.
4. Generates the self-signed certificate if one doesn't already exist (see
   [README's Certificate section](../README.md#certificate), or
   [docs/CERTIFICATES.md](CERTIFICATES.md) for the full reference).
5. Builds the two custom images (LazyLibrarian, Mylar) with
   `make build_images`, so a fresh clone never fails to start those two
   just because they use a locally built image rather than a pulled one.
   See [docs/LAZYLIBRARIAN.md](LAZYLIBRARIAN.md) and
   [docs/MYLAR.md](MYLAR.md).
6. Starts the stack (`make start`), then waits up to 90 seconds for Gluetun
   to actually report a connected VPN before continuing. If that times out
   (wrong key, or provider/server settings in `configs/gluetun/.env` that
   don't match your account), bootstrap stops with an error instead of
   continuing into confusing failures further down the chain.
7. Once Gluetun is confirmed connected, applies the Jellyfin base
   URL/trusted proxy settings from `JELLYFIN_BASE_URL` and
   `JELLYFIN_KNOWN_PROXY` now that Jellyfin has generated its own config.
8. Wires the app-to-app connections that only exist through each app's own
   live API (qBittorrent/SABnzbd as download clients in the Servarr apps,
   those apps registered in Prowlarr), and attempts the first-run setup that
   Jellyfin, Audiobookshelf, Calibre's content server, and Calibre-Web each
   otherwise need through their own web UI before they have any usable
   account at all. That reliably succeeds for three of the four; Jellyfin's
   is unreliable for reasons not fully understood, and usually needs a
   one-time visit to `http://localhost:${JELLYFIN_HTTP_PORT}/` in a browser
   (which completes it immediately). See
   [docs/CONNECTIONS.md](CONNECTIONS.md) for exactly what this covers, and
   `make wire_connections` to re-run just this step later (after enabling an
   app that was disabled, for instance).
9. Rotates every seeded API key and password (`make rotate_all`), so a
   fresh clone is fully secured the moment bootstrap finishes.

It's meant to run once. See [docs/ROTATION.md](ROTATION.md) to rotate again
later, and [docs/HARDENING.md](HARDENING.md) for the full permissions
explanation. [docs/PERMISSIONS.md](PERMISSIONS.md) covers the ownership
model itself and the `make permissions_check` / `permissions_repair` /
`permissions_smoke` commands in more depth. For `make bootstrap_tests` (the
release-validation variant) and everything else test related, see
[docs/TESTING.md](TESTING.md).
