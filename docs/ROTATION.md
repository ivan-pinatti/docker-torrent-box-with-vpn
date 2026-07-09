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
`prowlarr`, `bazarr`, `all`.

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

Apps whose key was rewritten on disk are recreated automatically at the end
(`podman-compose up -d --force-recreate`) so they load the new key. The
summary table masks the keys (`first4****`).

## Passwords (`rotate-passwords.sh`)

Valid targets: the API key list plus `qbittorrent` and `sabnzbd`.

- **Servarr apps**: the new login password is set through each app's host
  config API, which hashes it internally.
- **Bazarr**: writes the MD5 hash of the new password to `config.yaml`
  (Bazarr stores MD5 by design).
- **qBittorrent**: logs into the WebUI API with the current password (read
  from Sonarr's download client settings), sets the new one, then updates the
  `DownloadClients` tables of Sonarr, Radarr, Lidarr, Readarr, and Whisparr,
  plus `configs/qbittorrent/.env.secrets` and
  `configs/qbittorrent_exporter/.env.secrets`.
- **SABnzbd**: rotates the password, API key, and NZB key together. Updates
  `configs/sabnzbd/config/sabnzbd.ini`, `.env` and
  `configs/sabnzbd/.env.secrets`, the Servarr `DownloadClients` tables,
  LazyLibrarian, Mylar, and Notifiarr.

Passwords are only ever printed masked (`first4****`). Some apps cache
credentials in memory; run `make restart` if a login fails after rotation.

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
permissions are enforced after generation: `600` for `server.key` and
`server.pfx`, `644` for `server.crt`. The script prints the recreate command
for the affected containers at the end; run it for the new certificate to
take effect.

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

- **Jellyfin and Audiobookshelf API keys** used by Homepage must be rotated
  manually; see [DEPENDENCIES.md](DEPENDENCIES.md).
- **Jackett** is legacy and not covered by any rotation script.
- **Gluetun's WireGuard private key** lives in `configs/gluetun/.secret`;
  rotate it by generating a new config with your VPN provider.
