# Todo

## General / Security

- [ ] Enhance the library update process
- [ ] Research Dependabot/Renovate for Docker image versions; docker-compose
  image versions should be managed by Renovate rather than living in the
  compose file
- [ ] Fix python version w/ GHA
- [ ] Rotate passwords, including working out the KDF the apps use so
  rotated passwords can be generated with OpenSSL, see
  [Lidarr's UserService.cs](https://github.com/Lidarr/Lidarr/blob/6ec298ed2a9653863b8cea33e7174d50d37b5fcc/src/NzbDrone.Core/Authentication/UserService.cs#L22)
- [ ] Strip API key secrets from nginx logs, see
  [Jellyfin's nginx docs](https://jellyfin.org/docs/general/networking/nginx/#censor-sensitive-information-in-logs)
- [ ] Rotate API keys (all services, including Jackett)
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

- [ ] Sonarr HTTPS
- [ ] Investigate database corruption

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
