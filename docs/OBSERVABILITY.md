# Observability

The stack collects container and host metrics with Prometheus, ships logs via Grafana Alloy to
Loki, and surfaces everything in Grafana dashboards with built-in alerting.

## Topics

- [Monitoring](observability/MONITORING.md) — services, enabling, network architecture,
  Prometheus, Loki, and Alloy
- [Dashboards](observability/DASHBOARDS.md) — provisioned dashboard conventions and panel patterns
- [Alerting](observability/ALERTING.md) — alert rules, email (AWS SES), Telegram, and
  notification policy

## Quick links

| Service    | URL                                |
| ---------- | ---------------------------------- |
| Grafana    | `https://<host>/admin/grafana/`    |
| Prometheus | `https://<host>/admin/prometheus/` |

Disk growth controls for metrics retention, log rotation, and download-size alerts are
documented in [GROWTH_CONTROLS.md](GROWTH_CONTROLS.md).
