import configparser
import os
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import docker
import pytest
import yaml
from dotenv import dotenv_values

REPO_ROOT = Path(__file__).parent.parent
ENV = dotenv_values(REPO_ROOT / ".env")


def read_secret(owner: str, name: str):
    """Read a value delivered to containers via compose `secrets:`.

    These files are written without a trailing newline, but strip anyway so a
    hand-edited file does not silently produce a credential with \\n appended.
    """
    path = REPO_ROOT / "configs" / owner / "secrets" / name
    return path.read_text().strip() if path.exists() else None


# Service registry — each entry drives parametrize across all test layers.
# api_key_source:
# ("xml", rel_path, tag) | ("yaml", rel_path, *keys) |
# ("ini", rel_path, section, key) | None
SERVICES = {
    "sonarr": {
        "profile_var": "SONARR_PROFILE",
        "http_port_var": "SONARR_HTTP_PORT",
        "https_port_var": "SONARR_HTTPS_PORT",
        "proxy_path": "/sonarr",
        "api_health_path": "/sonarr/api/v3/health",
        "api_key_source": ("xml", "configs/sonarr/config/config.xml", "ApiKey"),
        "password_var": "SONARR_PASSWORD",  # pragma: allowlist secret
    },
    "radarr": {
        "profile_var": "RADARR_PROFILE",
        "http_port_var": "RADARR_HTTP_PORT",
        "https_port_var": "RADARR_HTTPS_PORT",
        "proxy_path": "/radarr",
        "api_health_path": "/radarr/api/v3/health",
        "api_key_source": ("xml", "configs/radarr/config/config.xml", "ApiKey"),
        "password_var": "RADARR_PASSWORD",  # pragma: allowlist secret
    },
    "prowlarr": {
        "profile_var": "PROWLARR_PROFILE",
        "http_port_var": "PROWLARR_HTTP_PORT",
        "https_port_var": "PROWLARR_HTTPS_PORT",
        "proxy_path": "/prowlarr",
        "api_health_path": "/prowlarr/api/v1/health",
        "api_key_source": ("xml", "configs/prowlarr/config/config.xml", "ApiKey"),
        "password_var": "PROWLARR_PASSWORD",  # pragma: allowlist secret
    },
    "readarr": {
        "profile_var": "READARR_PROFILE",
        "http_port_var": "READARR_HTTP_PORT",
        "https_port_var": "READARR_HTTPS_PORT",
        "proxy_path": "/readarr",
        "api_health_path": "/readarr/api/v1/health",
        "api_key_source": ("xml", "configs/readarr/config/config.xml", "ApiKey"),
        "password_var": "READARR_PASSWORD",  # pragma: allowlist secret
    },
    "bazarr": {
        "profile_var": "BAZARR_PROFILE",
        "http_port_var": "BAZARR_HTTP_PORT",
        "proxy_path": "/bazarr",
        "api_health_path": "/bazarr/api/system/health",
        "api_key_source": (
            "yaml",
            "configs/bazarr/config/config/config.yaml",
            "auth",
            "apikey",
        ),
        "password_var": "BAZARR_PASSWORD",  # pragma: allowlist secret
    },
    "qbittorrent": {
        "profile_var": "QBITTORRENT_PROFILE",
        "http_port_var": "QBITTORRENT_HTTP_PORT",
        "https_port_var": "QBITTORRENT_HTTPS_PORT",
        "proxy_path": "/qbittorrent",
        "api_health_path": None,  # /api/v2/app/version requires authentication in qBittorrent v5+
        "api_key_source": None,
        "password_var": "QBITTORRENT_PASSWORD",  # pragma: allowlist secret
        "username": "qbittorrent",
    },
    "nzbget": {
        "profile_var": "NZBGET_PROFILE",
        "http_port_var": "NZBGET_HTTP_PORT",
        "https_port_var": "NZBGET_HTTPS_PORT",
        "proxy_path": "/nzbget",
        "api_health_path": None,
        "api_key_source": None,
        "password_var": "NZBGET_PASSWORD",  # pragma: allowlist secret
        "username": "nzbget",
    },
    "sabnzbd": {
        "profile_var": "SABNZBD_PROFILE",
        "http_port_var": "SABNZBD_HTTP_PORT",
        "https_port_var": "SABNZBD_HTTPS_PORT",
        "proxy_path": "/sabnzbd",
        "api_health_path": "/sabnzbd/api",
        "api_key_source": (
            "ini",
            "configs/sabnzbd/config/sabnzbd.ini",
            "misc",
            "api_key",
        ),
        "password_var": "SABNZBD_PASSWORD",  # pragma: allowlist secret
        "username": "sabnzbd",
    },
    "jellyfin": {
        "profile_var": "JELLYFIN_PROFILE",
        "http_port_var": "JELLYFIN_HTTP_PORT",
        "https_port_var": "JELLYFIN_HTTPS_PORT",
        "proxy_path": "/jellyfin",
        "api_health_path": "/health",
        # Jellyfin is not proxied through nginx; use its direct port for API tests
        "api_base_url_override": "http://localhost:{JELLYFIN_HTTP_PORT}",
        "api_key_source": None,
        "password_var": None,
    },
    "flaresolverr": {
        "profile_var": "FLARESOLVERR_PROFILE",
        "http_port_var": "FLARESOLVERR_HTTP_PORT",
        "proxy_path": "/flaresolverr",
        # nginx strips /flaresolverr/ prefix (trailing slash on proxy_pass), so / reaches the root
        "api_health_path": "/flaresolverr/",
        "api_key_source": None,
        "password_var": None,
    },
    "lidarr": {
        "profile_var": "LIDARR_PROFILE",
        "http_port_var": "LIDARR_HTTP_PORT",
        "https_port_var": "LIDARR_HTTPS_PORT",
        "proxy_path": "/lidarr",
        "api_health_path": "/lidarr/api/v1/health",
        "api_key_source": ("xml", "configs/lidarr/config/config.xml", "ApiKey"),
        "password_var": "LIDARR_PASSWORD",  # pragma: allowlist secret
    },
    "whisparr": {
        "profile_var": "WHISPARR_PROFILE",
        "http_port_var": "WHISPARR_HTTP_PORT",
        "https_port_var": "WHISPARR_HTTPS_PORT",
        "proxy_path": "/whisparr",
        "api_health_path": "/whisparr/api/v3/health",
        "api_key_source": ("xml", "configs/whisparr/config/config.xml", "ApiKey"),
        "password_var": "WHISPARR_PASSWORD",  # pragma: allowlist secret
    },
    "recyclarr": {
        "profile_var": "RECYCLARR_PROFILE",
        "api_health_path": None,
        "api_key_source": None,
        "password_var": None,
    },
    # Observability stack
    "grafana": {
        "profile_var": "GRAFANA_PROFILE",
        "proxy_path": "/admin/grafana",
        "api_health_path": "/admin/grafana/api/health",
        "api_key_source": None,
        "password_var": None,
    },
    "prometheus": {
        "profile_var": "PROMETHEUS_PROFILE",
        "proxy_path": "/admin/prometheus",
        "api_health_path": "/admin/prometheus/api/v1/query?query=up",
        "api_key_source": None,
        "password_var": None,
    },
    "node_exporter": {
        "profile_var": "NODE_EXPORTER_PROFILE",
        "proxy_path": "/admin/node_exporter",
        "api_health_path": "/admin/node_exporter/metrics",
        "api_key_source": None,
        "password_var": None,
    },
    "podman_exporter": {
        "profile_var": "PODMAN_EXPORTER_PROFILE",
        "api_health_path": None,
        "api_key_source": None,
        "password_var": None,
    },
    "qbittorrent_exporter": {
        "profile_var": "QBITTORRENT_EXPORTER_PROFILE",
        "api_health_path": None,
        "api_key_source": None,
        "password_var": None,
    },
    "sabnzbd_exporter": {
        "profile_var": "SABNZBD_EXPORTER_PROFILE",
        "api_health_path": None,
        "api_key_source": None,
        "password_var": None,
    },
}

# Services that run in the Gluetun network namespace by default.
VPN_NETWORKED = {
    "qbittorrent",
    "nzbget",
    "sabnzbd",
}


def env(key: str, default: str = "") -> str:
    return ENV.get(key, default) or default


def is_enabled(service_name: str) -> bool:
    cfg = SERVICES.get(service_name, {})
    pvar = cfg.get("profile_var")
    return env(pvar, "disabled").lower() == "enabled"


def enabled_services():
    return [name for name in SERVICES if is_enabled(name)]


def port(service_name: str, kind: str = "http") -> int:
    key = "http_port_var" if kind == "http" else "https_port_var"
    var = SERVICES[service_name].get(key)
    return int(env(var, "0")) if var else 0


def base_url(https: bool = True) -> str:
    domain = env("DOMAIN", "localhost")
    scheme = "https" if https else "http"
    # `make bootstrap`'s port prompt (see the Makefile) offers standard
    # 80/443 or alternates when those are already taken; a non-interactive
    # bootstrap (no TTY for the prompt) picks the alternates. Omitting the
    # port here always assumed 443/80, so every test built on this silently
    # broke with "Connection refused" against any bootstrap that didn't end
    # up on the standard ports, confirmed live: NGINX_HTTPS_PORT=8443 here,
    # not 443, and every base_url()-based test failed the same way.
    nginx_port = int(env("NGINX_HTTPS_PORT" if https else "NGINX_HTTP_PORT", "0"))
    default_port = 443 if https else 80
    if nginx_port and nginx_port != default_port:
        return f"{scheme}://{domain}:{nginx_port}"
    return f"{scheme}://{domain}"


def service_base_url(service_name: str) -> str:
    """Return the base URL for a service's API calls.

    Services that are not proxied through nginx (e.g. jellyfin) specify an
    api_base_url_override that uses their direct port. Port variable names in
    the override are resolved from ENV.
    """
    override = SERVICES[service_name].get("api_base_url_override")
    if override:
        # Resolve {VAR_NAME} placeholders from ENV
        import re

        def _resolve(m):
            return env(m.group(1), m.group(1))

        return re.sub(r"\{([A-Z0-9_]+)\}", _resolve, override)
    return base_url(https=True)


def read_api_key(service_name: str):
    src = SERVICES[service_name].get("api_key_source")
    if src is None:
        return None
    kind = src[0]
    if kind == "xml":
        _, rel_path, tag = src
        path = REPO_ROOT / rel_path
        if not path.exists():
            return None
        tree = ET.parse(path)
        elem = tree.find(tag)
        return elem.text if elem is not None else None
    if kind == "yaml":
        rel_path = src[1]
        keys = src[2:]
        path = REPO_ROOT / rel_path
        if not path.exists():
            return None
        with open(path) as f:
            data = yaml.safe_load(f)
        for k in keys:
            if not isinstance(data, dict):
                return None
            data = data.get(k)
        return data if isinstance(data, str) else None
    if kind == "ini":
        _, rel_path, section, key = src
        path = REPO_ROOT / rel_path
        if not path.exists():
            return None
        if rel_path.endswith("sabnzbd.ini"):
            for line in path.read_text().splitlines():
                if line.strip().startswith(f"{key} ="):
                    return line.split("=", 1)[1].strip()
        parser = configparser.ConfigParser()
        parser.read(path)
        return parser.get(section, key, fallback=None)
    return None


@pytest.fixture(scope="session")
def docker_client():
    uid = os.getuid()
    if shutil.which("podman"):
        sock = f"unix:///run/user/{uid}/podman/podman.sock"
        return docker.DockerClient(base_url=sock)
    return docker.from_env()


@pytest.fixture(scope="session")
def running_containers(docker_client):
    try:
        return {c.name: c for c in docker_client.containers.list()}
    except Exception:
        return {}


def container_running(name: str, running_containers: dict) -> bool:
    return name in running_containers


def skip_if_not_running(name: str, running_containers: dict):
    if not container_running(name, running_containers):
        pytest.skip(f"container '{name}' is not running")


def fresh_container(docker_client, name: str):
    """Re-fetch a container by name instead of reusing a cached object.

    The session-scoped `running_containers` fixture snapshots container
    objects once. If an earlier test in the same run stops/recreates a
    container (rotation, rinse-and-repeat), that container gets a new ID and
    the cached object's exec_run() calls 404 against the old one.
    """
    return docker_client.containers.get(name)


def skip_if_not_running_fresh(docker_client, name: str, timeout: int = 60):
    """Like skip_if_not_running, but polls live instead of trusting the
    session-scoped snapshot.

    `running_containers` is captured once per pytest invocation (one of the
    several separate processes `make test` runs), at whichever moment the
    first test that needs it runs. A container with unusually slow or
    variable startup can still be short of "running" at that instant and
    fully up moments later, silently skipping every test gated on it for
    the rest of that invocation. Confirmed live: Calibre (README's Known
    Issues #6 documents 90s-300s+ starts, sometimes cycling through several
    s6-triggered relaunches) skipped its own password rotation test in
    every run this session even though the rotation itself, once it
    actually gets to run, already tolerates exactly this slowness with its
    own 600s login retry.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if docker_client.containers.get(name).status == "running":
                return
        except docker.errors.NotFound:
            pass
        time.sleep(5)
    pytest.skip(f"container '{name}' is not running")


def skip_if_disabled(name: str):
    if not is_enabled(name):
        pytest.skip(f"service '{name}' profile is disabled")


# ---------------------------------------------------------------------------
# In-container HTTP helpers
#
# App ports are not published to the host (access goes through nginx only), so
# API calls in tests run curl inside the target container against its own
# loopback address, exactly like the rotation scripts do.
# ---------------------------------------------------------------------------


def container_http(
    container: str,
    url: str,
    *,
    headers: dict | None = None,
    method: str | None = None,
    data: str | None = None,
    extra_args: list | None = None,
    timeout: int = 30,
) -> tuple[int, str]:
    """Run curl inside a container; return (status_code, body)."""
    cmd = [
        "podman",
        "exec",
        "-i",
        container,
        "curl",
        "-sk",
        "--max-time",
        str(timeout),
        "-w",
        "\n%{http_code}",
    ]
    if method:
        cmd += ["-X", method]
    for key, value in (headers or {}).items():
        cmd += ["-H", f"{key}: {value}"]
    if data is not None:
        cmd += ["-d", "@-"]
    cmd += extra_args or []
    cmd.append(url)
    result = subprocess.run(
        cmd, input=data, capture_output=True, text=True, timeout=timeout + 30
    )
    if result.returncode != 0:
        return 0, result.stderr
    body, _, status = result.stdout.rpartition("\n")
    return int(status or 0), body


# ---------------------------------------------------------------------------
# Homepage widget integration checks
#
# Homepage resolves HOMEPAGE_VAR_* credentials only at container creation and
# proxies every widget through /api/services/proxy. Probing that proxy
# exercises the full chain: env loaded, credential valid, upstream reachable.
# One probe per widget type, using an endpoint from the widget's allowlist.
# ---------------------------------------------------------------------------

HOMEPAGE_WIDGET_PROBES = [
    # (service key for profile check, homepage group, service name, endpoint)
    ("sonarr", "Servarr", "Sonarr", "queue"),
    ("radarr", "Servarr", "Radarr", "queue/status"),
    ("lidarr", "Servarr", "Lidarr", "queue/status"),
    ("readarr", "Servarr", "Readarr", "queue/status"),
    ("whisparr", "Servarr", "Whisparr", "queue/status"),
    ("mylar", "Servarr", "Mylar", "series"),
    ("bazarr", "Servarr", "Bazarr", "episodes"),
    ("prowlarr", "Indexers & Downloaders", "Prowlarr", "indexerstats"),
    ("sabnzbd", "Indexers & Downloaders", "SABnzbd", "queue"),
    ("qbittorrent", "Indexers & Downloaders", "qBittorrent", "torrents"),
    ("jellyfin", "Media & Library", "Jellyfin", "Sessions"),
    ("audiobookshelf", "Media & Library", "Audiobookshelf", "libraries"),
    ("calibreweb", "Media & Library", "Calibre Web", "stats"),
    ("grafana", "Observability", "Grafana", "stats"),
    ("prometheus", "Observability", "Prometheus", "targets"),
]


def homepage_http(url: str, timeout: int = 30) -> tuple[int, str]:
    """Fetch a URL from inside the homepage container (it only ships wget)."""
    script = (
        f'code=$(wget -q -O /tmp/homepage_probe -S "{url}" 2>&1 '
        "| grep -m1 \"HTTP/\" | awk '{print $2}'); "
        'echo "$code"; cat /tmp/homepage_probe 2>/dev/null'
    )
    result = subprocess.run(  # nosec B607 - podman is a trusted, fixed CLI in this stack
        ["podman", "exec", "homepage", "sh", "-c", script],
        capture_output=True,
        text=True,
        timeout=timeout + 30,
    )
    first, _, rest = result.stdout.partition("\n")
    try:
        return int(first.strip()), rest
    except ValueError:
        return 0, result.stdout


def homepage_widget_failures(only_services: set | None = None) -> list[str]:
    """Probe homepage widget proxies; return a list of failure descriptions."""
    from urllib.parse import quote

    failures = []
    for svc, group, service, endpoint in HOMEPAGE_WIDGET_PROBES:
        if only_services is not None and svc not in only_services:
            continue
        if svc in SERVICES and not is_enabled(svc):
            continue
        url = (
            "http://127.0.0.1:3000/api/services/proxy"
            f"?group={quote(group)}&service={quote(service)}"
            f"&endpoint={quote(endpoint, safe='')}"
        )
        status, body = homepage_http(url)
        if status != 200:
            failures.append(f"{service} ({endpoint}): HTTP {status} {body[:100]}")
        elif body.lstrip().startswith('{"error"'):
            # Homepage wraps upstream failures (bad credentials, unparsable
            # responses) in a 200 with an error envelope.
            failures.append(f"{service} ({endpoint}): widget error {body[:100]}")
    return failures


def recreate_container(name: str, timeout: int = 180):
    """Force-recreate a compose service container so it reloads env files."""
    subprocess.run(  # nosec B607 - podman-compose is a trusted, fixed CLI in this stack
        [
            "podman-compose",
            "--file",
            "docker-compose.yml",
            "--profile",
            "enabled",
            "up",
            "-d",
            "--force-recreate",
            name,
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        timeout=timeout,
    )


def wait_for_homepage_ready(timeout: int = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, _ = homepage_http("http://127.0.0.1:3000/api/healthcheck")
        if status == 200:
            return True
        time.sleep(3)
    return False


def restart_container(name: str, retries: int = 6, delay: int = 5):
    """Restart a container, retrying on podman's transient state race.

    Parallel test workers can each restart a shared container (e.g. homepage)
    around the same time; podman refuses a restart while another one is still
    mid-transition ("container state improper") instead of queuing it, so a
    single attempt is not reliable under xdist.
    """
    last_error = None
    for _ in range(retries):
        try:
            subprocess.run(  # nosec B607 - podman is a trusted, fixed CLI in this stack
                ["podman", "restart", name], check=True, capture_output=True
            )
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            time.sleep(delay)
    raise last_error


def wait_for_healthy(container: str, timeout: int = 120) -> bool:
    """Poll podman health status until healthy or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = subprocess.run(  # nosec B607 - podman is a trusted, fixed CLI in this stack
            [
                "podman",
                "inspect",
                container,
                "--format",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
            ],
            capture_output=True,
            text=True,
        )
        status = result.stdout.strip()
        if status in ("healthy", "running"):
            return True
        time.sleep(3)
    return False
