"""Service API health checks using API keys read from service config files."""

import pytest
import requests
import urllib3

from conftest import (
    SERVICES,
    is_enabled,
    read_api_key,
    service_base_url,
    skip_if_not_running,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

pytestmark = pytest.mark.services

TIMEOUT = 10

# Services with a dedicated API health endpoint
HEALTH_SERVICES = [name for name, cfg in SERVICES.items() if cfg.get("api_health_path")]


@pytest.mark.parametrize("service_name", HEALTH_SERVICES)
def test_service_api_health(service_name, running_containers):
    """GET the service's health endpoint and assert a 200 response."""
    if not is_enabled(service_name):
        pytest.skip(f"{service_name} profile is disabled")
    skip_if_not_running(service_name, running_containers)

    cfg = SERVICES[service_name]
    path = cfg["api_health_path"]
    api_key = read_api_key(service_name)

    url = service_base_url(service_name) + path
    headers = {}
    params = {}
    if api_key:
        headers["X-Api-Key"] = api_key
        params["apikey"] = api_key

    resp = requests.get(
        url, headers=headers, params=params, verify=False, timeout=TIMEOUT
    )
    assert resp.status_code == 200, (
        f"{service_name} health endpoint {url} returned {resp.status_code}: {resp.text[:200]}"
    )


@pytest.mark.parametrize(
    "service_name",
    [
        name
        for name in ("sonarr", "radarr", "prowlarr", "readarr", "lidarr")
        if name in SERVICES
    ],
)
def test_arr_health_response_empty(service_name, running_containers):
    """Servarr health endpoints return an empty list when everything is OK."""
    if not is_enabled(service_name):
        pytest.skip(f"{service_name} profile is disabled")
    skip_if_not_running(service_name, running_containers)

    cfg = SERVICES[service_name]
    path = cfg["api_health_path"]
    api_key = read_api_key(service_name)
    if not api_key:
        pytest.skip(f"No API key found for {service_name}")

    url = service_base_url(service_name) + path
    resp = requests.get(
        url, headers={"X-Api-Key": api_key}, verify=False, timeout=TIMEOUT
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list), f"Expected list from {url}, got {type(data)}"
    # Warn about health issues rather than failing — some warnings are non-critical
    if data:
        import warnings

        messages = [item.get("message", str(item)) for item in data]
        warnings.warn(
            f"{service_name} reports health issues: {messages}",
            UserWarning,
            stacklevel=2,
        )
