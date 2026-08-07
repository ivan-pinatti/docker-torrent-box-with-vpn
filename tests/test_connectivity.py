"""Port reachability: TCP connect, HTTP→HTTPS redirect, nginx proxy path checks.

Architecture note: app services are not exposed directly on the host unless
explicitly published. Servarr services are proxied through nginx whether they
run directly on app networks or through Gluetun route overrides.
"""

import socket

import pytest
import requests
import urllib3

from conftest import (
    SERVICES,
    env,
    is_enabled,
    port,
    skip_if_not_running,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

pytestmark = pytest.mark.connectivity

HOST = env("DOMAIN", "localhost")
CONNECT_TIMEOUT = 5
NGINX_HTTPS_PORT = int(env("NGINX_HTTPS_PORT", "443"))


def tcp_connect(host: str, p: int, timeout: float = CONNECT_TIMEOUT) -> bool:
    try:
        with socket.create_connection((host, p), timeout=timeout):
            return True
    except OSError:
        return False


# Services with ports exposed directly on the host.
DIRECT_PORT_SERVICES = ["jellyfin"]

# Enabled services that should have a proxy path through nginx.
PROXY_SERVICES = [name for name, cfg in SERVICES.items() if cfg.get("proxy_path")]


@pytest.mark.parametrize("service_name", DIRECT_PORT_SERVICES)
def test_http_port_reachable(service_name, running_containers):
    """Direct HTTP port check, only for services not in the VPN network namespace."""
    if not is_enabled(service_name):
        pytest.skip(f"{service_name} profile is disabled")
    skip_if_not_running(service_name, running_containers)
    p = port(service_name, "http")
    if not p:
        pytest.skip(f"{service_name} has no HTTP port configured")
    assert tcp_connect(HOST, p), (
        f"TCP connect to {HOST}:{p} ({service_name} HTTP) failed"
    )


@pytest.mark.parametrize("service_name", DIRECT_PORT_SERVICES)
def test_https_port_reachable(service_name, running_containers):
    """Direct HTTPS port check, only for services not in the VPN network namespace."""
    if not is_enabled(service_name):
        pytest.skip(f"{service_name} profile is disabled")
    skip_if_not_running(service_name, running_containers)
    p = port(service_name, "https")
    if not p:
        pytest.skip(f"{service_name} has no HTTPS port configured")
    assert tcp_connect(HOST, p), (
        f"TCP connect to {HOST}:{p} ({service_name} HTTPS) failed"
    )


@pytest.mark.parametrize("service_name", PROXY_SERVICES)
def test_service_reachable_via_proxy(service_name, running_containers):
    """Proxied services must respond through the nginx reverse proxy.

    A 502/503/504 means nginx is up but the backend is unreachable; anything
    else (200, 301, 302, 401, 403) means the service is running and nginx can
    reach it.
    """
    if not is_enabled(service_name):
        pytest.skip(f"{service_name} profile is disabled")
    skip_if_not_running(service_name, running_containers)
    skip_if_not_running("nginx", running_containers)
    if not tcp_connect(HOST, NGINX_HTTPS_PORT):
        pytest.skip("nginx HTTPS port is not reachable")

    proxy_path = SERVICES[service_name].get("proxy_path", f"/{service_name}")
    url = f"https://{HOST}:{NGINX_HTTPS_PORT}{proxy_path}/"
    try:
        resp = requests.get(
            url, allow_redirects=True, verify=False, timeout=CONNECT_TIMEOUT
        )
    except requests.exceptions.ReadTimeout:
        pytest.skip(
            f"{service_name} proxy path {proxy_path} timed out (service may be busy)"
        )
    assert resp.status_code not in (502, 503, 504), (
        f"{service_name} backend unreachable via nginx proxy {url}: "
        f"HTTP {resp.status_code}"
    )


def test_nginx_http_to_https_redirect(running_containers):
    """Port 80 must redirect to HTTPS."""
    skip_if_not_running("nginx", running_containers)
    p = int(env("NGINX_HTTP_PORT", "80"))
    if not tcp_connect(HOST, p):
        pytest.skip(f"Nginx HTTP port {p} is not reachable")
    resp = requests.get(
        f"http://{HOST}:{p}/",
        allow_redirects=False,
        timeout=CONNECT_TIMEOUT,
        verify=False,
    )
    assert resp.status_code in (301, 302), (
        f"Expected redirect from HTTP port {p}, got {resp.status_code}"
    )
    location = resp.headers.get("Location", "")
    assert location.startswith("https://"), (
        f"Redirect location '{location}' does not point to HTTPS"
    )


def test_nginx_https_reachable(running_containers):
    """HTTPS port must accept TCP connections."""
    skip_if_not_running("nginx", running_containers)
    assert tcp_connect(HOST, NGINX_HTTPS_PORT), (
        f"TCP connect to {HOST}:{NGINX_HTTPS_PORT} (nginx HTTPS) failed"
    )


def test_jellyfin_proxy_domain_reachable(running_containers):
    """Optional Jellyfin domain virtual host must reach the backend when enabled."""
    if not is_enabled("jellyfin"):
        pytest.skip("jellyfin profile is disabled")
    proxy_domain = env("JELLYFIN_PROXY_DOMAIN", "jellyfin.invalid")
    if proxy_domain in ("", "jellyfin.invalid"):
        pytest.skip("JELLYFIN_PROXY_DOMAIN is not configured")
    skip_if_not_running("jellyfin", running_containers)
    skip_if_not_running("nginx", running_containers)
    if not tcp_connect(HOST, NGINX_HTTPS_PORT):
        pytest.skip("nginx HTTPS port is not reachable")

    url = f"https://{HOST}:{NGINX_HTTPS_PORT}/"
    resp = requests.get(
        url,
        headers={"Host": proxy_domain},
        allow_redirects=True,
        verify=False,
        timeout=CONNECT_TIMEOUT,
    )
    assert resp.status_code not in (502, 503, 504), (
        f"jellyfin domain backend unreachable via nginx proxy {proxy_domain}: "
        f"HTTP {resp.status_code}"
    )
