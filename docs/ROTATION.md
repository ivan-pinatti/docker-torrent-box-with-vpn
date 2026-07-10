# Credential and Certificate Rotation

The stack ships with pre-configured API keys and passwords. Rotate all of them
before exposing anything beyond your own machine. The scripts below rotate a
credential in the app that owns it and then sync the new value into every
consumer, so the integrations keep working.

## Quick Reference

| What                    | Make target               | Script                          |
| ----------------------- | ------------------------- | ------------------------------- |
| API keys and passwords  | `make rotate_all`         | `scripts/rotate-all.sh`         |
| API keys only           | `make rotate_api_keys`    | `scripts/rotate-api-keys.sh`    |
| Login passwords only    | `make rotate_passwords`   | `scripts/rotate-passwords.sh`   |
| Self-signed certificate | `make rotate_certificate` | `scripts/rotate-certificate.sh` |
| Nginx host logs         | `make rotate_nginx_logs`  | `scripts/rotate-nginx-logs.sh`  |

All rotation targets accept `SERVICE=<name>` to limit the scope:

```shell
make rotate_all                     # everything
make rotate_all SERVICE=sonarr      # one service, keys and password
make rotate_api_keys SERVICE=radarr
make rotate_passwords SERVICE=qbittorrent
```

The stack must be running for API key and password rotation, because parts of
the process go through each app's own API (via `podman exec` into the app
container). Certificate and log rotation work on files only.

## API Keys (`rotate-api-keys.sh`)

Valid targets: `sonarr`, `radarr`, `lidarr`, `readarr`, `whisparr`,
`prowlarr`, `bazarr`, `lazylibrarian`, `mylar`, `nzbhydra2`, `jellyfin`,
`all`.

For each Servarr app the script writes a new `ApiKey` into the app's
`config.xml` (the apps ignore key changes sent over their API), then updates
every consumer of that key:

- The matching application entry in Prowlarr (over the Prowlarr API).
- Bazarr's `sonarr.apikey` and `radarr.apikey` in
  `configs/bazarr/config/config/config.yaml`.
- Recyclarr's `sonarr_apikey` and `radarr_apikey` in
  `configs/recyclarr/config/secrets.yml`.
- Homepage's `HOMEPAGE_VAR_*_API_KEY` entries in
  `configs/homepage/.env.secrets`.

The non-Servarr targets:

- **LazyLibrarian** and **Mylar** keep their key in `config.ini` and persist
  their in-memory config on shutdown, so the script stops the container,
  edits the file, and starts it again. Their Prowlarr application entries
  (and Homepage for Mylar) are updated too.
- **NZBHydra2** gets a new `main.apiKey` in `nzbhydra.yml` (written in plain
  text; NZBHydra re-obfuscates it on its next save). Consumers updated: the
  `Indexers` tables of all five Servarr databases, LazyLibrarian's Newznab
  and Torznab entries, and Mylar's `extra_newznabs`/`extra_torznabs` lines.
- **Jellyfin** keys cannot be chosen, so the script creates a new key over
  the Jellyfin API, stores it for Homepage, and revokes the old one.

Apps whose key was rewritten on disk are restarted or recreated
automatically so they load the new key, and Homepage is recreated to pick up
the new env values. The summary table masks the keys (`first4****`); the
actual values live in the respective config files.

## Passwords (`rotate-passwords.sh`)

Valid targets: `sonarr`, `radarr`, `lidarr`, `readarr`, `whisparr`,
`prowlarr`, `bazarr`, `qbittorrent`, `sabnzbd`, `lazylibrarian`, `mylar`,
`calibreweb`, `grafana`, `nzbhydra2`, `all`.

- **Servarr apps**: the new login password is set through each app's host
  config API, which hashes it internally.
- **Bazarr**: writes the MD5 hash of the new password to `config.yaml`
  (Bazarr stores MD5 by design).
- **qBittorrent**: logs into the WebUI API with the current password (read
  from Sonarr's download client settings), sets the new one, then updates
  every consumer: the `DownloadClients` tables of all five Servarr apps,
  LazyLibrarian's and Mylar's download client settings,
  `configs/qbittorrent/.env.secrets`,
  `configs/qbittorrent_exporter/.env.secrets`, and Homepage.
- **SABnzbd**: rotates the password, API key, and NZB key together. Updates
  `configs/sabnzbd/config/sabnzbd.ini`, `.env` and
  `configs/sabnzbd/.env.secrets`, the Servarr `DownloadClients` tables,
  LazyLibrarian, Mylar, Notifiarr, and Homepage.
- **LazyLibrarian** and **Mylar**: WebUI passwords in their `config.ini`.
- **Calibre-Web**: writes a new password hash for the `calibre` user
  directly to `app.db` (no API exists) and updates Homepage.
- **Grafana**: changes the admin password over Grafana's API, then keeps
  `grafana.ini` and Homepage's Basic auth header in sync.
- **NZBHydra2**: writes a new bcrypt hash to `nzbhydra.yml`.

Every file or database edit follows the stop, edit, start pattern: apps read
their config only at startup and persist in-memory state on shutdown, which
would clobber a live edit. Only changes made through an app's own API happen
while it runs. Both scripts end with a validation phase that proves each
rotated credential is accepted by its service (login or API probe, with
retries while containers come back up) and exit nonzero if any check fails.

The summary table prints the new passwords **in full**: the apps store only
hashes, so the table is the single opportunity to record them. Save them in
your password manager immediately. Some apps cache credentials in memory;
run `make restart` if a login fails after rotation.

## Combined (`rotate-all.sh`)

Runs the API key rotation followed by the password rotation for the same
target. Defaults to `all` when no target is given. This is what
`make rotate_all` calls.

## Certificate (`rotate-certificate.sh`)

Regenerates `certs/server.key`, `certs/server.crt`, and `certs/server.pfx`
with a new random PKCS#12 password, then syncs that password into every
consumer:

- `SslCertPassword` in the `config.xml` of Lidarr, Prowlarr, Radarr, Readarr,
  Sonarr, and Whisparr (apps with SSL disabled are skipped).
- `CertificatePassword` in Jellyfin's `network.xml`.
- `sslKeyStorePassword` in NZBHydra2's `nzbhydra.yml`.

The new password is stored in `certs/cert.conf`, which is gitignored. File
permissions are normalized to `644` after generation: the certificate files
are read by many services running as distinct non-root container UIDs under
rootless Podman, so they must stay world-readable. The script prints the
recreate command for the affected containers at the end; run it for the new
certificate to take effect.

Subject and SAN fields come from `certs/cert.conf` and `.env`
(`JELLYFIN_PROXY_DOMAIN`, `LAN_IP`, `GLUETUN_SERVICES_IP`,
`GLUETUN_OBSERVABILITY_IP`). For the initial certificate use
`make generate_certificate` instead; the rotate script is for replacing an
existing one.

## Nginx Logs (`rotate-nginx-logs.sh`)

Copies each `*.log` under the nginx log directory to a timestamped file and
truncates the original, then compresses rotated files older than
`LOG_RETENTION_DAYS` and deletes archives older than
`LOG_ARCHIVE_RETENTION_DAYS`. Runs daily via the log rotator container
(`LOG_ROTATION_CRON`); see [Growth Controls](GROWTH_CONTROLS.md).

## Out of Scope

- **Audiobookshelf's token** used by Homepage is a per-user JWT that must be
  rotated manually in the Audiobookshelf UI; see
  [DEPENDENCIES.md](DEPENDENCIES.md).
- **Calibre's desktop content server** credentials are managed in Calibre's
  own user database.
- **Jackett** is legacy and not covered by any rotation script.
- **Gluetun's WireGuard private key** lives in `configs/gluetun/.secret`;
  rotate it by generating a new config with your VPN provider.
