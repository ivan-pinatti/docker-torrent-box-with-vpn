"""Integration tests for scripts/rotate-passwords.sh.

These tests execute the rotation script against the live stack, verify the new
password is accepted and propagated to every consumer, then restore the original
password. They are marked `rotation` and excluded from the default test run.

App ports are not published to the host, so all API calls run curl inside the
target container (see conftest.container_http), matching how the rotation
scripts themselves talk to the apps.

Run explicitly with:
    pytest -m rotation tests/test_rotate_passwords.py
"""

import json
import sqlite3
import subprocess
import time

import pytest

from conftest import (
    ENV,
    REPO_ROOT,
    container_http,
    homepage_widget_failures,
    is_enabled,
    read_api_key,
    recreate_container,
    skip_if_not_running,
    wait_for_healthy,
    wait_for_homepage_ready,
)

pytestmark = pytest.mark.rotation

TIMEOUT = 30
SCRIPTS = REPO_ROOT / "scripts"

ARR_APPS_WITH_QBT = ("sonarr", "radarr", "lidarr", "readarr", "whisparr")

# Whisparr v3 names its DB whisparr3.db; the others match the service name.
ARR_DB_PATHS = {
    svc: f"configs/{svc}/config/{'whisparr3' if svc == 'whisparr' else svc}.db"
    for svc in ARR_APPS_WITH_QBT
}


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


# qBittorrent's WebUI binds to the Gluetun services IP, not loopback.
QBT_HOST = ENV.get("GLUETUN_SERVICES_IP", "127.0.0.1")

QBT_CONF = REPO_ROOT / "configs/qbittorrent/config/qBittorrent/qBittorrent.conf"


def _qbt_api_ok() -> bool:
    """Return True if the qBittorrent WebUI API responds."""
    port = int(ENV.get("QBITTORRENT_HTTPS_PORT", "8085"))
    status, _ = container_http(
        "qbittorrent",
        f"https://{QBT_HOST}:{port}/api/v2/app/version",
        timeout=TIMEOUT,
    )
    return status == 200


def _qbt_stored_password_hash() -> str:
    """Return the PBKDF2 hash stored in qBittorrent.conf.

    qBittorrent flushes its config on shutdown, so callers must restart the
    container before comparing hashes.
    """
    for line in QBT_CONF.read_text().splitlines():
        if line.startswith("WebUI\\Password_PBKDF2="):
            return line.split("=", 1)[1]
    return ""


def _qbt_restart_and_wait():
    subprocess.run(
        ["podman", "restart", "qbittorrent"], check=True, capture_output=True
    )
    for _ in range(30):
        if _qbt_api_ok():
            return
        time.sleep(3)
    pytest.fail("qBittorrent API did not come back after restart")


def _qbt_set_password(current_password: str, new_password: str):
    """Set the qBittorrent WebUI password via its API, inside the container."""
    port = int(ENV.get("QBITTORRENT_HTTPS_PORT", "8085"))
    jar = "/tmp/qbt_test_cookies.txt"
    login = (
        f"curl -sk -c {jar} -d 'username=qbittorrent&password={current_password}' "
        f"https://{QBT_HOST}:{port}/api/v2/auth/login"
    )
    payload = json.dumps({"web_ui_password": new_password})
    set_pref = (
        f"curl -sk -b {jar} --data-urlencode 'json={payload}' "
        f"https://{QBT_HOST}:{port}/api/v2/app/setPreferences"
    )
    subprocess.run(
        [
            "podman",
            "exec",
            "qbittorrent",
            "sh",
            "-c",
            f"{login} && {set_pref}; rm -f {jar}",
        ],
        check=True,
        capture_output=True,
        timeout=TIMEOUT * 3,
    )


# ---------------------------------------------------------------------------
# qBittorrent password rotation
# ---------------------------------------------------------------------------


def test_rotate_qbittorrent_password_propagates(running_containers):
    """Rotating the qBittorrent password updates qBittorrent and all consumers.

    Login-based verification is impossible here: the WebUI whitelists the
    services subnet (WebUI\\AuthSubnetWhitelist), and every reachable client
    lives on it, so /auth/login succeeds regardless of password. Instead the
    test verifies the PBKDF2 hash stored in qBittorrent.conf changed (the
    config is flushed on restart) and that all consumers were updated.
    """
    if not is_enabled("qbittorrent"):
        pytest.skip("qbittorrent profile is disabled")
    skip_if_not_running("qbittorrent", running_containers)

    sonarr_db = REPO_ROOT / ARR_DB_PATHS["sonarr"]
    old_password = _read_qbt_password_from_db(sonarr_db)
    _qbt_restart_and_wait()  # flush config so the pre-rotation hash is current
    old_hash = _qbt_stored_password_hash()

    result = _run_script("rotate-passwords.sh", "qbittorrent")
    assert result.returncode == 0, (
        f"rotate-passwords.sh qbittorrent exited {result.returncode}:\n{result.stderr}"
    )

    new_password = _read_qbt_password_from_db(sonarr_db)
    assert new_password != old_password, "Password was not changed"

    # qBittorrent stored a new password hash (visible in conf after a flush)
    _qbt_restart_and_wait()
    new_hash = _qbt_stored_password_hash()
    assert new_hash != old_hash, "qBittorrent.conf password hash did not change"

    # All arr DBs were updated
    for svc in ARR_APPS_WITH_QBT:
        if not is_enabled(svc):
            continue
        db_path = REPO_ROOT / ARR_DB_PATHS[svc]
        stored = _read_qbt_password_from_db(db_path)
        assert stored == new_password, f"{svc} DB still holds old qBittorrent password"

    # .env.secrets consumers were updated
    for rel_path, var in (
        ("configs/homepage/.env.secrets", "HOMEPAGE_VAR_QBITTORRENT_PASS"),
        ("configs/qbittorrent/.env.secrets", "PASSWORD"),
        ("configs/qbittorrent_exporter/.env.secrets", "QBITTORRENT_PASS"),
    ):
        path = REPO_ROOT / rel_path
        if path.exists():
            assert f"{var}={new_password}" in path.read_text(), (
                f"{rel_path} was not updated with the new password"
            )

    # Homepage was recreated by the script and must work with the new password
    if "homepage" in running_containers:
        assert wait_for_homepage_ready(), "homepage API did not respond after rotation"
        failures = homepage_widget_failures(only_services={"qbittorrent"})
        assert not failures, (
            "Homepage qBittorrent widget broken after rotation:\n" + "\n".join(failures)
        )

    # Restore the original password everywhere
    _qbt_set_password(new_password, old_password)
    for svc in ARR_APPS_WITH_QBT:
        db_path = REPO_ROOT / ARR_DB_PATHS[svc]
        if db_path.exists():
            _set_qbt_password_in_db(db_path, old_password)
    for rel_path, var in (
        ("configs/homepage/.env.secrets", "HOMEPAGE_VAR_QBITTORRENT_PASS"),
        ("configs/qbittorrent/.env.secrets", "PASSWORD"),
        ("configs/qbittorrent_exporter/.env.secrets", "QBITTORRENT_PASS"),
    ):
        path = REPO_ROOT / rel_path
        if path.exists():
            lines = path.read_text().splitlines()
            for i, line in enumerate(lines):
                if line.startswith(f"{var}="):
                    lines[i] = f"{var}={old_password}"
            path.write_text("\n".join(lines) + "\n")

    assert _qbt_api_ok(), "qBittorrent API not reachable after restore"

    # Recreate the env consumers so the restored password is live again
    if "homepage" in running_containers:
        recreate_container("homepage")
        assert wait_for_homepage_ready(), "homepage API did not respond after restore"
        failures = homepage_widget_failures(only_services={"qbittorrent"})
        assert not failures, (
            "Homepage qBittorrent widget broken after restore:\n" + "\n".join(failures)
        )
    if "qbittorrent_exporter" in running_containers:
        recreate_container("qbittorrent_exporter")


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
    scheme: str,
    port: int,
    url_base: str,
    api_ver: str,
    api_key: str,
    original_password: str,
):
    """Set an arr app's login password back to original_password via its host config API."""
    url = f"{scheme}://127.0.0.1:{port}/{url_base}/api/{api_ver}/config/host"
    status, body = container_http(
        app, url, headers={"X-Api-Key": api_key}, timeout=TIMEOUT
    )
    assert status == 200, f"Could not GET host config for {app}: HTTP {status}"
    cfg = json.loads(body)
    cfg["password"] = original_password
    cfg["passwordConfirmation"] = original_password
    status, _ = container_http(
        app,
        url,
        method="PUT",
        headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
        data=json.dumps(cfg),
        timeout=TIMEOUT,
    )
    assert status in (200, 202), f"Could not restore {app} password: HTTP {status}"


@pytest.mark.parametrize(
    "app,scheme,port_var,url_base,api_ver",
    [
        # Sonarr has no working SSL listener (see README known issues), so it
        # is exercised over its HTTP port like the rotation script does.
        ("sonarr", "http", "SONARR_HTTP_PORT", "sonarr", "v3"),
        ("radarr", "https", "RADARR_HTTPS_PORT", "radarr", "v3"),
        ("lidarr", "https", "LIDARR_HTTPS_PORT", "lidarr", "v1"),
        ("readarr", "https", "READARR_HTTPS_PORT", "readarr", "v1"),
        ("whisparr", "https", "WHISPARR_HTTPS_PORT", "whisparr", "v3"),
        ("prowlarr", "https", "PROWLARR_HTTPS_PORT", "prowlarr", "v1"),
    ],
)
def test_rotate_arr_password(
    app, scheme, port_var, url_base, api_ver, running_containers
):
    """Rotating an arr login password changes the DB hash and the service stays healthy."""
    if not is_enabled(app):
        pytest.skip(f"{app} profile is disabled")
    skip_if_not_running(app, running_containers)

    db_path = REPO_ROOT / ARR_DB_PATHS.get(app, f"configs/{app}/config/{app}.db")
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
    port = int(ENV.get(port_var, "0"))
    status, _ = container_http(
        app,
        f"{scheme}://127.0.0.1:{port}/{url_base}/api/{api_ver}/health",
        headers={"X-Api-Key": api_key},
        timeout=TIMEOUT,
    )
    assert status == 200, (
        f"{app} health unreachable after password rotation (HTTP {status})"
    )

    # Restore original password via API so the suite stays idempotent
    _restore_arr_password(
        app, scheme, port, url_base, api_ver, api_key, original_password
    )


# ---------------------------------------------------------------------------
# Non-arr password rotations (forward-only: consumers are updated by the
# script and the new password is printed in the summary table, which is the
# operator's only copy since the apps store hashes).
# ---------------------------------------------------------------------------


def _summary_password(stdout: str, service: str) -> str:
    """Extract the plaintext new password for a service from the summary table."""
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == service:
            return parts[1]
    return ""


def test_rotate_grafana_password(running_containers):
    """Rotating the Grafana admin password updates grafana.ini and Homepage."""
    skip_if_not_running("grafana", running_containers)

    result = _run_script("rotate-passwords.sh", "grafana")
    assert result.returncode == 0, (
        f"rotate-passwords.sh grafana exited {result.returncode}:\n{result.stderr}"
    )
    new_password = _summary_password(result.stdout, "grafana")
    assert new_password, "Summary table does not contain the new grafana password"

    ini = (REPO_ROOT / "configs/grafana/config/grafana.ini").read_text()
    assert f"admin_password = {new_password}" in ini, "grafana.ini not updated"

    status, _ = container_http(
        "grafana",
        "http://127.0.0.1:3000/api/user",
        extra_args=["-u", f"admin:{new_password}"],
        timeout=TIMEOUT,
    )
    assert status == 200, f"Grafana does not accept the new password (HTTP {status})"

    status, _ = container_http(
        "grafana",
        "http://127.0.0.1:3000/api/user",
        extra_args=["-u", "admin:definitely-wrong"],
        timeout=TIMEOUT,
    )
    assert status == 401, f"Grafana accepts a wrong password (HTTP {status})"

    if "homepage" in running_containers:
        assert wait_for_homepage_ready(), "homepage API did not respond"
        failures = homepage_widget_failures(only_services={"grafana"})
        assert not failures, (
            "Homepage Grafana widget broken after rotation:\n" + "\n".join(failures)
        )


def test_rotate_calibreweb_password(running_containers):
    """Rotating the Calibre-Web password updates app.db and Homepage."""
    skip_if_not_running("calibre-web", running_containers)

    result = _run_script("rotate-passwords.sh", "calibreweb")
    assert result.returncode == 0, (
        f"rotate-passwords.sh calibreweb exited {result.returncode}:\n{result.stderr}"
    )
    new_password = _summary_password(result.stdout, "calibreweb")
    assert new_password, "Summary table does not contain the new calibreweb password"

    secrets = (REPO_ROOT / "configs/homepage/.env.secrets").read_text()
    assert f"HOMEPAGE_VAR_CALIBREWEB_PASS={new_password}" in secrets, (
        "Homepage secrets not updated with the new calibre-web password"
    )

    assert wait_for_healthy("calibre-web"), "calibre-web unhealthy after rotation"

    if "homepage" in running_containers:
        assert wait_for_homepage_ready(), "homepage API did not respond"
        # calibre-web may still be warming up right after its restart; give
        # the widget a few attempts before declaring it broken.
        failures = homepage_widget_failures(only_services={"calibreweb"})
        for _ in range(6):
            if not failures:
                break
            time.sleep(10)
            failures = homepage_widget_failures(only_services={"calibreweb"})
        assert not failures, (
            "Homepage Calibre Web widget broken after rotation:\n" + "\n".join(failures)
        )


def test_rotate_lazylibrarian_password(running_containers):
    """Rotating LazyLibrarian's WebUI password survives its config flush."""
    skip_if_not_running("lazylibrarian", running_containers)

    result = _run_script("rotate-passwords.sh", "lazylibrarian")
    assert result.returncode == 0, (
        f"rotate-passwords.sh lazylibrarian exited {result.returncode}:\n{result.stderr}"
    )
    new_password = _summary_password(result.stdout, "lazylibrarian")
    assert new_password, "Summary table does not contain the new password"

    ini = (REPO_ROOT / "configs/lazylibrarian/config/config.ini").read_text()
    assert f"http_pass = {new_password}" in ini, (
        "LazyLibrarian config.ini does not hold the new password (config flush clobbered it?)"
    )


def test_rotate_mylar_password(running_containers):
    """Rotating Mylar's WebUI password survives its config flush."""
    skip_if_not_running("mylar", running_containers)

    result = _run_script("rotate-passwords.sh", "mylar")
    assert result.returncode == 0, (
        f"rotate-passwords.sh mylar exited {result.returncode}:\n{result.stderr}"
    )
    new_password = _summary_password(result.stdout, "mylar")
    assert new_password, "Summary table does not contain the new password"

    ini = (REPO_ROOT / "configs/mylar/config/mylar/config.ini").read_text()
    assert f"http_password = {new_password}" in ini, (
        "Mylar config.ini does not hold the new password (config flush clobbered it?)"
    )


def test_rotate_nzbhydra2_password(running_containers):
    """Rotating NZBHydra2's password writes a bcrypt hash the app accepts."""
    skip_if_not_running("nzbhydra2", running_containers)

    result = _run_script("rotate-passwords.sh", "nzbhydra2")
    assert result.returncode == 0, (
        f"rotate-passwords.sh nzbhydra2 exited {result.returncode}:\n{result.stderr}"
    )
    new_password = _summary_password(result.stdout, "nzbhydra2")
    assert new_password, "Summary table does not contain the new password"

    assert wait_for_healthy("nzbhydra2"), "nzbhydra2 unhealthy after rotation"

    # Form login: success redirects into the app, failure back to /login?error.
    # -D - includes the response headers (with Location) in the body.
    port = int(ENV.get("NZBHYDRA2_HTTPS_PORT", "5077"))
    status, body = container_http(
        "nzbhydra2",
        f"https://127.0.0.1:{port}/nzbhydra2/login",
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=f"username=nzbhydra2&password={new_password}",
        extra_args=["-D", "-"],
        timeout=TIMEOUT,
    )
    assert status == 302, f"Unexpected login response (HTTP {status})"
    assert "login?error" not in body, "NZBHydra2 rejected the new password"
