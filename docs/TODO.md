# Todo

Open items only. Resolved work lives in git history, not here; see `git log`
for what was fixed and when.

## General / Security

- [ ] Enhance the library update process
- [ ] Research Dependabot/Renovate for Docker image versions; docker-compose
  image versions should be managed by Renovate rather than living in the
  compose file
- [ ] Fix python version w/ GHA
- [ ] Strip API key secrets from nginx logs, see
  [Jellyfin's nginx docs](https://jellyfin.org/docs/general/networking/nginx/#censor-sensitive-information-in-logs)
- [ ] Move certificate info to a dedicated folder
- [ ] Add k6 load testing
- [ ] Add a VPN provider affiliate link
- [ ] Set up a firewall
- [ ] Find and inventory existing backups
- [ ] Automate backups
- [ ] Close remaining HTTP ports, allow access only through nginx

## Gluetun

- [ ] Verify IPv6 address handling and how to disable it

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

## NZBHydra2

- [ ] Add notifications (Apprise?)
- [ ] Fix failure adding to Lidarr, see
  [SSL verification errors wiki page](https://github.com/theotherp/nzbhydra2/wiki/SSL-verification-errors)

## Lidarr

- [ ] Lidarr is not configured for Indexers due to a restriction to add it

## Prowlarr

- [ ] Flaresolverr
- [ ] Indexers
- [ ] Auto config arrs

## Calibre

- [ ] Investigate why the desktop GUI/content server sometimes takes 90s to
  300s+ to come up (vs. 4-8s in isolation), specifically during mass
  simultaneous container startup (`make start` bringing up the whole stack,
  or `rotate-passwords.sh`'s own cascading stop/start/recreate activity).
  Confirmed via direct log capture: `svc-de` is an s6 "longrun" service
  whose `run` script does `wait "$PID"; exit 1` on the underlying
  calibre/labwc process, so whenever that process exits for any reason, s6
  automatically relaunches it with a fresh PID; this is what both the
  spontaneous recovery (seen during a plain `make start`, no self-heal
  logic involved) and `rotate-passwords.sh`'s manual
  `s6-svc -r /run/service/svc-de` self-heal actually trigger. What's not
  found: why the first attempt's process exits/goes idle in the first
  place: no crash or error appears in the container logs at the moment it
  happens. Tested and ruled out as the sole cause: CPU quota (0.5 vs 1 vs 2
  CPUs made no difference to the worst case under real load, though 0.5 did
  show genuine throttling in isolation and 1 is the current setting),
  sustained concurrent `podman exec` load against other containers alone,
  and a long stopped period alone or combined with the load test; none of
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
  [MylarComics/mylar3#23](https://github.com/MylarComics/mylar3/pull/23)
  merged into `nightly` on 2026-07-23 but hasn't reached a stable release
  yet. See `docs/MYLAR.md` for the check to run before removing the patch

## jDownloader2

- [ ] Drop `patches/jdownloader2/10-webauth.sh` once it is no longer needed.
  Upstream fixed `load_env_var()` in `docker-baseimage-gui` version 4.13.0
  (2026-08-06), confirmed via the maintainer's own comment closing #196. But
  `docker-jdownloader-2`'s own Dockerfile still pins `baseimage-gui:alpine-3.24-v4.12.6`
  as of its last commit (2026-07-12) and no image tag newer than
  `v26.07.2` has been published, so the fix has not reached the actual
  `jlesage/jdownloader-2` image yet and the patch still applies. Check
  `docker-jdownloader-2`'s Dockerfile for a `baseimage-gui` bump to 4.13.0+
  before removing this patch

## Test Suite

- [ ] Deluge, Notifiarr, and Jackett have zero pytest coverage. Found while
  building `make bootstrap_tests` (2026-08-06): `conftest.py`'s `SERVICES`
  dict doesn't register Deluge or Notifiarr at all, so no generic
  container/security/health test ever touches them regardless of profile
  state, and Jackett is already documented as deliberately out of scope
  (`.env.example`: "managed manually and is not covered by Renovate or
  pytest layers"). `.env.tests` (the override file `bootstrap_tests`
  applies) intentionally leaves all three disabled for the same reason.
  Deluge and Notifiarr look like plain oversights rather than a deliberate
  exclusion like Jackett's; worth real coverage if either is meant to be a
  first-class supported service
