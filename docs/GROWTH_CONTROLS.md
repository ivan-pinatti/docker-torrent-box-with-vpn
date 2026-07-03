# Growth Controls

This stack avoids runaway disk growth with retention settings, bounded caches,
manual maintenance commands, and Grafana alerts. It does not use host filesystem
quotas and it does not automatically delete torrent or usenet downloads.

## What Is Automatic

- Prometheus keeps metrics for `PROMETHEUS_RETENTION_TIME` and also honors
  `PROMETHEUS_RETENTION_SIZE`.
- Loki keeps logs for `LOKI_RETENTION_PERIOD`.
- Nginx host logs rotate daily according to `LOG_ROTATION_CRON`.
- Nginx proxy cache is capped by `NGINX_PROXY_CACHE_MAX_SIZE`.
- Nginx evicts cached objects that have not been used for
  `NGINX_PROXY_CACHE_INACTIVE`.
- Grafana provisions disk-pressure alerts when observability is enabled.
- SABnzbd pauses downloads when free disk space drops below its configured
  free-space threshold.

## What Is Manual

- Torrent and usenet payload cleanup is manual.
- Immediate nginx host log rotation can be triggered manually with
  `make rotate_nginx_logs`.
- Nginx cache pruning is manual with `make prune_cache`.
- Disk usage review is manual with `make disk_status`.

## Downloads

Torrent and usenet payloads are the biggest expected disk users. The stack
warns about growth, but does not remove downloaded content.

Run:

```sh
make disk_status
```

This reports current usage for:

- `data/torrents`
- `data/usenet`
- `logs`
- `cache`
- `storage`

Usenet downloads are staged in `data/usenet/incomplete` and completed into
`data/usenet/complete/<category>`. Torrent downloads use
`data/torrents/<category>`.

It also lists the largest torrent, usenet, and log folders. The download warning
thresholds are configured in `.env`:

```env
DOWNLOADS_WARN_GB=500
DOWNLOADS_CRIT_GB=750
```

When the qBittorrent/SABnzbd exporters and Grafana are enabled, Grafana also
alerts on low free disk space and stalled Usenet queues.

## Logs

Nginx writes host-mounted logs under `logs/nginx`. Rotation is automatic when
`LOG_ROTATOR_PROFILE=enabled`. The `log_rotator` container runs cron inside the
container, so no host cron or host systemd timer is required.

The default rotation schedule is 03:30 local time:

```env
LOG_ROTATION_CRON=30 3 * * *
```

Retention has two tiers:

```env
LOG_RETENTION_DAYS=30
LOG_ARCHIVE_RETENTION_DAYS=90
```

Rotated logs stay plain text for 30 days. Rotated logs older than 30 days are
compressed with gzip. Compressed archives older than 90 days are deleted.

Grafana does not search the `.gz` files directly. Grafana searches logs that
Alloy has already sent to Loki. Keep `LOKI_RETENTION_PERIOD=90d` if you want
Grafana to search nginx logs for the same 90-day archive window.

To rotate immediately for testing or maintenance, run:

```sh
make rotate_nginx_logs
```

SABnzbd logs are written under `configs/sabnzbd/config/logs` and tailed by
Alloy into Loki when observability is enabled. qBittorrent app logs are capped
by its own file logger settings in
`configs/qbittorrent/config/qBittorrent/qBittorrent.conf`.

SABnzbd stores NZB backup history under `configs/sabnzbd/config/history` to help
with duplicate detection and retry workflows. These are compressed NZB files,
not downloaded media payloads, but they can still grow over time on busy
systems.

## Observability

Prometheus retention is bounded by both time and size:

```env
PROMETHEUS_RETENTION_TIME=30d
PROMETHEUS_RETENTION_SIZE=10GB
```

Loki retention is enabled with:

```env
LOKI_RETENTION_PERIOD=90d
```

Changing these values requires recreating or restarting the affected containers.

## Cache

Nginx proxy cache is bounded by nginx itself:

```env
NGINX_PROXY_CACHE_MAX_SIZE=1g
NGINX_PROXY_CACHE_INACTIVE=7d
```

`max_size` is the approximate cache size cap. `inactive` means nginx may remove
cached objects that have not been used for that long. The default is seven days
so weekly usage patterns still benefit from cache hits.

To clear nginx cache manually, run:

```sh
make prune_cache
```

The command asks for confirmation. If nginx is running, it stops nginx, clears
`cache/nginx`, and starts nginx again. It does not delete torrent, usenet,
media, config, or observability data.
