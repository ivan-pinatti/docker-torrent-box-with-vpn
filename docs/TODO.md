# Todo

## General / Security

- [ ] Replace tracked live configs with a curated basic setup for fresh
  clones. The runtime SQLite databases were untracked and gitignored on
  2026-07-09: pre-commit's stash cycle rewrote them mid-commit on 2026-07-07
  while services were running, corrupting the sonarr, radarr, lidarr, and
  readarr databases (recovered from app backups; corrupt copies preserved
  under `backup/db-corruption-20260709-150443/`). Old database contents are
  still in git history; purging them requires a history rewrite
  (`git filter-repo`) plus a force push. Until the baseline config exists,
  live configs stay uncommitted and commits should be avoided while the
  stack is running
- [ ] Enhance the library update process
- [ ] Research Dependabot/Renovate for Docker image versions; docker-compose
  image versions should be managed by Renovate rather than living in the
  compose file
- [ ] Fix python version w/ GHA
- [x] Rotate passwords, implemented by `scripts/rotate-passwords.sh` through
  each app's host config API, which hashes them internally, so no local KDF
  work is needed. See [ROTATION.md](ROTATION.md)
- [ ] Strip API key secrets from nginx logs, see
  [Jellyfin's nginx docs](https://jellyfin.org/docs/general/networking/nginx/#censor-sensitive-information-in-logs)
- [x] Rotate API keys, implemented by `scripts/rotate-api-keys.sh` for the
  Servarr apps and Bazarr. Jackett is legacy and stays out of scope. See
  [ROTATION.md](ROTATION.md)
- [ ] Move certificate info to a dedicated folder
- [ ] Add k6 load testing
- [ ] Disable automatic Docker image updates in all containers
- [ ] Add a VPN provider affiliate link
- [ ] Set up a firewall
- [ ] Find and inventory existing backups
- [ ] Automate backups
- [ ] Close remaining HTTP ports, allow access only through nginx

## Gluetun

- [ ] Verify IPv6 address handling and how to disable it

## Nginx

- [ ] Investigate `NGINX_HOST=${DOMAIN}` in `configs/nginx/.env`: `DOMAIN` was
  undefined in root `.env` (now added), but it's unconfirmed whether any
  nginx config/template in this repo actually reads `NGINX_HOST` at all, or
  if it's dead config left over like the removed *arr `PASSWORD` vars

## qBittorrent

- [ ] Set up an nginx reverse proxy for the WebUI, see
  [qBittorrent's NGINX reverse proxy wiki page](https://github.com/qbittorrent/qBittorrent/wiki/NGINX-Reverse-Proxy-for-Web-UI)
- [ ] Review and set upload/download speed limits

Needs review (flagged instead of carried as firm todos: qBittorrent already
runs inside gluetun's namespace with a structural VPN killswitch, so it's
unclear whether these still add value; couldn't confirm against trash-guides
recommendations):

- [ ] Enable Anonymous Mode
- [ ] Disable Local Peer Discovery
- [ ] Disable the rate limit exemption for LAN peers

## Jackett

- [ ] Add an OMDb key

## Sonarr

- [ ] Sonarr HTTPS: working setup steps are documented in the README known
  issues section (SslCertPath/SslCertPassword in config.xml plus EnableSsl);
  fold them into the future baseline config
- [x] Investigate database corruption: caused by pre-commit stashing the
  tracked live database during a commit while Sonarr was running, see the
  runtime configs entry under General / Security

## NZBHydra2

- [ ] Restrict access for unlogged-in users
- [ ] Set cookie expiry to 1 day
- [ ] Add notifications (Apprise?)
- [ ] Fix failure adding to Lidarr, see
  [SSL verification errors wiki page](https://github.com/theotherp/nzbhydra2/wiki/SSL-verification-errors)

## Lidarr

- [ ] Lidarr is not configured for Indexers due to a restriction to add it

## Prowlarr

- [ ] Flaresolverr
- [ ] Indexers
- [ ] Auto config arrs
- [ ] Decide how Prowlarr should trust the self-signed certificate for the
  LazyLibrarian and Mylar HTTPS application entries. Prowlarr validates
  certificates for DNS-name hosts, so sync tests to those two apps fail TLS
  and their rotation updates use forceSave. Options: set Prowlarr's
  CertificateValidation to Disabled (everything is on internal networks), or
  issue a certificate with SANs for the service aliases

## Calibre

- [ ] Investigate why the desktop GUI/content server sometimes takes 90s to
  300s+ to come up (vs. 4-8s in isolation), specifically during mass
  simultaneous container startup (`make start` bringing up the whole stack,
  or `rotate-passwords.sh`'s own cascading stop/start/recreate activity).
  Confirmed via direct log capture: `svc-de` is an s6 "longrun" service
  whose `run` script does `wait "$PID"; exit 1` on the underlying
  calibre/labwc process, so whenever that process exits for any reason, s6
  automatically relaunches it with a fresh PID — this is what both the
  spontaneous recovery (seen during a plain `make start`, no self-heal
  logic involved) and `rotate-passwords.sh`'s manual
  `s6-svc -r /run/service/svc-de` self-heal actually trigger. What's not
  found: why the first attempt's process exits/goes idle in the first
  place — no crash or error appears in the container logs at the moment it
  happens. Tested and ruled out as the sole cause: CPU quota (0.5 vs 1 vs 2
  CPUs made no difference to the worst case under real load, though 0.5 did
  show genuine throttling in isolation and 1 is the current setting),
  sustained concurrent `podman exec` load against other containers alone,
  and a long stopped period alone or combined with the load test — none of
  these reproduce it outside an actual mass-startup event. See
  [README.md known issue #6](../README.md#known-issues-and-future-improvements)
  and `docs/ROTATION.md` for the current mitigation
  (`validate_calibre()` in `scripts/rotate-passwords.sh`). Not filed
  upstream: without a minimal reproduction outside the full stack's
  concurrent startup, a report to `linuxserver/docker-calibre` wouldn't be
  actionable for the maintainers.

## Mylar

- [ ] Mylar + NZBget HTTPS. The qBittorrent side is already fixed via a
  local patch (`patches/mylar/`); upstream PR
  [MylarComics/mylar3#23](https://github.com/MylarComics/mylar3/pull/23) is
  still open

## Whisparr

- [ ] Re-enable the password once the upstream bug is fixed

## In Progress

## Won't do

## Done

2.2.x

- [x] Containers run as non-root (PUID=${UID}/PGID=${GID}). s6-overlay starts as root to
  drop privileges; the app process runs as the configured user.
- [x] All containers hardened with no-new-privileges and cap_drop: ALL. Exceptions: gluetun
  (needs NET_ADMIN/NET_RAW), cadvisor (needs privileged), podman_exporter (uses userns_mode).

2.1.x

- [x] DOCS - Updated to add required binaries for xmlstarlet and yq
- [x] DOCS - Wireguard is required in the host machine
- [x] DOCS - Added the requirements section and the make check_requirements command
- [x] MAKE - Improvement in generate_certificate, now it updates SSL keys in apps configurations
- [x] MAKE - Added the check_requirements command
- [x] Docker - All containers are now limited to 1 CPU and 1 GB memory
- [x] Docker Compose - Version in docker-compose file is obsolete, removed
- [x] All Services - All versions are now locked to the latest working
- [x] All Services - Removed the general .env from the containers configuration,
  only specific .env for each service now
- [x] All Services - Removed secrets as new images don't have the option anymore
- [x] ProtonVPN - Added the --p2p option to ProtonVPN container
- [x] ProtonVPN - Moved the secret into the .secret file for improved security
- [x] Whisparr - Added to the stack
- [x] Jellyfin - Added to the stack
- [x] Docker Compose - Switch from docker-compose to docker compose

2.1.4

- [x] Fix pre-commit docker-compose hook

2.0.1

- [x] Added backup entries to .gitignore
- [x] Added certs to the backup
- [x] Rearranging Github files
- [x] Automate semantic versioning
- [x] Automate release generation
- [x] Adding devContainers to the repository to facilitate development
- [x] Plex network changed to `host` for better performance
- [x] Added support for NordVPN (untested)

2.0.0

- [x] Augment the stack to use a reverse proxy w/ https
- [x] Add Lazylibrarian to Prowlarr
- [x] Added Prowlarr to the stack
- [x] Config HTTPS available services
- [x] Create the script to generate self-certificate
- [x] Add Stale bot
- [x] Pre-commit hooks - Linting, security, etc...
- [x] Added restart to Makefile
- [x] Added ports 6881 and 6881/udp to qBittorrent container
- [x] Made the `docker-compose` file more compact
- [x] Remove the `depends_on` clause from the containers to make it more customizable
- [x] Add the option to select to enable/disable apps
- [x] Fix the text for the `make clean`
- [x] Flaresolverr typo (missing an R)
- [x] Flaresolverr doesn't have a captcha solver - investigate
- [x] Create my first TODO.md
- [x] Add more tasks to Makefile
