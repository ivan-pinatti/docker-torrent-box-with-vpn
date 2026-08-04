"""Integration tests for scripts/wire-connections.sh.

These run the wiring script against the live stack, then verify via each
app's own live API that the expected DownloadClients/Applications entries
exist with the right host/port/category. Marked `wiring` and excluded from
the default `make test` run because they create real, persistent state.

Unlike the rotation tests, there is no restore-after-test: a wired connection
is meant to stay, not act as a temporary probe value.

App ports are not published to the host, so all API calls run curl inside the
target container (see conftest.container_http), matching how the wiring
script itself talks to the apps.

Run explicitly with:
    pytest -m wiring tests/test_wire_connections.py
"""

import subprocess

import pytest

from conftest import ENV, REPO_ROOT, container_http, is_enabled, skip_if_not_running

pytestmark = pytest.mark.wiring

TIMEOUT = 30
SCRIPT = REPO_ROOT / "scripts" / "wire-connections.sh"

# app: (scheme, port_var, api_version, sabnzbd_category)
ARR_APPS = {
    "lidarr": ("https", "LIDARR_HTTPS_PORT", "v1", "music"),
    "radarr": ("https", "RADARR_HTTPS_PORT", "v3", "movies"),
    "readarr": ("https", "READARR_HTTPS_PORT", "v1", "ebooks"),
    "sonarr": ("http", "SONARR_HTTP_PORT", "v3", "tv"),
    "whisparr": ("https", "WHISPARR_HTTPS_PORT", "v3", "mature"),
}

PROWLARR_APPLICATIONS = [
    "LazyLibrarian",
    "Lidarr",
    "Mylar",
    "Radarr",
    "Readarr",
    "Sonarr",
    "Whisparr",
]


def _env(key: str) -> str:
    val = ENV.get(key)
    assert val, f"{key} not set in .env"
    return val


def _api_key(app: str) -> str:
    import xml.etree.ElementTree as ET

    path = REPO_ROOT / f"configs/{app}/config/config.xml"
    tree = ET.parse(path)
    elem = tree.find("ApiKey")
    assert elem is not None and elem.text
    return elem.text


def _download_clients(app: str, running_containers: dict) -> list[dict]:
    skip_if_not_running(app, running_containers)
    scheme, port_var, api_ver, _ = ARR_APPS[app]
    port = _env(port_var)
    status, body = container_http(
        app,
        f"{scheme}://127.0.0.1:{port}/{app}/api/{api_ver}/downloadclient",
        headers={"X-Api-Key": _api_key(app)},
        timeout=TIMEOUT,
    )
    assert status == 200, f"[{app}] GET downloadclient failed: {status} {body[:200]}"
    import json

    return json.loads(body)


def _field(client: dict, name: str) -> object:
    for f in client["fields"]:
        if f["name"] == name:
            return f["value"]
    raise KeyError(name)


@pytest.fixture(scope="module", autouse=True)
def run_wire_connections():
    """Run the wiring script once for the whole module (it's idempotent)."""
    result = subprocess.run(  # nosec B603 - fixed path, no user input
        [str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert result.returncode == 0, (
        f"wire-connections.sh failed:\nSTDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
    return result


@pytest.mark.parametrize("app", sorted(ARR_APPS))
def test_qbittorrent_client_wired(app, running_containers):
    if not is_enabled(app):
        pytest.skip(f"service '{app}' profile is disabled")
    clients = _download_clients(app, running_containers)
    matches = [c for c in clients if c["implementation"] == "QBittorrent"]
    assert len(matches) == 1, (
        f"[{app}] expected exactly one QBittorrent client, found {len(matches)}"
    )
    client = matches[0]
    assert client["enable"] is True
    assert _field(client, "host") == _env("GLUETUN_SERVICES_IP")
    assert _field(client, "port") == int(_env("QBITTORRENT_HTTPS_PORT"))
    # qBittorrent's own categories.json uses each app's bare name.
    category_field = next(
        f["name"]
        for f in client["fields"]
        if f["name"].endswith("Category") and "Imported" not in f["name"]
    )
    assert _field(client, category_field) == app


@pytest.mark.parametrize("app", sorted(ARR_APPS))
def test_sabnzbd_client_wired(app, running_containers):
    if not is_enabled(app):
        pytest.skip(f"service '{app}' profile is disabled")
    _, _, _, expected_category = ARR_APPS[app]
    clients = _download_clients(app, running_containers)
    matches = [c for c in clients if c["implementation"] == "Sabnzbd"]
    assert len(matches) == 1, (
        f"[{app}] expected exactly one Sabnzbd client, found {len(matches)}"
    )
    client = matches[0]
    assert client["enable"] is True
    assert _field(client, "host") == _env("GLUETUN_SERVICES_IP")
    assert _field(client, "port") == int(_env("SABNZBD_HTTP_PORT"))
    category_field = next(
        f["name"]
        for f in client["fields"]
        if f["name"].endswith("Category") and "Imported" not in f["name"]
    )
    assert _field(client, category_field) == expected_category


@pytest.mark.parametrize("app", sorted(ARR_APPS))
def test_arr_host_prereqs_wired(app, running_containers):
    """CertificateValidation relaxed and an initial WebUI login exists."""
    if not is_enabled(app):
        pytest.skip(f"service '{app}' profile is disabled")
    skip_if_not_running(app, running_containers)
    scheme, port_var, api_ver, _ = ARR_APPS[app]
    port = _env(port_var)
    status, body = container_http(
        app,
        f"{scheme}://127.0.0.1:{port}/{app}/api/{api_ver}/config/host",
        headers={"X-Api-Key": _api_key(app)},
        timeout=TIMEOUT,
    )
    assert status == 200, f"[{app}] GET config/host failed: {status} {body[:200]}"
    import json

    host_config = json.loads(body)
    assert host_config["username"] == app
    assert host_config["certificateValidation"] == "disabledForLocalAddresses"


def test_prowlarr_applications_wired(running_containers):
    if not is_enabled("prowlarr"):
        pytest.skip("service 'prowlarr' profile is disabled")
    skip_if_not_running("prowlarr", running_containers)
    port = _env("PROWLARR_HTTPS_PORT")
    status, body = container_http(
        "prowlarr",
        f"https://127.0.0.1:{port}/prowlarr/api/v1/applications",
        headers={"X-Api-Key": _api_key("prowlarr")},
        timeout=TIMEOUT,
    )
    assert status == 200, f"GET applications failed: {status} {body[:200]}"
    import json

    applications = json.loads(body)
    names = {a["name"] for a in applications}
    # LazyLibrarian/Mylar aren't Servarr apps and have no profile_var in
    # conftest's SERVICES, so their enabled check goes straight to .env.
    expected = {
        name
        for name in PROWLARR_APPLICATIONS
        if ENV.get(f"{name.upper()}_PROFILE", "disabled").lower() == "enabled"
    }
    missing = expected - names
    assert not missing, f"Prowlarr missing applications: {missing}"


def test_prowlarr_indexer_wired(running_containers):
    """Prowlarr ends up with at least one indexer.

    A real bootstrap left Prowlarr with zero indexers because
    wire_prowlarr_apps died on the first application registration under
    `set -e`, taking the indexer (registered after them) down with it.
    """
    if not is_enabled("prowlarr"):
        pytest.skip("service 'prowlarr' profile is disabled")
    skip_if_not_running("prowlarr", running_containers)
    port = _env("PROWLARR_HTTPS_PORT")
    status, body = container_http(
        "prowlarr",
        f"https://127.0.0.1:{port}/prowlarr/api/v1/indexer",
        headers={"X-Api-Key": _api_key("prowlarr")},
        timeout=TIMEOUT,
    )
    assert status == 200, f"GET indexer failed: {status} {body[:200]}"
    import json

    indexers = json.loads(body)
    assert indexers, "Prowlarr has no indexers at all"


@pytest.mark.parametrize("app", sorted(ARR_APPS))
def test_prowlarr_indexers_propagated_to_arr_app(app, running_containers):
    """Prowlarr's indexer actually reached each arr app.

    Registering the Applications in Prowlarr is only half the chain; the
    indexer still has to be pushed into each app. That push silently failed
    in a real bootstrap: Prowlarr had put the indexer into a failure backoff
    (Internet Archive's advancedsearch API intermittently times out), so it
    answered each arr app's capability probe with 429, the app rejected the
    indexer with 400, and nothing retried. The user-visible symptom was "no
    indexers in the arr apps" while Prowlarr itself looked fine, which is
    exactly what this asserts against.
    """
    if not is_enabled(app) or not is_enabled("prowlarr"):
        pytest.skip("service profile is disabled")
    skip_if_not_running(app, running_containers)
    scheme, port_var, api_ver, _ = ARR_APPS[app]
    port = _env(port_var)
    status, body = container_http(
        app,
        f"{scheme}://127.0.0.1:{port}/{app}/api/{api_ver}/indexer",
        headers={"X-Api-Key": _api_key(app)},
        timeout=TIMEOUT,
    )
    assert status == 200, f"[{app}] GET indexer failed: {status} {body[:200]}"
    import json

    indexers = json.loads(body)
    assert indexers, (
        f"[{app}] has no indexers: Prowlarr's Application sync never landed. "
        "Check Prowlarr's log for 429/backoff and the app's log for "
        "'Invalid Request' on POST .../indexer"
    )


def test_wiring_is_idempotent(running_containers):
    """Re-running the script must not create duplicate entries."""
    result = subprocess.run(  # nosec B603 - fixed path, no user input
        [str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert result.returncode == 0, (
        f"second wire-connections.sh run failed:\nSTDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
    for app in ARR_APPS:
        if not is_enabled(app):
            continue
        clients = _download_clients(app, running_containers)
        for implementation in ("QBittorrent", "Sabnzbd"):
            matches = [c for c in clients if c["implementation"] == implementation]
            assert len(matches) == 1, (
                f"[{app}] expected exactly one {implementation} client after "
                f"re-running, found {len(matches)}"
            )
