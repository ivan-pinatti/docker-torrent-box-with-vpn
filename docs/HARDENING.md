# Container Security Hardening

This document describes the security measures applied to containers in this stack and the
rationale behind each decision.

## Threat model

The stack runs on a single host behind a LAN. The goal is containment: if a container is
compromised (e.g. via a vulnerability in a media app), the attacker should not be able to
escalate to the host user, read unrelated container data, or gain Linux capabilities they
do not need.

## Measures applied

### Non-root process user (PUID/PGID)

All linuxserver.io and hotio images accept `PUID` and `PGID` environment variables. The
container init (s6-overlay) starts as root to set up the environment, then drops to the
configured user before exec'ing the application. Setting `PUID=${UID}` and `PGID=${GID}`
means the running application is uid=1000, not uid=0.

`PUID=0`/`PGID=0` (which was the previous default) defeats this entirely: the application
itself runs as root inside the container.

For images that use a `user:` field instead of PUID/PGID (recyclarr, prometheus, grafana),
the same principle applies via the Compose `user:` key.

### `no-new-privileges`

```yaml
security_opt:
  - no-new-privileges:true
```

Applied to every container except gluetun, cadvisor, podman_exporter, and
podman_limits_exporter (see exceptions below). Prevents any process inside the container
from gaining additional privileges via setuid/setcap binaries or execve. This is a
kernel-level guarantee and is safe for all images in this stack.

### `cap_drop: ALL`

```yaml
cap_drop: [ALL]
```

Applied to containers whose init does not need Linux capabilities to function:

| Container(s) | cap_drop applied | Reason |
| --- | --- | --- |
| nginx | `cap_drop: ALL` + `cap_add: [CHOWN, SETUID, SETGID, NET_BIND_SERVICE]` | Master chowns temp dirs, forks workers as `nginx` user (uid 101), and binds to ports 80/443 |
| alloy | `cap_drop: ALL` + `cap_add: [DAC_READ_SEARCH]` | Needs to read log files owned by other services' PUIDs |
| prometheus, grafana, loki | yes | Static binary / Go service |
| node_exporter, nginx_exporter, qbittorrent_exporter, sabnzbd_exporter | yes | Read-only exporters |
| recyclarr, flaresolverr, homepage, audiobookshelf, korsync, log_rotator | yes | No s6-overlay privilege switching |

**Not applied** to linuxserver/hotio images (sonarr, radarr, jellyfin, qbittorrent, sabnzbd,
legacy nzbget, etc.): s6-overlay needs `CAP_CHOWN` to transfer `/config` ownership to PUID,
and `CAP_SETUID`/`CAP_SETGID` to drop from uid=0 to PUID. Dropping all capabilities before
those operations silently prevents the privilege switch, leaving the app running as root
regardless of the PUID setting.

### IPv6 disabled

```yaml
sysctls:
  - net.ipv6.conf.all.disable_ipv6=1
  - net.ipv6.conf.default.disable_ipv6=1
  - net.ipv6.conf.lo.disable_ipv6=1
```

Applied to standalone services and exporters. Prevents accidental traffic from
bypassing the VPN via IPv6 where a container has its own network namespace.

`qbittorrent`, `sabnzbd`, and legacy `nzbget` inherit gluetun's network
namespace, so their container-level IPv6 settings are controlled by gluetun.
Gluetun intentionally keeps IPv6 sysctls enabled because its DNS listener binds
to `[::]:53`; leak protection comes from not assigning IPv6 addresses and from
gluetun's firewall rules. SABnzbd is additionally configured with
`host = 0.0.0.0`, `ipv6_hosting = 0`, and `ipv6_servers = 0` in
`configs/sabnzbd/config/sabnzbd.ini`.

### VPN kill-switch

Download clients (qbittorrent, jdownloader2, sabnzbd, and legacy nzbget when
enabled) share the gluetun network namespace via
`network_mode: container:${VPN_PROVIDER}`. If gluetun stops, those containers
lose network access entirely. No traffic can escape to the clearnet. The
qBittorrent and SABnzbd exporters do not share the namespace; they sit on
internal networks and scrape the download clients through gluetun's services
address.

### Internal networks

The observability stack and the services network are declared `internal: true`, meaning
containers on those networks cannot route to external addresses. This limits what a
compromised exporter or servarr app can reach.

### Read-only volume mounts

Certificates, config files used only at read time, and system paths are mounted `:ro` where
possible. Examples: `/etc/localtime`, `/certs`, prometheus config.

## Exceptions

| Container | Exception | Reason |
| --- | --- | --- |
| gluetun | `cap_add: [NET_ADMIN, NET_RAW]` | VPN tunnel and firewall rule management |
| cadvisor | `privileged: true` | Requires full cgroup, /proc, and /sys access to report container metrics |
| podman_exporter | `userns_mode: keep-id:uid=65534,gid=65534` | Must access the Podman socket as a specific mapped UID; SELinux label enforcement disabled |
| podman_limits_exporter | `userns_mode: keep-id:uid=0,gid=0` | Must access the Podman socket as a specific mapped UID; SELinux label enforcement disabled |
| gluetun, podman_exporter, podman_limits_exporter | `security_opt: label=disable` | SELinux label enforcement disabled for socket access |

## Rootless Podman UID remapping

This stack runs under rootless Podman. The host user (uid=1000) is mapped to uid=0 inside
container user namespaces. Container uid=1000 maps to a sub-uid (typically host uid
~525287).

**Consequence for bind-mounted volumes:** Files created on the host by the host user appear
as uid=0 inside the container. A container process running as uid=1000 cannot write to
files it sees as owned by uid=0.

**Fix for directories that container processes (uid=1000) must write to**: remap ownership
into the container user namespace before first start. `podman unshare` enters the same user
namespace containers use, so `chown $(id -u):$(id -g)` sets ownership to the sub-uid that
container uid=1000 maps to on the host.

```bash
make bootstrap
```

This covers the managed `data`, `configs`, and `storage` paths declared in
`permissions.yml`. It also applies the initial Jellyfin network settings from
`JELLYFIN_BASE_URL` and `JELLYFIN_KNOWN_PROXY`; normal `make start` does not
rewrite Jellyfin config.

The permissions manifest also grants namespace uid `0` `rwx` ACL access to all
managed paths. In rootless Podman, namespace uid `0` maps to the host login
user, so the operator can edit, move, and delete managed files from a normal
terminal without `sudo` while app processes continue to run as their
service-specific non-root UIDs.

`podman unshare` enters the same user namespace the containers use. Inside it,
`chown $(id -u):$(id -g)` sets ownership to the sub-uid that container uid=1000 maps to on
the host.

**For linuxserver s6-overlay images** (sonarr, radarr, etc.): the init script runs
`chown -R ${PUID}:${PGID} /config` recursively at every startup, so config directories are
automatically re-owned. No manual chown is needed.

**For the hotio whisparr image**: the init only chowns the top-level `/config` directory,
not its contents. `make bootstrap` handles the one-time recursive chown of
`configs/whisparr/config` so the app process can read its own ASP.NET data-protection keys
and write its PID file.

## Verification

```bash
# Confirm app processes run as non-root
for c in sonarr radarr bazarr lidarr prowlarr readarr whisparr qbittorrent sabnzbd jellyfin prometheus grafana; do
  echo -n "$c: "; podman exec $c id 2>/dev/null || echo "not running"
done

# Confirm security options and capability drops
podman inspect sonarr --format 'SecurityOpt={{.HostConfig.SecurityOpt}} CapDrop={{.HostConfig.CapDrop}}'

# Run the dedicated security test suite
make test PYTEST_ARGS="-m security"
```
