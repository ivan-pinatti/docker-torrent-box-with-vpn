# App-to-App Connections

Most of this stack's config is seeded from `.example` templates at bootstrap,
so apps that read their connection settings from a flat config file already
know about each other on first boot. A handful of connections don't work that
way: they live in an app's own SQLite database, populated only through its
live API, which means nothing can pre-seed them the way a template does. This
document covers what those connections are, how they get created, and what's
already wired without any of this.

## Quick Reference

| What | Make target | Script |
| ---------------------------------- | ---------------------- | ------------------------------ |
| Download clients + Prowlarr apps | `make wire_connections` | `scripts/wire-connections.sh` |

`make bootstrap` runs this automatically, after the stack's first
`make start` and before it rotates every seeded credential
(`make rotate_all`) — wiring has to come first, since some rotations (
qBittorrent's in particular) read the current credential out of a
DownloadClients entry that only exists once wiring has run. Run it again by
hand any time: after enabling an app that was previously disabled, or just to
confirm everything is still wired. Every step checks for an existing entry
first, so re-running is always safe.

## What gets wired

### Download clients (Sonarr, Radarr, Lidarr, Readarr, Whisparr → qBittorrent, SABnzbd)

Each of these apps keeps its download clients in a `DownloadClients` SQLite
table, created through `POST /api/<version>/downloadclient`. The script:

- Waits (up to 3 minutes) for the app to answer its own `/system/status`,
  since this only makes sense against a running app, and `make start` doesn't
  wait for individual apps to finish warming up.
- Sets up the app's initial WebUI login (username = password = the app's own
  name, matching the README's login table) and relaxes
  `CertificateValidation` to `DisabledForLocalAddresses`, if neither has been
  done yet. Both are required before the app will accept a download client
  pointed at this stack's self-signed cert: `AuthenticationMethod=Forms`
  makes the app reject any `config/host` update, including one that only
  touches certificate validation, unless a WebUI login already exists.
- Fetches the app's own `/downloadclient/schema` for the QBittorrent and
  Sabnzbd implementations, which already carries every field at a sensible
  default, and only overrides what's actually connection-specific: host,
  port, credentials, and category. The category is always set explicitly
  rather than trusted from the schema default: qBittorrent's own
  `categories.json` uses each app's bare name (`radarr`, `sonarr`, ...), but
  e.g. Sonarr's own qBittorrent schema defaults to `tv-sonarr` instead of
  `sonarr` — qBittorrent doesn't validate the category on creation, it just
  silently creates an empty one, which would silently break the
  pre-configured save-path layout. SABnzbd's categories are genre-based
  (`tv`, `movies`, `music`, `ebooks`, `mature`) and validates strictly, so an
  unmatched category fails the request outright rather than creating one.
- Posts the client with `enable = true`.

### Prowlarr → Applications (Sonarr, Radarr, Lidarr, Readarr, Whisparr, LazyLibrarian, Mylar)

If Prowlarr is enabled (`PROWLARR_PROFILE`), the script registers each of
those apps as an Application via `POST /api/v1/applications`, so Prowlarr can
push indexer sync to them (`syncLevel: fullSync`). Skipped entirely, with a
note, if Prowlarr's container doesn't exist — the same no-op behavior
`scripts/rotate-api-keys.sh`'s `update_prowlarr_application()` already has
for a missing entry.

## What's already wired, and why this script doesn't touch it

- **Bazarr → Sonarr/Radarr**: `configs/bazarr/config/config/config.yaml.example`
  already ships `ip`/`port`/`base_url`/`ssl` filled in, and `apikey` matches
  Sonarr/Radarr's own placeholder key by construction (both derive from the
  same per-app canonical placeholder).
- **Mylar/LazyLibrarian → qBittorrent/SABnzbd**: their `config.ini.example`
  files are pre-filled the same way, since both apps are configured from a
  flat file rather than a database.

## Credentials this script sets up

Beyond the connections above, `ensure_arr_host_prereqs()` (used internally by
the download-client wiring) is the only place in this stack that creates an
arr app's initial WebUI login. Nothing else does this today: neither
bootstrap's config seeding (which only touches files, and this setting lives
in the database) nor `scripts/rotate-passwords.sh` (which only *rotates* an
existing login, and aborts if one isn't there yet). The seeded username and
password both equal the app's own name, matching the README's login table;
rotate it like any other seeded credential with `make rotate_passwords
SERVICE=<app>`.

## Troubleshooting

Run `make wire_connections` directly to see per-app output. A line like
`[lidarr] Not reachable, skipping.` means the app's container either doesn't
exist (its `*_PROFILE` is `disabled`) or didn't come up healthy within 3
minutes; nothing else in this document applies until it's addressed
separately. Every other failure surfaces the app's own validation error, if
any: rerun `./scripts/wire-connections.sh` directly (not the `make` wrapper)
to see the full curl output instead of a truncated summary.
