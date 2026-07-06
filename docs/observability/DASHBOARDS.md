# Grafana Dashboards

Dashboard JSON is provisioned from `configs/grafana/config/provisioning/dashboards/`. Prefer
editing these files over making one-off UI changes; provisioned dashboards can be overwritten
when Grafana reloads.

After changing a dashboard JSON file:

```shell
jq empty configs/grafana/config/provisioning/dashboards/torrent_box/nginx.json
podman restart grafana
```

Then confirm Grafana is healthy:

```shell
podman ps --filter name=grafana --format '{{.Names}}\t{{.Status}}'
```

## Loki top-k bar gauges

For Loki metric queries shown as Grafana bar gauges, use all three pieces together:

- `sort_desc(topk(...))` in LogQL to select and order the returned vector by value.
- `queryType: "instant"` so Loki returns one point per series for the selected dashboard time range.
- Bar gauge `reduceOptions.values: true` with `limit: 10` so Grafana displays all returned values
  instead of reducing to a single value.

Example target:

```json
{
  "datasource": { "type": "loki", "uid": "loki" },
  "expr": "sort_desc(topk(10, sum by (service) (count_over_time({job=\"nginx-access\", service=~\"$service\"} !~ \"stub_status\" [$__range]))))",
  "legendFormat": "{{service}}",
  "queryType": "instant",
  "refId": "A"
}
```

Matching bar gauge value options:

```json
"reduceOptions": {
  "calcs": ["lastNotNull"],
  "fields": "",
  "limit": 10,
  "values": true
}
```

`topk(10, ...)` selects the largest series. Use `sort_desc(...)` when display order matters.
Grafana bar gauges default to calculating a single value per field. With Loki instant query
results, leaving `values` as `false` can reduce the panel to one number. Set `values: true` when
the panel should show one bar per returned label value.

Keep `options.sort: "desc"` on the bar gauge as a visualization-level safeguard, but do not rely
on it alone to fix Loki frame ordering.

## Nginx overview examples

The Nginx overview dashboard uses this pattern for:

- Panel 71, `Top 10 Clients (requests)`: `sort_desc(topk(10, sum by (remote_addr) (...)))`
- Panel 72, `Top 10 Backends (requests)`: `sort_desc(topk(10, sum by (service) (...)))`

Both panels use Loki instant queries and `reduceOptions.values: true`.

## References

- Grafana bar gauge value options: <https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/bar-gauge/>
- Grafana Loki query editor options: <https://grafana.com/docs/grafana/latest/datasources/loki/query-editor/>
- Loki metric query aggregation operators: <https://grafana.com/docs/loki/latest/query/metric_queries/>
