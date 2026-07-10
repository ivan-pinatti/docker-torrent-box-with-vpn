"""Integration tests for scripts/rotate-api-keys.sh.

These tests execute the rotation script against the live stack, verify the new
key propagated to every consumer, then restore the original key so the suite
remains idempotent. They are marked `rotation` and are excluded from the
default `make test` run because they modify running service state.

App ports are not published to the host, so all API calls run curl inside the
target container (see conftest.container_http), matching how the rotation
scripts themselves talk to the apps.

Run explicitly with:
    pytest -m rotation tests/test_rotate_api_keys.py
"""

import json
import sqlite3
import subprocess
import xml.etree.ElementTree as ET

import pytest
import yaml

from conftest import (
    ENV,
    REPO_ROOT,
    container_http,
    homepage_widget_failures,
    is_enabled,
    recreate_container,
    skip_if_not_running,
    wait_for_healthy,
    wait_for_homepage_ready,
)

pytestmark = pytest.mark.rotation

TIMEOUT = 30
SCRIPTS = REPO_ROOT / "scripts"

BAZARR_CONFIG = REPO_ROOT / "configs/bazarr/config/config/config.yaml"
RECYCLARR_SECRETS = REPO_ROOT / "configs/recyclarr/config/secrets.yml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_script(script: str, target: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(SCRIPTS / script), target],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )


def _read_xml_key(rel_path: str) -> str:
    path = REPO_ROOT / rel_path
    tree = ET.parse(path)
    elem = tree.find("ApiKey")
    assert elem is not None and elem.text, f"ApiKey not found in {rel_path}"
    return elem.text


def _health_status(
    app: str, scheme: str, port: int, url_base: str, api_ver: str, key: str
) -> int:
    status, _ = container_http(
        app,
        f"{scheme}://127.0.0.1:{port}/{url_base}/api/{api_ver}/health",
        headers={"X-Api-Key": key},
        timeout=TIMEOUT,
    )
    return status


def _restore_arr_key(app: str, xml_path: str, old_key: str):
    """Write old_key back to config.xml and restart the app to load it.

    The arr apps ignore apiKey changes sent over their API, so restore uses
    the same mechanism as the rotation script: edit config.xml and restart.
    """
    subprocess.run(
        [
            "xmlstarlet",
            "--quiet",
            "ed",
            "--inplace",
            "--update",
            "/Config/ApiKey",
            "--value",
            old_key,
            str(REPO_ROOT / xml_path),
        ],
        check=True,
    )
    subprocess.run(["podman", "restart", app], check=True, capture_output=True)
    assert wait_for_healthy(app), f"{app} did not become healthy after key restore"


def _prowlarr_application(prowlarr_api_key: str, app_name: str) -> dict | None:
    """Return the Prowlarr Applications entry for app_name, or None if absent."""
    port = int(ENV.get("PROWLARR_HTTPS_PORT", "6969"))
    status, body = container_http(
        "prowlarr",
        f"https://127.0.0.1:{port}/prowlarr/api/v1/applications",
        headers={"X-Api-Key": prowlarr_api_key},
        timeout=TIMEOUT,
    )
    if status != 200:
        return None
    for app in json.loads(body):
        if app.get("name") == app_name:
            return app
    return None


def _prowlarr_stored_key(app_name: str) -> str | None:
    """Return the apiKey Prowlarr stores for an app, read from prowlarr.db.

    The Prowlarr API redacts apiKey values in GET responses, so the only way
    to verify the stored value is to read the Applications table directly.
    """
    conn = sqlite3.connect(
        f"file:{REPO_ROOT}/configs/prowlarr/config/prowlarr.db?mode=ro", uri=True
    )
    row = conn.execute(
        "SELECT Settings FROM Applications WHERE Name = ?", (app_name,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return json.loads(row[0]).get("apiKey")


def _set_prowlarr_key_for_app(prowlarr_api_key: str, app_name: str, key: str):
    """Write an app's API key back into Prowlarr's Applications table."""
    app_json = _prowlarr_application(prowlarr_api_key, app_name)
    assert app_json is not None, f"Prowlarr application '{app_name}' not found"
    for field in app_json.get("fields", []):
        if field.get("name") == "apiKey":
            field["value"] = key
    port = int(ENV.get("PROWLARR_HTTPS_PORT", "6969"))
    status, _ = container_http(
        "prowlarr",
        f"https://127.0.0.1:{port}/prowlarr/api/v1/applications/{app_json['id']}",
        method="PUT",
        headers={"X-Api-Key": prowlarr_api_key, "Content-Type": "application/json"},
        data=json.dumps(app_json),
        timeout=TIMEOUT,
    )
    assert status in (200, 202), (
        f"Could not restore Prowlarr application '{app_name}': {status}"
    )


def _restore_yaml_consumers(app: str, old_key: str):
    """Restore Bazarr and Recyclarr entries for sonarr/radarr."""
    with open(BAZARR_CONFIG) as fh:
        bazarr_cfg = yaml.safe_load(fh)
    bazarr_cfg[app]["apikey"] = old_key
    with open(BAZARR_CONFIG, "w") as fh:
        yaml.dump(bazarr_cfg, fh, default_flow_style=False, allow_unicode=True)

    with open(RECYCLARR_SECRETS) as fh:
        recyclarr_cfg = yaml.safe_load(fh)
    recyclarr_cfg[f"{app}_apikey"] = old_key
    with open(RECYCLARR_SECRETS, "w") as fh:
        yaml.dump(recyclarr_cfg, fh, default_flow_style=False)


def _restore_homepage_key(var_name: str, old_key: str):
    path = REPO_ROOT / "configs/homepage/.env.secrets"
    if not path.exists():
        return
    lines = path.read_text().splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"{var_name}="):
            lines[i] = f"{var_name}={old_key}"
            break
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "app,xml_path,scheme,port_var,url_base,api_ver",
    [
        (
            "sonarr",
            "configs/sonarr/config/config.xml",
            "http",
            "SONARR_HTTP_PORT",
            "sonarr",
            "v3",
        ),
        (
            "radarr",
            "configs/radarr/config/config.xml",
            "https",
            "RADARR_HTTPS_PORT",
            "radarr",
            "v3",
        ),
        (
            "lidarr",
            "configs/lidarr/config/config.xml",
            "https",
            "LIDARR_HTTPS_PORT",
            "lidarr",
            "v1",
        ),
        (
            "readarr",
            "configs/readarr/config/config.xml",
            "https",
            "READARR_HTTPS_PORT",
            "readarr",
            "v1",
        ),
        (
            "whisparr",
            "configs/whisparr/config/config.xml",
            "https",
            "WHISPARR_HTTPS_PORT",
            "whisparr",
            "v3",
        ),
    ],
)
def test_rotate_api_key_propagates(
    app,
    xml_path,
    scheme,
    port_var,
    url_base,
    api_ver,
    running_containers,
):
    """Rotating an arr app's API key updates all consumers and the new key works."""
    if not is_enabled(app):
        pytest.skip(f"{app} profile is disabled")
    skip_if_not_running(app, running_containers)
    skip_if_not_running("prowlarr", running_containers)

    old_key = _read_xml_key(xml_path)
    port = int(ENV.get(port_var, "0"))

    result = _run_script("rotate-api-keys.sh", app)
    assert result.returncode == 0, (
        f"rotate-api-keys.sh {app} exited {result.returncode}:\n{result.stderr}"
    )

    new_key = _read_xml_key(xml_path)
    assert new_key != old_key, f"{app}: key was not changed"

    # The script recreates the app container; wait for it to come back.
    assert wait_for_healthy(app), f"{app} did not become healthy after rotation"

    # New key is accepted
    status = _health_status(app, scheme, port, url_base, api_ver, new_key)
    assert status == 200, (
        f"{app}: new key not accepted by health endpoint (HTTP {status})"
    )

    # Old key is rejected
    status = _health_status(app, scheme, port, url_base, api_ver, old_key)
    assert status == 401, (
        f"{app}: old key still accepted after rotation (HTTP {status})"
    )

    # Prowlarr Applications table was updated (skipped for apps that have no
    # application entry in Prowlarr, e.g. Whisparr)
    prowlarr_key = _read_xml_key("configs/prowlarr/config/config.xml")
    prowlarr_entry = _prowlarr_application(prowlarr_key, app.capitalize())
    if prowlarr_entry is not None:
        stored = _prowlarr_stored_key(app.capitalize())
        assert stored == new_key, (
            f"Prowlarr application '{app}' has a stale key, expected the rotated one"
        )

    # Sonarr and Radarr also propagate to Bazarr and recyclarr
    if app in ("sonarr", "radarr"):
        with open(BAZARR_CONFIG) as fh:
            bazarr_cfg = yaml.safe_load(fh)
        assert bazarr_cfg[app]["apikey"] == new_key, (
            f"Bazarr config.yaml {app}.apikey not updated"
        )

        with open(RECYCLARR_SECRETS) as fh:
            recyclarr_cfg = yaml.safe_load(fh)
        assert recyclarr_cfg[f"{app}_apikey"] == new_key, (
            f"recyclarr secrets.yml {app}_apikey not updated"
        )

    # Homepage was recreated by the script and must work with the new key
    if "homepage" in running_containers:
        assert wait_for_homepage_ready(), "homepage API did not respond after rotation"
        failures = homepage_widget_failures(only_services={app})
        assert not failures, (
            f"Homepage widget broken after rotating {app}:\n" + "\n".join(failures)
        )

    # ------------------------------------------------------------------
    # Restore the original key everywhere so the suite stays idempotent
    # ------------------------------------------------------------------
    _restore_arr_key(app, xml_path, old_key)

    status = _health_status(app, scheme, port, url_base, api_ver, old_key)
    assert status == 200, f"{app}: could not restore old key (HTTP {status})"

    if prowlarr_entry is not None:
        _set_prowlarr_key_for_app(prowlarr_key, app.capitalize(), old_key)

    if app in ("sonarr", "radarr"):
        _restore_yaml_consumers(app, old_key)
    _restore_homepage_key(f"HOMEPAGE_VAR_{app.upper()}_API_KEY", old_key)

    # Homepage reads env only at creation; recreate it so the restored key is
    # live again, then verify the widget still works.
    if "homepage" in running_containers:
        recreate_container("homepage")
        assert wait_for_homepage_ready(), "homepage API did not respond after restore"
        failures = homepage_widget_failures(only_services={app})
        assert not failures, (
            f"Homepage widget broken after restoring {app}:\n" + "\n".join(failures)
        )


# ---------------------------------------------------------------------------
# INI-configured apps (LazyLibrarian, Mylar), NZBHydra2, and Jellyfin.
# These rotations are forward-only: every consumer is updated by the script,
# so there is no state to restore.
# ---------------------------------------------------------------------------


def _read_ini_api_key(rel_path: str) -> str:
    for line in (REPO_ROOT / rel_path).read_text().splitlines():
        if line.startswith("api_key = "):
            return line.split("= ", 1)[1]
    return ""


LAZYLIBRARIAN_INI = "configs/lazylibrarian/config/config.ini"
MYLAR_INI = "configs/mylar/config/mylar/config.ini"


def test_rotate_lazylibrarian_api_key(running_containers):
    """Rotating LazyLibrarian's API key updates config.ini and Prowlarr."""
    skip_if_not_running("lazylibrarian", running_containers)
    skip_if_not_running("prowlarr", running_containers)

    old_key = _read_ini_api_key(LAZYLIBRARIAN_INI)
    result = _run_script("rotate-api-keys.sh", "lazylibrarian")
    assert result.returncode == 0, (
        f"rotate-api-keys.sh lazylibrarian exited {result.returncode}:\n{result.stderr}"
    )

    new_key = _read_ini_api_key(LAZYLIBRARIAN_INI)
    assert new_key and new_key != old_key, "LazyLibrarian api_key was not changed"
    assert _prowlarr_stored_key("LazyLibrarian") == new_key, (
        "Prowlarr's LazyLibrarian entry was not updated"
    )
    assert wait_for_healthy("lazylibrarian"), "lazylibrarian unhealthy after rotation"


def test_rotate_mylar_api_key(running_containers):
    """Rotating Mylar's API key updates config.ini, Prowlarr, and Homepage."""
    skip_if_not_running("mylar", running_containers)
    skip_if_not_running("prowlarr", running_containers)

    old_key = _read_ini_api_key(MYLAR_INI)
    result = _run_script("rotate-api-keys.sh", "mylar")
    assert result.returncode == 0, (
        f"rotate-api-keys.sh mylar exited {result.returncode}:\n{result.stderr}"
    )

    new_key = _read_ini_api_key(MYLAR_INI)
    assert new_key and new_key != old_key, "Mylar api_key was not changed"
    assert _prowlarr_stored_key("Mylar") == new_key, (
        "Prowlarr's Mylar entry was not updated"
    )
    assert wait_for_healthy("mylar"), "mylar unhealthy after rotation"

    if "homepage" in running_containers:
        assert wait_for_homepage_ready(), "homepage API did not respond"
        failures = homepage_widget_failures(only_services={"mylar"})
        assert not failures, (
            "Homepage Mylar widget broken after rotation:\n" + "\n".join(failures)
        )


def test_rotate_nzbhydra2_api_key(running_containers):
    """Rotating NZBHydra2's key updates the yml and every consumer."""
    skip_if_not_running("nzbhydra2", running_containers)

    def ll_hydra_key() -> str:
        for line in (REPO_ROOT / LAZYLIBRARIAN_INI).read_text().splitlines():
            if line.startswith("api = "):
                return line.split("= ", 1)[1]
        return ""

    old_key = ll_hydra_key()
    result = _run_script("rotate-api-keys.sh", "nzbhydra2")
    assert result.returncode == 0, (
        f"rotate-api-keys.sh nzbhydra2 exited {result.returncode}:\n{result.stderr}"
    )

    new_key = ll_hydra_key()
    assert new_key and new_key != old_key, "NZBHydra2 key was not changed"

    # All arr Indexers entries point at the new key
    from test_rotate_passwords import ARR_DB_PATHS

    for svc, db_rel in ARR_DB_PATHS.items():
        db_path = REPO_ROOT / db_rel
        if not db_path.exists():
            continue
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        for name, settings in conn.execute("SELECT Name, Settings FROM Indexers"):
            data = json.loads(settings)
            if "nzbhydra" in str(data.get("baseUrl", "")).lower():
                assert data.get("apiKey") == new_key, (
                    f"{svc} indexer '{name}' still holds the old NZBHydra2 key"
                )
        conn.close()

    # Mylar's extra_newznabs/extra_torznabs entries carry the new key
    assert new_key in (REPO_ROOT / MYLAR_INI).read_text(), (
        "Mylar config does not carry the new NZBHydra2 key"
    )

    # NZBHydra2 accepts the new key and rejects a wrong one (both are HTTP
    # 200; the body distinguishes results from the error envelope)
    assert wait_for_healthy("nzbhydra2"), "nzbhydra2 unhealthy after rotation"
    port = int(ENV.get("NZBHYDRA2_HTTPS_PORT", "5077"))
    _, body = container_http(
        "nzbhydra2",
        f"https://127.0.0.1:{port}/nzbhydra2/api?t=caps&apikey={new_key}",
        timeout=TIMEOUT,
    )
    assert "<error" not in body, f"NZBHydra2 rejected the new key: {body[:120]}"
    _, body = container_http(
        "nzbhydra2",
        f"https://127.0.0.1:{port}/nzbhydra2/api?t=caps&apikey={old_key}",
        timeout=TIMEOUT,
    )
    assert "<error" in body, "NZBHydra2 still accepts the old key"


def test_rotate_jellyfin_api_key(running_containers):
    """Rotating Jellyfin's key creates a new one, adopts it, revokes the old."""
    skip_if_not_running("jellyfin", running_containers)

    env_path = REPO_ROOT / "configs/homepage/.env.secrets"
    if not env_path.exists():
        pytest.skip("homepage .env.secrets not present")

    def homepage_jellyfin_key() -> str:
        for line in env_path.read_text().splitlines():
            if line.startswith("HOMEPAGE_VAR_JELLYFIN_KEY="):
                return line.split("=", 1)[1]
        return ""

    old_key = homepage_jellyfin_key()
    result = _run_script("rotate-api-keys.sh", "jellyfin")
    assert result.returncode == 0, (
        f"rotate-api-keys.sh jellyfin exited {result.returncode}:\n{result.stderr}"
    )

    new_key = homepage_jellyfin_key()
    assert new_key and new_key != old_key, "Jellyfin key was not changed"

    port = int(ENV.get("JELLYFIN_HTTP_PORT", "8096"))
    status, _ = container_http(
        "jellyfin",
        f"http://127.0.0.1:{port}/jellyfin/Auth/Keys",
        headers={"Authorization": f'MediaBrowser Token="{new_key}"'},
        timeout=TIMEOUT,
    )
    assert status == 200, f"Jellyfin does not accept the new key (HTTP {status})"

    status, _ = container_http(
        "jellyfin",
        f"http://127.0.0.1:{port}/jellyfin/Auth/Keys",
        headers={"Authorization": f'MediaBrowser Token="{old_key}"'},
        timeout=TIMEOUT,
    )
    assert status == 401, f"Jellyfin still accepts the revoked key (HTTP {status})"

    if "homepage" in running_containers:
        assert wait_for_homepage_ready(), "homepage API did not respond"
        failures = homepage_widget_failures(only_services={"jellyfin"})
        assert not failures, (
            "Homepage Jellyfin widget broken after rotation:\n" + "\n".join(failures)
        )
