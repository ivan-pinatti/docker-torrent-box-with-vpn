"""Integration tests for scripts/rotate-api-keys.sh.

These tests execute the rotation script against the live stack, verify the new
key propagated to every consumer, then restore the original key so the suite
remains idempotent. They are marked `rotation` and are excluded from the
default `make test` run because they modify running service state.

Run explicitly with:
    pytest -m rotation tests/test_rotate_api_keys.py
"""

import subprocess
import xml.etree.ElementTree as ET

import pytest
import requests
import urllib3
import yaml

from conftest import (
    ENV,
    REPO_ROOT,
    base_url,
    is_enabled,
    skip_if_not_running,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

pytestmark = pytest.mark.rotation

TIMEOUT = 30
BASE = base_url(https=True)
SCRIPTS = REPO_ROOT / "scripts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_script(script: str, target: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(SCRIPTS / script), target],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _read_xml_key(rel_path: str) -> str:
    path = REPO_ROOT / rel_path
    tree = ET.parse(path)
    elem = tree.find("ApiKey")
    assert elem is not None and elem.text, f"ApiKey not found in {rel_path}"
    return elem.text


def _restore_arr_key(
    app: str, port_var: str, url_base: str, api_ver: str, old_key: str, current_key: str
):
    """Restore an arr app's API key to old_key using current_key for auth."""
    port = int(ENV.get(port_var, "0"))
    url = f"https://localhost:{port}/{url_base}/api/{api_ver}/config/host"
    resp = requests.get(
        url, headers={"X-Api-Key": current_key}, verify=False, timeout=TIMEOUT
    )
    assert resp.status_code == 200, (
        f"Could not GET host config for {app}: {resp.status_code}"
    )
    cfg = resp.json()
    cfg["apiKey"] = old_key
    resp = requests.put(
        url, json=cfg, headers={"X-Api-Key": current_key}, verify=False, timeout=TIMEOUT
    )
    assert resp.status_code in (200, 202), (
        f"Could not restore {app} key: {resp.status_code}"
    )


def _prowlarr_key_for_app(prowlarr_api_key: str, app_id: int) -> str | None:
    """Return the apiKey field value stored for an app in Prowlarr's Applications table."""
    port = int(ENV.get("PROWLARR_HTTPS_PORT", "9697"))
    url = f"https://localhost:{port}/prowlarr/api/v1/applications/{app_id}"
    resp = requests.get(
        url, headers={"X-Api-Key": prowlarr_api_key}, verify=False, timeout=TIMEOUT
    )
    if resp.status_code != 200:
        return None
    fields = resp.json().get("fields", [])
    for f in fields:
        if f.get("name") == "apiKey":
            return f.get("value")
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "app,xml_path,https_port_var,url_base,api_ver,prowlarr_app_id",
    [
        (
            "sonarr",
            "configs/sonarr/config/config.xml",
            "SONARR_HTTPS_PORT",
            "sonarr",
            "v3",
            3,
        ),
        (
            "radarr",
            "configs/radarr/config/config.xml",
            "RADARR_HTTPS_PORT",
            "radarr",
            "v3",
            5,
        ),
        (
            "lidarr",
            "configs/lidarr/config/config.xml",
            "LIDARR_HTTPS_PORT",
            "lidarr",
            "v1",
            1,
        ),
        (
            "readarr",
            "configs/readarr/config/config.xml",
            "READARR_HTTPS_PORT",
            "readarr",
            "v1",
            2,
        ),
        (
            "whisparr",
            "configs/whisparr/config/config.xml",
            "WHISPARR_HTTPS_PORT",
            "whisparr",
            "v3",
            7,
        ),
    ],
)
def test_rotate_api_key_propagates(
    app,
    xml_path,
    https_port_var,
    url_base,
    api_ver,
    prowlarr_app_id,
    running_containers,
):
    """Rotating an arr app's API key updates all consumers and the new key works."""
    if not is_enabled(app):
        pytest.skip(f"{app} profile is disabled")
    skip_if_not_running(app, running_containers)

    old_key = _read_xml_key(xml_path)

    result = _run_script("rotate-api-keys.sh", app)
    assert result.returncode == 0, (
        f"rotate-api-keys.sh {app} exited {result.returncode}:\n{result.stderr}"
    )

    new_key = _read_xml_key(xml_path)
    assert new_key != old_key, f"{app}: key was not changed (still {old_key!r})"

    port = int(ENV.get(https_port_var, "0"))
    health_url = f"https://localhost:{port}/{url_base}/api/{api_ver}/health"

    # New key is accepted
    resp = requests.get(
        health_url, headers={"X-Api-Key": new_key}, verify=False, timeout=TIMEOUT
    )
    assert resp.status_code == 200, (
        f"{app}: new key not accepted by health endpoint (HTTP {resp.status_code})"
    )

    # Old key is rejected
    resp = requests.get(
        health_url, headers={"X-Api-Key": old_key}, verify=False, timeout=TIMEOUT
    )
    assert resp.status_code == 401, (
        f"{app}: old key still accepted after rotation (HTTP {resp.status_code})"
    )

    # Prowlarr Applications table was updated
    prowlarr_key = _read_xml_key("configs/prowlarr/config/config.xml")
    stored = _prowlarr_key_for_app(prowlarr_key, prowlarr_app_id)
    assert stored == new_key, (
        f"Prowlarr Applications[{prowlarr_app_id}] ({app}) has stale key {stored!r}, expected {new_key!r}"
    )

    # Sonarr and Radarr also propagate to Bazarr and recyclarr
    if app in ("sonarr", "radarr"):
        with open(REPO_ROOT / "configs/bazarr/config/config/config.yaml") as fh:
            bazarr_cfg = yaml.safe_load(fh)
        assert bazarr_cfg[app]["apikey"] == new_key, (
            f"Bazarr config.yaml {app}.apikey not updated (got {bazarr_cfg[app]['apikey']!r})"
        )

        with open(REPO_ROOT / "configs/recyclarr/config/secrets.yml") as fh:
            recyclarr_cfg = yaml.safe_load(fh)
        assert recyclarr_cfg[f"{app}_apikey"] == new_key, (
            f"recyclarr secrets.yml {app}_apikey not updated"
        )

    # Restore original key so subsequent tests keep working
    _restore_arr_key(app, https_port_var, url_base, api_ver, old_key, new_key)

    # After restore, old key must be accepted again
    resp = requests.get(
        health_url, headers={"X-Api-Key": old_key}, verify=False, timeout=TIMEOUT
    )
    assert resp.status_code == 200, (
        f"{app}: could not restore old key (HTTP {resp.status_code})"
    )

    # Also restore consumers that were updated by the script
    if app == "sonarr":
        with open(REPO_ROOT / "configs/bazarr/config/config/config.yaml") as fh:
            bazarr_cfg = yaml.safe_load(fh)
        bazarr_cfg["sonarr"]["apikey"] = old_key
        with open(REPO_ROOT / "configs/bazarr/config/config/config.yaml", "w") as fh:
            yaml.dump(bazarr_cfg, fh, default_flow_style=False, allow_unicode=True)
        with open(REPO_ROOT / "configs/recyclarr/config/secrets.yml") as fh:
            recyclarr_cfg = yaml.safe_load(fh)
        recyclarr_cfg["sonarr_apikey"] = old_key
        with open(REPO_ROOT / "configs/recyclarr/config/secrets.yml", "w") as fh:
            yaml.dump(recyclarr_cfg, fh, default_flow_style=False)

    if app == "radarr":
        with open(REPO_ROOT / "configs/bazarr/config/config/config.yaml") as fh:
            bazarr_cfg = yaml.safe_load(fh)
        bazarr_cfg["radarr"]["apikey"] = old_key
        with open(REPO_ROOT / "configs/bazarr/config/config/config.yaml", "w") as fh:
            yaml.dump(bazarr_cfg, fh, default_flow_style=False, allow_unicode=True)
        with open(REPO_ROOT / "configs/recyclarr/config/secrets.yml") as fh:
            recyclarr_cfg = yaml.safe_load(fh)
        recyclarr_cfg["radarr_apikey"] = old_key
        with open(REPO_ROOT / "configs/recyclarr/config/secrets.yml", "w") as fh:
            yaml.dump(recyclarr_cfg, fh, default_flow_style=False)
