"""Observability stack integration tests.

Checks that the full metrics pipeline is healthy end-to-end:
Prometheus targets → scrape success
podman_exporter   → per-container metrics present
qbittorrent/SABnzbd → exporters reachable and returning metrics
Grafana           → datasource healthy, dashboards provisioned
"""

import json
import re

import pytest
import requests
import urllib3

from conftest import REPO_ROOT, base_url, env, is_enabled, skip_if_not_running

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

pytestmark = pytest.mark.observability

TIMEOUT = 10
PROMETHEUS_PATH = "/admin/prometheus/api/v1"
GRAFANA_PATH = "/admin/grafana/api"
GRAFANA_USER = env("ADMIN_USER", "admin")
GRAFANA_PASSWORD = env("ADMIN_PASSWORD", "admin")

EXPECTED_PROMETHEUS_JOBS = {
    "node_exporter",
    "podman",
    "prometheus",
    "qbittorrent",
    "sabnzbd",
}

REPO_POD_NAME = "pod_docker-torrent-box-with-vpn"

EXPECTED_PODMAN_DASHBOARD_STACKS = {
    "Downloaders": {"jdownloader2", "qbittorrent", "sabnzbd"},
    "Indexers": {"nzbhydra2", "prowlarr"},
    "Media & Library": {"jellyfin", "audiobookshelf", "calibre", "calibre-web"},
    "Observability": {
        "cadvisor",
        "podman_exporter",
        "podman_limits_exporter",
        "node_exporter",
        "nginx_exporter",
        "qbittorrent_exporter",
        "sabnzbd_exporter",
        "alloy",
        "prometheus",
        "loki",
        "grafana",
    },
    "VPN": {"gluetun"},
    "Proxy": {"nginx"},
    "Homepage": {"homepage"},
    "Servarr": {
        "bazarr",
        "flaresolverr",
        "lidarr",
        "radarr",
        "readarr",
        "recyclarr",
        "sonarr",
        "whisparr",
        "mylar",
    },
}


# ---------------------------------------------------------------------------
# Prometheus
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def prometheus_url():
    return base_url(https=True) + PROMETHEUS_PATH


def _prom_get(prometheus_url, path, params=None):
    resp = requests.get(
        prometheus_url + path,
        params=params,
        verify=False,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _podman_dashboard():
    return json.loads(
        (
            REPO_ROOT
            / "configs/grafana/config/provisioning/dashboards/node_containers/podman_containers.json"
        ).read_text()
    )


def _dashboard_variable(dashboard, name):
    return next(
        item for item in dashboard["templating"]["list"] if item["name"] == name
    )


def _parse_custom_variable_query(query):
    stacks = {}
    for item in query.split(", "):
        label, regex = item.split(" : ", 1)
        stacks[label] = set(regex.split("|"))
    return stacks


def test_prometheus_self_healthy(running_containers):
    """Prometheus /api/v1/query?query=up returns status=success."""
    if not is_enabled("prometheus"):
        pytest.skip("prometheus profile is disabled")
    skip_if_not_running("prometheus", running_containers)

    data = _prom_get(base_url() + PROMETHEUS_PATH, "/query", {"query": "up"})
    assert data["status"] == "success"


def test_prometheus_all_targets_up(running_containers, prometheus_url):
    """All expected scrape jobs are present and in 'up' state."""
    if not is_enabled("prometheus"):
        pytest.skip("prometheus profile is disabled")
    skip_if_not_running("prometheus", running_containers)

    data = _prom_get(prometheus_url, "/targets")
    targets = data["data"]["activeTargets"]
    by_job = {t["scrapePool"]: t for t in targets}

    for job in EXPECTED_PROMETHEUS_JOBS:
        assert job in by_job, (
            f"Prometheus scrape job '{job}' not found (known: {list(by_job)})"
        )
        health = by_job[job]["health"]
        assert health == "up", (
            f"Prometheus job '{job}' is '{health}': {by_job[job].get('lastError', '')}"
        )


def test_prometheus_no_unknown_targets(running_containers, prometheus_url):
    """No scrape target is stuck in 'unknown' state after startup."""
    if not is_enabled("prometheus"):
        pytest.skip("prometheus profile is disabled")
    skip_if_not_running("prometheus", running_containers)

    data = _prom_get(prometheus_url, "/targets")
    unknown = [
        t["scrapePool"]
        for t in data["data"]["activeTargets"]
        if t["health"] == "unknown"
    ]
    assert not unknown, f"Prometheus targets still in 'unknown' state: {unknown}"


# ---------------------------------------------------------------------------
# podman_exporter — per-container metrics
# ---------------------------------------------------------------------------


def test_podman_exporter_container_metrics_present(running_containers, prometheus_url):
    """podman_container_info must report at least the core service containers."""
    if not is_enabled("podman_exporter"):
        pytest.skip("PODMAN_EXPORTER_PROFILE is disabled")
    skip_if_not_running("podman_exporter", running_containers)
    if not is_enabled("prometheus"):
        pytest.skip("prometheus profile is disabled")

    data = _prom_get(prometheus_url, "/query", {"query": "podman_container_info"})
    assert data["status"] == "success"
    results = data["data"]["result"]
    assert results, (
        "podman_container_info returned no series — exporter may not see containers"
    )

    names = {r["metric"].get("name", "") for r in results}
    expected = {"sonarr", "radarr", "gluetun", "prometheus", "grafana", "sabnzbd"}
    missing = expected - names
    assert not missing, f"Expected containers missing from podman metrics: {missing}"


def test_podman_exporter_cpu_metrics(running_containers, prometheus_url):
    """podman_container_cpu_seconds_total has data for running containers."""
    if not is_enabled("podman_exporter"):
        pytest.skip("PODMAN_EXPORTER_PROFILE is disabled")
    skip_if_not_running("podman_exporter", running_containers)
    if not is_enabled("prometheus"):
        pytest.skip("prometheus profile is disabled")

    data = _prom_get(
        prometheus_url, "/query", {"query": "podman_container_cpu_seconds_total"}
    )
    assert data["status"] == "success"
    assert data["data"]["result"], "No CPU metrics from podman_exporter"


def test_podman_exporter_memory_metrics(running_containers, prometheus_url):
    """podman_container_mem_usage_bytes has data for running containers."""
    if not is_enabled("podman_exporter"):
        pytest.skip("PODMAN_EXPORTER_PROFILE is disabled")
    skip_if_not_running("podman_exporter", running_containers)
    if not is_enabled("prometheus"):
        pytest.skip("prometheus profile is disabled")

    data = _prom_get(
        prometheus_url, "/query", {"query": "podman_container_mem_usage_bytes"}
    )
    assert data["status"] == "success"
    assert data["data"]["result"], "No memory metrics from podman_exporter"


# ---------------------------------------------------------------------------
# qbittorrent exporter
# ---------------------------------------------------------------------------


def test_qbittorrent_exporter_metrics_present(running_containers, prometheus_url):
    """qbittorrent_exporter metrics are scraped into Prometheus."""
    if not is_enabled("qbittorrent_exporter"):
        pytest.skip("QBITTORRENT_EXPORTER_PROFILE is disabled")
    skip_if_not_running("qbittorrent_exporter", running_containers)
    if not is_enabled("prometheus"):
        pytest.skip("prometheus profile is disabled")

    data = _prom_get(
        prometheus_url, "/query", {"query": 'max(qbittorrent_up{job="qbittorrent"})'}
    )
    assert data["status"] == "success"
    assert data["data"]["result"], "qbittorrent_up returned no series"
    assert data["data"]["result"][0]["value"][1] == "1", (
        f"qbittorrent_up is not 1: {data['data']['result']}"
    )

    err_data = _prom_get(prometheus_url, "/targets")
    qbt_target = next(
        (
            t
            for t in err_data["data"]["activeTargets"]
            if t["scrapePool"] == "qbittorrent"
        ),
        None,
    )
    assert qbt_target is not None, "qbittorrent scrape job not found"
    assert qbt_target["health"] == "up", (
        f"qbittorrent scrape job is '{qbt_target['health']}': {qbt_target.get('lastError', '')}"
    )


# ---------------------------------------------------------------------------
# SABnzbd exporter
# ---------------------------------------------------------------------------


def test_sabnzbd_exporter_metrics_present(running_containers, prometheus_url):
    """SABnzbd exporter metrics are scraped into Prometheus."""
    if not is_enabled("sabnzbd_exporter"):
        pytest.skip("SABNZBD_EXPORTER_PROFILE is disabled")
    skip_if_not_running("sabnzbd_exporter", running_containers)
    if not is_enabled("prometheus"):
        pytest.skip("prometheus profile is disabled")

    data = _prom_get(prometheus_url, "/query", {"query": 'up{job="sabnzbd"}'})
    assert data["status"] == "success"
    assert data["data"]["result"], "SABnzbd exporter returned no up series"
    assert data["data"]["result"][0]["value"][1] == "1", (
        f"SABnzbd exporter is not up: {data['data']['result']}"
    )


# ---------------------------------------------------------------------------
# Grafana
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def grafana_url():
    return base_url(https=True) + GRAFANA_PATH


@pytest.fixture(scope="module")
def grafana_session():
    """Return a requests.Session authenticated against Grafana via Basic Auth."""
    session = requests.Session()
    session.verify = False
    session.auth = (GRAFANA_USER, GRAFANA_PASSWORD)
    resp = session.get(
        base_url(https=True) + GRAFANA_PATH + "/health",
        timeout=TIMEOUT,
    )
    if resp.status_code == 401:
        pytest.skip(
            f"Could not authenticate to Grafana (HTTP {resp.status_code}): {resp.text[:200]}"
        )
    return session


def test_grafana_health(running_containers):
    """Grafana /api/health returns database=ok (no auth required)."""
    if not is_enabled("grafana"):
        pytest.skip("grafana profile is disabled")
    skip_if_not_running("grafana", running_containers)

    resp = requests.get(
        base_url() + GRAFANA_PATH + "/health",
        verify=False,
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("database") == "ok", f"Grafana database not ok: {data}"


def test_grafana_prometheus_datasource_healthy(
    running_containers, grafana_url, grafana_session
):
    """Grafana Prometheus datasource uid='prometheus' is configured."""
    if not is_enabled("grafana"):
        pytest.skip("grafana profile is disabled")
    skip_if_not_running("grafana", running_containers)

    resp = grafana_session.get(
        grafana_url + "/datasources/uid/prometheus",
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, (
        f"Grafana datasource 'prometheus' not found: {resp.status_code} {resp.text[:200]}"
    )
    data = resp.json()
    assert data.get("type") == "prometheus"


def test_grafana_dashboards_provisioned(
    running_containers, grafana_url, grafana_session
):
    """All expected dashboards are present in Grafana."""
    if not is_enabled("grafana"):
        pytest.skip("grafana profile is disabled")
    skip_if_not_running("grafana", running_containers)

    resp = grafana_session.get(
        grafana_url + "/search?type=dash-db",
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200
    titles = {d["title"] for d in resp.json()}

    expected = {
        "Node Exporter - Overview",
        "Docker Containers",
        "qBittorrent - Overview",
        "SABnzbd Dashboard",
        "Podman Containers",
    }
    missing = expected - titles
    assert not missing, f"Grafana dashboards missing: {missing} (found: {titles})"


def test_podman_dashboard_stack_filters_match_app_groups():
    dashboard = _podman_dashboard()
    stack = _dashboard_variable(dashboard, "stack")

    assert (
        _parse_custom_variable_query(stack["query"]) == EXPECTED_PODMAN_DASHBOARD_STACKS
    )
    assert "lazylibrarian" not in stack["query"]


def test_podman_dashboard_default_stack_filter_is_repo_only():
    dashboard = _podman_dashboard()
    stack = _dashboard_variable(dashboard, "stack")
    all_value = stack["allValue"]
    expected_containers = set().union(*EXPECTED_PODMAN_DASHBOARD_STACKS.values())

    assert set(all_value.split("|")) == expected_containers
    assert re.fullmatch(all_value, "pihole-mcp-360657") is None
    assert re.fullmatch(all_value, "podman_cpu_exporter") is None


def test_podman_dashboard_container_variable_is_repo_scoped():
    dashboard = _podman_dashboard()
    container = _dashboard_variable(dashboard, "container")

    assert f'pod_name="{REPO_POD_NAME}"' in container["query"]
    assert 'name=~"${stack:raw}"' in container["query"]


def test_podman_dashboard_podman_exporter_queries_are_repo_scoped():
    dashboard = _podman_dashboard()
    unscoped = []

    for panel in dashboard["panels"]:
        for target in panel.get("targets") or []:
            expr = target.get("expr", "")
            if "podman_container_" not in expr:
                continue
            if "podman_container_cpu_limit_vcpus" in expr:
                continue
            if "podman_container_pids_limit" in expr:
                continue
            if f'pod_name="{REPO_POD_NAME}"' not in expr:
                unscoped.append((panel["title"], expr))

    assert not unscoped


def test_torrent_box_overview_uses_sabnzbd_not_nzbget():
    dashboard = (
        REPO_ROOT
        / "configs/grafana/config/provisioning/dashboards/torrent_box/backends.json"
    ).read_text()
    assert "nzbget" not in dashboard.lower()
    assert "sabnzbd" in dashboard.lower()


def test_qbittorrent_dashboard_uses_bit_rates():
    dashboard = json.loads(
        (
            REPO_ROOT
            / "configs/grafana/config/provisioning/dashboards/downloaders/qbittorrent.json"
        ).read_text()
    )
    panels = {panel["title"]: panel for panel in dashboard["panels"]}

    for title in (
        "Session Transfer Rate",
        "Active Download Limit",
        "Active Upload Limit",
        "VPN Network I/O",
    ):
        panel = panels[title]
        assert panel["fieldConfig"]["defaults"]["unit"] == "bps"
        for target in panel["targets"]:
            assert target["expr"].endswith(" * 8")

    assert panels["Disk I/O"]["fieldConfig"]["defaults"]["unit"] == "Bps"


def test_qbittorrent_dashboard_uses_decimal_byte_sizes():
    dashboard = json.loads(
        (
            REPO_ROOT
            / "configs/grafana/config/provisioning/dashboards/downloaders/qbittorrent.json"
        ).read_text()
    )
    panels = {panel["title"]: panel for panel in dashboard["panels"]}

    for title in (
        "All Time Downloaded",
        "All Time Uploaded",
        "Session Downloaded",
        "Session Uploaded",
        "Free Space",
        "qBittorrent Memory Usage",
        "Download Disk Free",
        "Swap Usage",
    ):
        assert panels[title]["fieldConfig"]["defaults"]["unit"] == "decbytes"
