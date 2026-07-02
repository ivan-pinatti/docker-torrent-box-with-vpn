"""Integration tests for scripts/rotate-passwords.sh.

These tests execute the rotation script against the live stack, verify the new
password is accepted and propagated to every consumer, then restore the original
password. They are marked `rotation` and excluded from the default test run.

Run explicitly with:
    pytest -m rotation tests/test_rotate_passwords.py
"""

import json
import sqlite3
import subprocess

import pytest
import requests
import urllib3

from conftest import (
    ENV,
    REPO_ROOT,
    base_url,
    is_enabled,
    read_api_key,
    skip_if_not_running,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

pytestmark = pytest.mark.rotation

TIMEOUT = 30
BASE = base_url(https=True)
SCRIPTS = REPO_ROOT / "scripts"

ARR_APPS_WITH_QBT = ("sonarr", "radarr", "lidarr", "readarr", "whisparr")


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


def _read_qbt_password_from_db(db_path) -> str:
    """Return the plain-text qBittorrent password stored in an arr DB."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        "SELECT Settings FROM DownloadClients WHERE ConfigContract='QBittorrentSettings' LIMIT 1"
    )
    row = cur.fetchone()
    conn.close()
    assert row is not None, f"No QBittorrentSettings row in {db_path}"
    return json.loads(row[0]).get("password", "")


def _set_qbt_password_in_db(db_path, password: str):
    """Overwrite the qBittorrent password in an arr DB's DownloadClients table."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        "SELECT Id, Settings FROM DownloadClients WHERE ConfigContract='QBittorrentSettings'"
    )
    for row_id, settings_json in cur.fetchall():
        settings = json.loads(settings_json)
        settings["password"] = password
        cur.execute(
            "UPDATE DownloadClients SET Settings = ? WHERE Id = ?",
            (json.dumps(settings), row_id),
        )
    conn.commit()
    conn.close()


def _qbt_login(password: str) -> bool:
    """Return True if qBittorrent accepts the given password."""
    port = int(ENV.get("QBITTORRENT_HTTPS_PORT", "8085"))
    resp = requests.post(
        f"https://localhost:{port}/api/v2/auth/login",
        data={"username": "qbittorrent", "password": password},
        verify=False,
        timeout=TIMEOUT,
    )
    return resp.status_code == 200 and resp.text.strip() == "Ok."


def _arr_login(
    app: str, url_base: str, https_port_var: str, api_ver: str, password: str
) -> bool:
    """Return True if the arr app's login endpoint accepts the given password."""
    port = int(ENV.get(https_port_var, "0"))
    resp = requests.post(
        f"https://localhost:{port}/{url_base}/login",
        data={"username": app, "password": password},
        verify=False,
        timeout=TIMEOUT,
        allow_redirects=False,
    )
    # Successful login redirects away from /login (302); failure stays on /login (200 with error).
    return resp.status_code in (302, 303)


# ---------------------------------------------------------------------------
# qBittorrent password rotation
# ---------------------------------------------------------------------------


def test_rotate_qbittorrent_password_propagates(running_containers):
    """Rotating the qBittorrent password updates all arr DownloadClients tables."""
    if not is_enabled("qbittorrent"):
        pytest.skip("qbittorrent profile is disabled")
    skip_if_not_running("qbittorrent", running_containers)

    sonarr_db = REPO_ROOT / "configs/sonarr/config/sonarr.db"
    old_password = _read_qbt_password_from_db(sonarr_db)

    result = _run_script("rotate-passwords.sh", "qbittorrent")
    assert result.returncode == 0, (
        f"rotate-passwords.sh qbittorrent exited {result.returncode}:\n{result.stderr}"
    )

    new_password = _read_qbt_password_from_db(sonarr_db)
    assert new_password != old_password, "Password was not changed"

    # New password is accepted by qBittorrent
    assert _qbt_login(new_password), "qBittorrent does not accept the new password"

    # Old password is rejected
    assert not _qbt_login(old_password), "qBittorrent still accepts the old password"

    # All arr DBs were updated
    for svc in ARR_APPS_WITH_QBT:
        if not is_enabled(svc):
            continue
        db_path = REPO_ROOT / f"configs/{svc}/config/{svc}.db"
        stored = _read_qbt_password_from_db(db_path)
        assert stored == new_password, (
            f"{svc} DB still holds old qBittorrent password (got {stored!r})"
        )

    # Restore: set old password directly in qBittorrent via API (login with new pw first)
    port = int(ENV.get("QBITTORRENT_HTTPS_PORT", "8085"))
    session = requests.Session()
    session.verify = False
    session.post(
        f"https://localhost:{port}/api/v2/auth/login",
        data={"username": "qbittorrent", "password": new_password},
        timeout=TIMEOUT,
    )
    session.post(
        f"https://localhost:{port}/api/v2/app/setPreferences",
        data={"json": json.dumps({"web_ui_password": old_password})},
        timeout=TIMEOUT,
    )
    for svc in ARR_APPS_WITH_QBT:
        db_path = REPO_ROOT / f"configs/{svc}/config/{svc}.db"
        if db_path.exists():
            _set_qbt_password_in_db(db_path, old_password)

    assert _qbt_login(old_password), "Could not restore original qBittorrent password"


# ---------------------------------------------------------------------------
# Arr app login-password rotation
# ---------------------------------------------------------------------------


def _read_arr_password_hash(db_path) -> str | None:
    """Return the raw password hash from an arr app's Users table."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT Password FROM Users LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def _restore_arr_password(
    app: str,
    https_port_var: str,
    url_base: str,
    api_ver: str,
    api_key: str,
    original_password: str,
):
    """Set an arr app's login password back to original_password via its host config API."""
    port = int(ENV.get(https_port_var, "0"))
    url = f"https://localhost:{port}/{url_base}/api/{api_ver}/config/host"
    resp = requests.get(
        url, headers={"X-Api-Key": api_key}, verify=False, timeout=TIMEOUT
    )
    assert resp.status_code == 200
    cfg = resp.json()
    cfg["password"] = original_password
    cfg["passwordConfirmation"] = original_password
    resp = requests.put(
        url, json=cfg, headers={"X-Api-Key": api_key}, verify=False, timeout=TIMEOUT
    )
    assert resp.status_code in (200, 202), (
        f"Could not restore {app} password: HTTP {resp.status_code}"
    )


@pytest.mark.parametrize(
    "app,https_port_var,url_base,api_ver,db_rel",
    [
        (
            "sonarr",
            "SONARR_HTTPS_PORT",
            "sonarr",
            "v3",
            "configs/sonarr/config/sonarr.db",
        ),
        (
            "radarr",
            "RADARR_HTTPS_PORT",
            "radarr",
            "v3",
            "configs/radarr/config/radarr.db",
        ),
        (
            "lidarr",
            "LIDARR_HTTPS_PORT",
            "lidarr",
            "v1",
            "configs/lidarr/config/lidarr.db",
        ),
        (
            "readarr",
            "READARR_HTTPS_PORT",
            "readarr",
            "v1",
            "configs/readarr/config/readarr.db",
        ),
        (
            "whisparr",
            "WHISPARR_HTTPS_PORT",
            "whisparr",
            "v3",
            "configs/whisparr/config/whisparr.db",
        ),
        (
            "prowlarr",
            "PROWLARR_HTTPS_PORT",
            "prowlarr",
            "v1",
            "configs/prowlarr/config/prowlarr.db",
        ),
    ],
)
def test_rotate_arr_password(
    app, https_port_var, url_base, api_ver, db_rel, running_containers
):
    """Rotating an arr login password changes the DB hash and the service stays healthy."""
    if not is_enabled(app):
        pytest.skip(f"{app} profile is disabled")
    skip_if_not_running(app, running_containers)

    db_path = REPO_ROOT / db_rel
    old_hash = _read_arr_password_hash(db_path)

    # The default password matches the app name; capture it for restore.
    original_password = app

    result = _run_script("rotate-passwords.sh", app)
    assert result.returncode == 0, (
        f"rotate-passwords.sh {app} exited {result.returncode}:\n{result.stderr}"
    )

    new_hash = _read_arr_password_hash(db_path)
    assert new_hash != old_hash, (
        f"{app}: password hash in DB was not changed after rotation"
    )

    # Service health endpoint must still respond with the API key (service not broken)
    api_key = read_api_key(app)
    assert api_key, f"Could not read API key for {app}"
    port = int(ENV.get(https_port_var, "0"))
    resp = requests.get(
        f"https://localhost:{port}/{url_base}/api/{api_ver}/health",
        headers={"X-Api-Key": api_key},
        verify=False,
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, (
        f"{app} health unreachable after password rotation (HTTP {resp.status_code})"
    )

    # Restore original password via API so the suite stays idempotent
    _restore_arr_password(
        app, https_port_var, url_base, api_ver, api_key, original_password
    )
