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


def _run_script(
    script: str, target: str, timeout: int = 600
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(SCRIPTS / script), target],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
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
    subprocess.run(  # nosec B607 - podman is a trusted, fixed CLI in this stack
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
    jar = "/tmp/qbt_test_cookies.txt"  # nosec B108 - path is inside the container, not the host
    login = (
        f"curl -sk -c {jar} -d 'username=qbittorrent&password={current_password}' "
        f"https://{QBT_HOST}:{port}/api/v2/auth/login"
    )
    payload = json.dumps({"web_ui_password": new_password})
    set_pref = (
        f"curl -sk -b {jar} --data-urlencode 'json={payload}' "
        f"https://{QBT_HOST}:{port}/api/v2/app/setPreferences"
    )
    subprocess.run(  # nosec B607 - podman is a trusted, fixed CLI in this stack
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
    """Extract the plaintext new password for a service from the summary table.

    Table rows are: service, user, new password.
    """
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == service:
            return parts[2]
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


def test_rotate_grafana_password_starts_stopped_container(running_containers):
    """Rotating Grafana's password auto-starts the container if it's stopped.

    Grafana's rotation logs into its own live API rather than stopping the
    container to edit a file, so the script must bring it up first (and wait
    for it to report healthy) instead of failing with a raw podman exec
    error against a non-running container.
    """
    skip_if_not_running("grafana", running_containers)

    subprocess.run(["podman", "stop", "grafana"], check=True, capture_output=True)  # nosec B607
    try:
        result = _run_script("rotate-passwords.sh", "grafana")
        assert result.returncode == 0, (
            f"rotate-passwords.sh grafana exited {result.returncode}:\n{result.stderr}"
        )
        assert "Not running; starting it" in result.stdout, (
            "rotate-passwords.sh did not report starting the stopped container"
        )
        new_password = _summary_password(result.stdout, "grafana")
        assert new_password, "Summary table does not contain the new grafana password"

        status, _ = container_http(
            "grafana",
            "http://127.0.0.1:3000/api/user",
            extra_args=["-u", f"admin:{new_password}"],
            timeout=TIMEOUT,
        )
        assert status == 200, (
            f"Grafana does not accept the new password after auto-start (HTTP {status})"
        )
    finally:
        subprocess.run(["podman", "start", "grafana"], check=True, capture_output=True)  # nosec B607


def test_rotate_calibreweb_password(running_containers):
    """Rotating the Calibre-Web password updates app.db and Homepage."""
    skip_if_not_running("calibre-web", running_containers)

    result = _run_script("rotate-passwords.sh", "calibre-web")
    assert result.returncode == 0, (
        f"rotate-passwords.sh calibre-web exited {result.returncode}:\n{result.stderr}"
    )
    new_password = _summary_password(result.stdout, "calibre-web")
    assert new_password, "Summary table does not contain the new calibre-web password"

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


def test_rotate_calibre_password(running_containers):
    """Rotating the Calibre content server password updates the userdb and LazyLibrarian."""
    if ENV.get("CALIBRE_PROFILE", "disabled").lower() != "enabled":
        pytest.skip("calibre profile is disabled")
    skip_if_not_running("calibre", running_containers)

    # rotate-passwords.sh itself retries calibre_login_ok for up to 600s
    # (the desktop GUI can take minutes to boot); give the subprocess margin
    # above that so this test's own timeout never fires first.
    result = _run_script("rotate-passwords.sh", "calibre", timeout=660)
    assert result.returncode == 0, (
        f"rotate-passwords.sh calibre exited {result.returncode}:\n{result.stderr}"
    )
    new_password = _summary_password(result.stdout, "calibre")
    assert new_password, "Summary table does not contain the new calibre password"

    conn = sqlite3.connect(
        str(REPO_ROOT / "configs/calibre/config/.config/calibre/server-users.sqlite")
    )
    cur = conn.cursor()
    cur.execute("SELECT pw FROM users WHERE name = 'calibre'")
    row = cur.fetchone()
    conn.close()
    assert row is not None and row[0] == new_password, (
        "server-users.sqlite does not hold the new calibre password"
    )

    ll_config = REPO_ROOT / "configs/lazylibrarian/config/config.ini"
    if ll_config.exists():
        assert f"calibre_pass = {new_password}" in ll_config.read_text(), (
            "LazyLibrarian config.ini does not hold the new calibre password"
        )

    port = int(ENV.get("CALIBRE_GUI_WEB_HTTP_PORT", "8081"))
    status = 0
    for _ in range(10):
        status, _body = container_http(
            "calibre",
            f"http://127.0.0.1:{port}/ajax/library-info",
            extra_args=["-u", f"calibre:{new_password}"],
            timeout=TIMEOUT,
        )
        if status == 200:
            break
        time.sleep(5)
    assert status == 200, (
        f"Calibre content server does not accept the new password (HTTP {status})"
    )

    # The desktop GUI/noVNC session shares the same password, via basic auth
    # over HTTPS with a self-signed certificate. It only starts once the
    # container's X11 desktop has booted, which can lag well behind the
    # content server; if this proves flaky, see the recovery command in
    # docs/ROTATION.md for the known GUI single-instance wedge.
    gui_port = int(ENV.get("CALIBRE_DESKTOP_HTTPS_PORT", "8181"))
    gui_status = 0
    for _ in range(10):
        gui_status, _body = container_http(
            "calibre",
            f"https://127.0.0.1:{gui_port}/",
            extra_args=["-k", "-u", f"calibre:{new_password}"],
            timeout=TIMEOUT,
        )
        if gui_status == 200:
            break
        time.sleep(5)
    assert gui_status == 200, (
        f"Calibre desktop GUI does not accept the new password (HTTP {gui_status})"
    )


def test_rotate_jdownloader2_password(running_containers):
    """Rotating jDownloader2's web auth password is accepted by its login flow."""
    if ENV.get("JDOWNLOADER2_PROFILE", "disabled").lower() != "enabled":
        pytest.skip("jdownloader2 profile is disabled")
    skip_if_not_running("jdownloader2", running_containers)

    result = _run_script("rotate-passwords.sh", "jdownloader2")
    assert result.returncode == 0, (
        f"rotate-passwords.sh jdownloader2 exited {result.returncode}:\n{result.stderr}"
    )
    new_password = _summary_password(result.stdout, "jdownloader2")
    assert new_password, "Summary table does not contain the new jdownloader2 password"

    secrets = REPO_ROOT / "configs/jdownloader2/.env.secrets"
    assert f"WEB_AUTHENTICATION_PASSWORD={new_password}" in secrets.read_text(), (
        "jdownloader2 .env.secrets was not updated with the new password"
    )

    port = int(ENV.get("JDOWNLOADER2_HTTP_PORT", "5800"))
    login_sh = (
        "jar=$(mktemp); "
        f'curl -sk -c "$jar" -o /dev/null https://127.0.0.1:{port}/; '
        f'curl -sk -b "$jar" -c "$jar" -o /dev/null '
        f"-d 'username=jdownloader2&password={new_password}' "
        f"https://127.0.0.1:{port}/login/login; "
        f'code=$(curl -sk -b "$jar" -o /dev/null -w "%{{http_code}}" https://127.0.0.1:{port}/); '
        'rm -f "$jar"; echo "$code"'
    )
    code = None
    for _ in range(10):
        login = subprocess.run(  # nosec B607 - podman is a trusted, fixed CLI in this stack
            ["podman", "exec", "jdownloader2", "sh", "-c", login_sh],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        code = login.stdout.strip()
        if code == "200":
            break
        time.sleep(5)
    assert code == "200", f"jDownloader2 rejected the new password (HTTP {code})"


def test_rotate_jellyfin_password(running_containers):
    """Rotating the Jellyfin password is accepted by AuthenticateByName."""
    if not is_enabled("jellyfin"):
        pytest.skip("jellyfin profile is disabled")
    skip_if_not_running("jellyfin", running_containers)

    result = _run_script("rotate-passwords.sh", "jellyfin")
    assert result.returncode == 0, (
        f"rotate-passwords.sh jellyfin exited {result.returncode}:\n{result.stderr}"
    )
    new_password = _summary_password(result.stdout, "jellyfin")
    assert new_password, "Summary table does not contain the new jellyfin password"

    port = int(ENV.get("JELLYFIN_HTTP_PORT", "8096"))
    auth_header = (
        'Authorization: MediaBrowser Client="pytest", Device="pytest", '
        'DeviceId="pytest", Version="1.0"'
    )
    status, _body = container_http(
        "jellyfin",
        f"http://127.0.0.1:{port}/jellyfin/Users/AuthenticateByName",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"Username": "jellyfin", "Pw": new_password}),
        extra_args=["-H", auth_header],
        timeout=TIMEOUT,
    )
    assert status == 200, f"Jellyfin rejected the new password (HTTP {status})"


def _abs_password_hash() -> str:
    """Return the bcrypt hash stored for the root user in absdatabase.sqlite."""
    conn = sqlite3.connect(
        str(REPO_ROOT / "configs/audiobookshelf/config/absdatabase.sqlite")
    )
    cur = conn.cursor()
    cur.execute("SELECT pash FROM users WHERE username = 'root'")
    row = cur.fetchone()
    conn.close()
    assert row is not None, "No root user in absdatabase.sqlite"
    return row[0]


def test_rotate_audiobookshelf_password(running_containers):
    """Rotating the Audiobookshelf password writes a bcrypt hash the app accepts."""
    # Audiobookshelf has no SERVICES entry in conftest, so check its compose
    # profile flag directly instead of via is_enabled().
    if ENV.get("AUDIOBOOKSHELF_PROFILE", "disabled").lower() != "enabled":
        pytest.skip("audiobookshelf profile is disabled")
    skip_if_not_running("audiobookshelf", running_containers)

    old_hash = _abs_password_hash()

    result = _run_script("rotate-passwords.sh", "audiobookshelf")
    assert result.returncode == 0, (
        f"rotate-passwords.sh audiobookshelf exited {result.returncode}:\n{result.stderr}"
    )
    new_password = _summary_password(result.stdout, "audiobookshelf")
    assert new_password, "Summary table does not contain the new password"

    new_hash = _abs_password_hash()
    assert new_hash != old_hash, "absdatabase.sqlite password hash did not change"

    # The audiobookshelf image ships no curl; log in with node's global fetch
    # inside the container, like the rotation script's own validation does.
    port = int(ENV.get("AUDIOBOOKSHELF_HTTP_PORT", "13378"))
    login_js = (
        "const [port, username, password] = process.argv.slice(1);"
        "fetch(`http://127.0.0.1:${port}/audiobookshelf/login`, {"
        "  method: 'POST',"
        "  headers: { 'Content-Type': 'application/json' },"
        "  body: JSON.stringify({ username, password }),"
        "}).then((res) => process.exit(res.status === 200 ? 0 : 1),"
        "        () => process.exit(1));"
    )
    for _ in range(10):
        login = subprocess.run(  # nosec B607 - podman is a trusted, fixed CLI in this stack
            [
                "podman",
                "exec",
                "audiobookshelf",
                "node",
                "-e",
                login_js,
                str(port),
                "root",
                new_password,
            ],
            capture_output=True,
            timeout=TIMEOUT,
        )
        if login.returncode == 0:
            break
        time.sleep(5)
    assert login.returncode == 0, "Audiobookshelf rejected the new password"


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
