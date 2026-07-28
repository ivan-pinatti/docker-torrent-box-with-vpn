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
- [x] Disable automatic Docker image updates in all containers: no
  watchtower/auto-update mechanism exists, and `up` never re-pulls images on
  its own, so the only real drift risk was the handful of services still
  pinned to the `latest` tag. `nordvpn`/`plex` have no container definition
  left anywhere in the compose tree (dead `.env` vars, no risk); `mylar` and
  `jdownloader2` were actively running on `latest` and got pinned to the
  exact versions already running (`v0.9.0-ls252`, `v26.07.2`, confirmed via
  the running images' own version labels and a rebuild that reused the
  identical cached layer, so no functional change). Also synced
  `.env.example`'s stale `latest` defaults for `cadvisor`/`node_exporter` to
  match what `.env` already pins, so fresh clones get the same protection
- [ ] Add a VPN provider affiliate link
- [ ] Set up a firewall
- [ ] Find and inventory existing backups
- [ ] Automate backups
- [ ] Close remaining HTTP ports, allow access only through nginx

## Gluetun

- [ ] Verify IPv6 address handling and how to disable it

## Nginx

- [x] Investigate `NGINX_HOST=${DOMAIN}` in `configs/nginx/.env`: confirmed
  dead, like the removed *arr `PASSWORD` vars. Not referenced in
  `configs/nginx/templates/*.template` and not read by the official nginx
  image's own entrypoint scripts either (checked `/docker-entrypoint.d/` and
  `/docker-entrypoint.sh` inside the running container). The other two vars
  in that file are real: `JELLYFIN_PROXY_DOMAIN` is used in
  `default.conf.template`'s `server_name`, and
  `NGINX_ENTRYPOINT_LOCAL_RESOLVERS` drives the image's own
  `15-local-resolvers.envsh`. Removed `NGINX_HOST`; nginx recreated clean
  and healthy afterward

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

- [x] Restrict access for unlogged-in users: `restrictAdmin`,
  `restrictDetailsDl`, `restrictIndexerSelection`, `restrictSearch`, and
  `restrictStats` are all already `true` in the live config. Verified live:
  an unauthenticated request to the internal search API and to the home
  page both redirect to `/login` (302); the Newznab-compatible `/api`
  endpoint is separately protected by its own API key check regardless
- [x] Set cookie expiry to 1 day: `auth.rememberMeValidityDays` is already `1`
  in the live config (confirmed it survives container restarts, since
  NZBHydra2 flushes its own config back to `nzbhydra.yml` on shutdown)
- [ ] Add notifications (Apprise?)
- [ ] Fix failure adding to Lidarr, see
  [SSL verification errors wiki page](https://github.com/theotherp/nzbhydra2/wiki/SSL-verification-errors)

## Lidarr

- [ ] Lidarr is not configured for Indexers due to a restriction to add it

## Prowlarr

- [ ] Flaresolverr
- [ ] Indexers
- [ ] Auto config arrs
- [x] Decide how Prowlarr should trust the self-signed certificate for the
  LazyLibrarian and Mylar HTTPS application entries. Resolved (per Ivan)

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
  [MylarComics/mylar3#23](https://github.com/MylarComics/mylar3/pull/23)
  merged into `nightly` on 2026-07-23 but hasn't reached a stable release
  yet. See `docs/MYLAR.md` for the check to run before removing the patch

## Whisparr

- [x] Re-enable the password once the upstream bug is fixed: already
  re-enabled. `config.xml` shows `AuthenticationMethod=Forms`,
  `AuthenticationRequired=Enabled`, matching its Servarr siblings; verified
  live that an unauthenticated request gets a real `401` redirecting to
  `/login`. `rotate-passwords.sh`/`rotate-api-keys.sh` treat it identically
  to every other arr app with no special-casing, and Prowlarr has it
  registered as a synced application with no active failure/disable state
  and no related errors in recent logs. The original bug reference is lost
  (introduced from a root `TODO.md` that was never tracked by git, so no
  history survived the merge in `dc14c98`); likely candidate is the
  documented Prowlarr↔Whisparr Basic-auth-challenge sync bug, not currently
  reproducing here

## Test Suite

Found running `make test` after the 2026-07-27 Prowlarr/Sonarr/Radarr version
bump (2.5.2/6.3.0/4.0.19). None of the arr-specific tests (health checks, API
key rotation, password rotation) failed, so these look pre-existing rather
than caused by that update, but they still need fixing:

- [x] `docker-py` container references go stale mid-session against the
  podman socket: once a container is stopped/recreated (as the rotation and
  rinse-and-repeat tests do earlier in the same `pytest` run), later
  `container.exec_run()` calls against the old cached ID 404 with
  `docker.errors.NotFound`. Fixed by adding `fresh_container()` in
  `conftest.py`, re-fetched by name right before each `exec_run()` in
  `tests/test_security.py`, instead of reusing the session-fixture object.
  Reproduced and confirmed the fix directly: force-recreated a container
  mid-session, the stale object 404s while a freshly-fetched one works
- [x] `test_capabilities_dropped` in `tests/test_security.py` asserted the
  literal string `"ALL"` appears in `CapDrop`, but podman's Docker-compatible
  API reports the fully expanded default-capability list instead. This
  surfaced a real, separate gap while fixing it: `cap_drop: ALL` was
  completely missing (not just misreported) from the compose blocks for
  sonarr, radarr, bazarr, lidarr, prowlarr, readarr, whisparr (via the
  shared `x-servarr-common` anchor), qbittorrent, sabnzbd, and jellyfin,
  confirmed via `/proc/1/status` (`CapBnd` non-zero) despite the 2.2.x
  changelog claiming all containers were hardened with it. Tried adding
  `cap_drop: [ALL]` to all ten and it broke every one of them:
  s6-overlay's root-to-PUID/PGID privilege drop needs `CAP_SETGID` for its
  `setgroups()` call, and `s6-applyuidgid: fatal: unable to set
  supplementary group list: Operation not permitted` crash-loops them.
  Reverted the compose change (confirmed clean, containers healthy again);
  these ten structurally cannot reach zero capabilities without breaking
  their own startup. Fixed the test instead to assert the achievable
  invariant per group: full drop for services that can reach it, and "no
  capability added beyond the default floor" for the ten that need it
  (tracked as `ROOT_INIT_SERVICES` in the test file)
- [x] Grafana dashboard tests in `tests/test_observability.py` read dashboard
  JSON straight from `configs/grafana/config/provisioning/dashboards/<file>.json`,
  but the dashboards were reorganized into subfolders
  (`downloaders/`, `node_containers/`, `torrent_box/`) without updating the
  tests, so every one 404s with `FileNotFoundError`. Fixed the paths; also
  caught a stale panel title (`Network I/O` renamed to `VPN Network I/O`) in
  the same run
- [x] `tests/test_auth.py::test_qbittorrent_api_login` and
  `test_qbittorrent_web_session_login` failed with a login `'Fails.'`
  response. Not a health-check timing issue: the tests read
  `QBITTORRENT_PASSWORD` from root `.env`, but `rotate-passwords.sh` only
  ever writes the rotated password to `configs/qbittorrent/.env.secrets`, so
  they always fell back to the placeholder password and failed with a real
  credential mismatch. Fixed to read the actual secrets file.
  `test_containers.py::test_container_healthy` also read a stale `Health`
  snapshot captured once at session-fixture creation; fixed to reload and
  retry via `wait_for_healthy` before asserting
- [x] `tests/test_compose_config.py::test_homepage_group_and_media_ordering`
  expects the indexers/downloaders group ordered
  `[..., 'NZBHydra2']` but got `JDownloader2` appended instead; homepage
  config and test have drifted apart. Updated the expected order to include
  `JDownloader2`
- [x] `tests/test_rinse_and_repeat.py::test_stop_then_start[1]` hit a
  transient podman IPAM error (`requested ip address 172.30.0.10 is already
  allocated`) on the first stop/start cycle; passed clean on the immediate
  retry (`[2]`). Root cause: the `media` network (nginx's static IP lives on
  it) was never added to `start:`'s "ensure required networks exist"
  pre-check, unlike `apps`/`services`/`observability`, so it relied entirely
  on podman-compose's own automatic network creation during `up`, racing
  under the same category of bug those three were already worked around for.
  `start_library:` already had the correct line (`network exists ... media
  || network create --subnet ${MEDIA_SUBNET} ... media`); `start:` just
  never got it. Added it; ran `test_stop_then_start` and
  `test_down_then_start` (2 cycles each) clean afterward. That alone wasn't
  sufficient though: a subsequent `make start` still hit the exact same
  IPAM error, this time with `calibre` (a dynamically-addressed container)
  holding nginx's static IP, because nothing reserved `172.30.0.10` out of
  the dynamic pool, so whichever container asked for an address first could
  get it. Added `MEDIA_DYNAMIC_IP_RANGE=172.30.0.16/28` (`.env`,
  `.env.example`) and wired it into the `media` network's `ip_range` in
  `docker-compose.yml` and the two `podman network create` calls in the
  Makefile, so dynamic allocation can no longer touch nginx's reserved
  address. Verified after recreating the network: nginx holds `.10`,
  jellyfin/audiobookshelf/calibre/calibre-web/korsync/homepage all land in
  `.16`-`.31` with no collisions
- [x] `tests/test_observability.py::test_grafana_dashboards_provisioned`
  expected dashboard titles `Node Exporter - Overview`, `qBittorrent -
  Overview`, `SABnzbd Dashboard`, but Grafana now reports the shortened
  titles `Node Exporter`, `qBittorrent`, `SABnzbd` (dashboards were renamed
  at some point after the file-path reorg). Updated the expected set to
  match. Also added a `pw_rotation` marker (on top of the existing
  `rotation` marker, which covers both password and API-key rotation) and a
  `make test_no_rotate_passwords` target, so the two can be selected
  independently — `pytest -m rotation` still means "both", `-m pw_rotation`
  or `-m "not pw_rotation"` scopes to password rotation alone (named to
  dodge a detect-secrets false positive: any marker name containing
  "password" before the colon gets flagged as a Secret Keyword). Ran the
  full suite twice with it: the first run had 1
  failure (this dashboard title mismatch) plus 2 connection-refused errors
  and a garbled homepage widget-check failure; the cause of those latter
  three wasn't identified (collection order rules out
  `test_rinse_and_repeat.py`, which runs after both), but they didn't
  reproduce on an immediate re-run in isolation or on a second full run
  (295 passed, 9 skipped, 0 failed) after the dashboard fix, so treated as a
  one-off environmental blip rather than a real bug

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
