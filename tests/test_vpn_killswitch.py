"""VPN kill-switch: verify that VPN-networked containers cannot reach the public
internet when the VPN container is stopped.

These tests are marked @pytest.mark.vpn and @pytest.mark.killswitch.
They are automatically skipped when:
- GLUETUN_PROFILE is not enabled
- The VPN container (VPN_PROVIDER) is not running
- The test VPN-networked container (qbittorrent) is not running

The kill-switch guarantee: qBittorrent runs inside the VPN network namespace
(network_mode: container:${VPN_PROVIDER}). When that container is stopped the
shared network namespace is destroyed, making outbound connections impossible.
"""

import time

import pytest
import urllib3

from conftest import env, skip_if_not_running

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

pytestmark = [pytest.mark.vpn, pytest.mark.killswitch]

VPN_CONTAINER = env("VPN_PROVIDER", "gluetun")
PROBE_CONTAINER = "qbittorrent"
EXTERNAL_IP_URL = "https://checkip.amazonaws.com"
EXTERNAL_IP_FALLBACK = "https://api4.my-ip.io/ip"
CURL_CMD = ["curl", "-s", "--max-time", "5", EXTERNAL_IP_URL]
VPN_HEALTHY_TIMEOUT = 120


def _require_vpn_enabled():
    if env("GLUETUN_PROFILE", "disabled").lower() != "enabled":
        pytest.skip("GLUETUN_PROFILE is not enabled — VPN kill-switch tests skipped")


def _exec_curl(docker_client, container_name: str) -> tuple[int, str]:
    """Run curl inside a container. Returns (exit_code, stdout)."""
    container = docker_client.containers.get(container_name)
    result = container.exec_run(CURL_CMD)
    return result.exit_code, result.output.decode("utf-8", errors="replace").strip()


def _wait_for_healthy(
    docker_client, container_name: str, timeout: int = VPN_HEALTHY_TIMEOUT
):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        c = docker_client.containers.get(container_name)
        health = c.attrs.get("State", {}).get("Health", {}).get("Status")
        if health == "healthy":
            return
        time.sleep(5)
    raise TimeoutError(
        f"Container '{container_name}' did not become healthy within {timeout}s"
    )


def test_vpn_container_is_healthy(running_containers, docker_client):
    """Baseline: Gluetun must be healthy before we test the kill-switch."""
    _require_vpn_enabled()
    skip_if_not_running(VPN_CONTAINER, running_containers)
    container = running_containers[VPN_CONTAINER]
    health = container.attrs.get("State", {}).get("Health", {}).get("Status")
    assert health == "healthy", (
        f"Gluetun container health is '{health}', expected 'healthy'"
    )


def test_vpn_exit_ip_differs_from_lan(running_containers, docker_client):
    """Traffic from VPN-networked containers exits via the VPN, not the host LAN IP."""
    _require_vpn_enabled()
    skip_if_not_running(VPN_CONTAINER, running_containers)
    skip_if_not_running(PROBE_CONTAINER, running_containers)

    lan_ip = env("LAN_IP", "")
    exit_code, output = _exec_curl(docker_client, PROBE_CONTAINER)
    if exit_code != 0:
        pytest.skip(
            f"curl from {PROBE_CONTAINER} failed (exit {exit_code}) — "
            "may indicate kill-switch is already active or no internet access"
        )

    vpn_ip = output.strip()
    assert vpn_ip, "checkip returned empty response"
    if lan_ip:
        assert vpn_ip != lan_ip, (
            f"VPN exit IP {vpn_ip!r} equals LAN IP {lan_ip!r} — traffic is NOT going through VPN"
        )


def test_killswitch_blocks_traffic_when_vpn_stopped(running_containers, docker_client):
    """After stopping Gluetun, VPN-networked containers must not reach the internet."""
    _require_vpn_enabled()
    skip_if_not_running(VPN_CONTAINER, running_containers)
    skip_if_not_running(PROBE_CONTAINER, running_containers)

    vpn_container = docker_client.containers.get(VPN_CONTAINER)

    try:
        vpn_container.stop(timeout=15)

        # Give the network namespace a moment to collapse
        time.sleep(2)

        exit_code, output = _exec_curl(docker_client, PROBE_CONTAINER)
        assert exit_code != 0, (
            f"Kill-switch FAILED: {PROBE_CONTAINER} reached the internet after VPN stopped. "
            f"External IP response: {output!r}"
        )
    finally:
        # Always restore the VPN container — do not leave the stack broken
        vpn_container.start()
        try:
            _wait_for_healthy(docker_client, VPN_CONTAINER)
        except TimeoutError as exc:
            pytest.fail(
                f"Gluetun did not recover after restart: {exc}. "
                "Stack may be in a degraded state — check container logs."
            )


def test_traffic_restored_after_vpn_restart(running_containers, docker_client):
    """After Gluetun recovers, VPN-networked containers can reach the internet again.

    With podman-compose, namespace-sharing containers do not automatically rejoin
    the VPN container's new namespace after a restart. This test explicitly restarts
    the probe container so it joins the new namespace, verifying that the stack can
    recover from a VPN outage with a container restart (the expected operational
    procedure after a VPN recovery event).
    """
    _require_vpn_enabled()
    skip_if_not_running(VPN_CONTAINER, running_containers)
    skip_if_not_running(PROBE_CONTAINER, running_containers)

    vpn = docker_client.containers.get(VPN_CONTAINER)
    health = vpn.attrs.get("State", {}).get("Health", {}).get("Status")
    if health != "healthy":
        pytest.skip("Gluetun is not healthy — cannot test post-recovery connectivity")

    # Restart the probe container so it re-attaches to the VPN container's new namespace.
    probe = docker_client.containers.get(PROBE_CONTAINER)
    probe.restart(timeout=30)
    time.sleep(10)

    # A single attempt right after restart is fragile: routing through a
    # freshly (re)established tunnel needs a moment to settle, more so
    # against a local mock VPN's extra hop (probe -> gluetun -> the mock's
    # own NAT -> the real internet) than a dedicated commercial provider,
    # confirmed live (the exact same curl succeeded immediately when
    # retried by hand seconds after a one-shot failure here).
    exit_code, output = 1, ""
    for attempt in range(6):
        exit_code, output = _exec_curl(docker_client, PROBE_CONTAINER)
        if exit_code == 0 and output.strip():
            break
        if attempt < 5:
            time.sleep(5)
    assert exit_code == 0, (
        f"Traffic not restored after VPN restart + probe container restart: "
        f"curl exited {exit_code}, output={output!r}"
    )
    assert output.strip(), "No IP returned after VPN recovery"
