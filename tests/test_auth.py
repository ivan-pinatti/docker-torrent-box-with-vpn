"""Authentication tests: API login and web session login per service."""

import pytest
import requests
import urllib3

from conftest import (
    SERVICES,
    base_url,
    env,
    is_enabled,
    read_api_key,
    read_secret,
    service_base_url,
    service_env,
    skip_if_not_running,
    wait_for_healthy,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

pytestmark = pytest.mark.auth

TIMEOUT = 10
BASE = base_url(https=True)


def _qbittorrent_password():
    """qBittorrent's rotated password lives in its own .env.secrets, not root .env."""
    return service_env("qbittorrent").get("PASSWORD") or env(
        "QBITTORRENT_PASSWORD", "qbittorrent"
    )


# ---------------------------------------------------------------------------
# qBittorrent
# ---------------------------------------------------------------------------


def test_qbittorrent_api_login(running_containers):
    """POST /api/v2/auth/login with credentials from .env."""
    if not is_enabled("qbittorrent"):
        pytest.skip("qbittorrent profile is disabled")
    skip_if_not_running("qbittorrent", running_containers)
    wait_for_healthy("qbittorrent")

    password = _qbittorrent_password()
    username = SERVICES["qbittorrent"]["username"]
    url = f"{BASE}/qbittorrent/api/v2/auth/login"
    resp = requests.post(
        url,
        data={"username": username, "password": password},
        verify=False,
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200
    assert resp.text.strip() == "Ok.", f"qBittorrent login failed: {resp.text!r}"


def test_qbittorrent_web_session_login(running_containers):
    """Full browser-style session login to qBittorrent web UI."""
    if not is_enabled("qbittorrent"):
        pytest.skip("qbittorrent profile is disabled")
    skip_if_not_running("qbittorrent", running_containers)
    wait_for_healthy("qbittorrent")

    password = _qbittorrent_password()
    username = SERVICES["qbittorrent"]["username"]
    session = requests.Session()
    session.verify = False

    login_url = f"{BASE}/qbittorrent/api/v2/auth/login"
    resp = session.post(
        login_url, data={"username": username, "password": password}, timeout=TIMEOUT
    )
    assert resp.status_code == 200 and resp.text.strip() == "Ok."

    # Verify the session cookie grants access to a protected endpoint
    version_resp = session.get(
        f"{BASE}/qbittorrent/api/v2/app/version", timeout=TIMEOUT
    )
    assert version_resp.status_code == 200, (
        f"Session cookie not accepted: {version_resp.status_code}"
    )


# ---------------------------------------------------------------------------
# NzbGet (HTTP Basic Auth JSON-RPC)
# ---------------------------------------------------------------------------


def test_nzbget_api_auth(running_containers):
    """Authenticated JSON-RPC call to NzbGet using Basic Auth."""
    if not is_enabled("nzbget"):
        pytest.skip("nzbget profile is disabled")
    skip_if_not_running("nzbget", running_containers)

    username = SERVICES["nzbget"]["username"]
    password = env("NZBGET_PASSWORD", "nzbget")
    url = f"{BASE}/nzbget/jsonrpc"
    payload = {"method": "version", "params": [], "id": 1}
    resp = requests.post(
        url, json=payload, auth=(username, password), verify=False, timeout=TIMEOUT
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "result" in data, f"NzbGet JSON-RPC returned no result: {data}"


# ---------------------------------------------------------------------------
# SABnzbd
# ---------------------------------------------------------------------------


def test_sabnzbd_api_auth(running_containers):
    """Authenticated SABnzbd API call using the configured API key."""
    if not is_enabled("sabnzbd"):
        pytest.skip("sabnzbd profile is disabled")
    skip_if_not_running("sabnzbd", running_containers)

    api_key = read_api_key("sabnzbd") or read_secret("sabnzbd", "api_key.txt")
    if not api_key:
        pytest.skip("No SABnzbd API key found")

    # mode=queue, not mode=version: version is unauthenticated and answers
    # even for a bogus key, so asserting on it proved nothing about auth.
    resp = requests.get(
        f"{BASE}/sabnzbd/api",
        params={"mode": "queue", "output": "json", "apikey": api_key},
        verify=False,
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200
    assert "API Key Incorrect" not in resp.text, "SABnzbd rejected the API key"
    data = resp.json()
    assert "queue" in data, f"SABnzbd API returned no queue: {data}"


# ---------------------------------------------------------------------------
# Servarr apps (Sonarr, Radarr, Prowlarr, Readarr) — API key as auth
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "service_name", ["sonarr", "radarr", "prowlarr", "readarr", "lidarr"]
)
def test_arr_api_key_auth(service_name, running_containers):
    """API key must grant access to the service status endpoint."""
    if not is_enabled(service_name):
        pytest.skip(f"{service_name} profile is disabled")
    skip_if_not_running(service_name, running_containers)

    api_key = read_api_key(service_name)
    if not api_key:
        pytest.skip(f"No API key found for {service_name}")

    cfg = SERVICES[service_name]
    url = BASE + cfg["api_health_path"]
    resp = requests.get(
        url, headers={"X-Api-Key": api_key}, verify=False, timeout=TIMEOUT
    )
    assert resp.status_code == 200, (
        f"{service_name} API key rejected: {resp.status_code}"
    )


@pytest.mark.parametrize(
    "service_name", ["sonarr", "radarr", "prowlarr", "readarr", "lidarr"]
)
def test_arr_rejects_invalid_api_key(service_name, running_containers):
    """Invalid API key must be rejected with 401."""
    if not is_enabled(service_name):
        pytest.skip(f"{service_name} profile is disabled")
    skip_if_not_running(service_name, running_containers)

    cfg = SERVICES[service_name]
    url = BASE + cfg["api_health_path"]
    resp = requests.get(
        url,
        headers={"X-Api-Key": "invalid_key_00000000000000000"},
        verify=False,
        timeout=TIMEOUT,
    )
    assert resp.status_code == 401, (
        f"{service_name} accepted an invalid API key: {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# Bazarr — API key from YAML config
# ---------------------------------------------------------------------------


def test_bazarr_api_key_auth(running_containers):
    if not is_enabled("bazarr"):
        pytest.skip("bazarr profile is disabled")
    skip_if_not_running("bazarr", running_containers)

    api_key = read_api_key("bazarr")
    if not api_key:
        pytest.skip("No Bazarr API key found")

    url = f"{BASE}/bazarr/api/system/health"
    resp = requests.get(
        url, headers={"X-API-KEY": api_key}, verify=False, timeout=TIMEOUT
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Jellyfin — unauthenticated health check, authenticated user info
# ---------------------------------------------------------------------------


def test_jellyfin_health_endpoint(running_containers):
    if not is_enabled("jellyfin"):
        pytest.skip("jellyfin profile is disabled")
    skip_if_not_running("jellyfin", running_containers)

    jellyfin_base = service_base_url("jellyfin")
    resp = requests.get(f"{jellyfin_base}/health", verify=False, timeout=TIMEOUT)
    assert resp.status_code == 200
