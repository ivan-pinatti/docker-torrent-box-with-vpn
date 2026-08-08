"""Mylar to jDownloader2 connectivity: exec into Mylar and hit jDownloader2's own API.

jDownloader2 restricts its REST API and its older /jd namespace to loopback by
default, and the /jd namespace is disabled outright unless the deprecated API
is turned on. Mylar's connection test (and its real link submission) needs
both open. configs/jdownloader2/config/cfg/org.jdownloader.api.RemoteAPIConfig.json.example
is seeded by `make bootstrap` with the values that make this work; this test
exercises the actual failure mode from Mylar's own network vantage point,
not just jDownloader2's config file.
"""

import pytest

from conftest import REPO_ROOT, env, skip_if_not_running

pytestmark = pytest.mark.connectivity


def _jd2_url() -> str | None:
    """Read jd2_url out of Mylar's live config.ini (plain key = value line)."""
    path = REPO_ROOT / "configs" / "mylar" / "config" / "mylar" / "config.ini"
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        if line.strip().startswith("jd2_url ="):
            return line.split("=", 1)[1].strip()
    return None


def _using_mock_vpn() -> bool:
    """True once seed-vpn-mock.sh has pointed gluetun at the local mock endpoint."""
    path = REPO_ROOT / "configs" / "gluetun" / ".env"
    if not path.exists():
        return False
    for line in path.read_text().splitlines():
        if line.strip() == "VPN_SERVICE_PROVIDER=custom":
            return True
    return False


def test_mylar_reaches_jdownloader2_api(docker_client, running_containers):
    """Mylar's own jd2_url must be reachable and answer /jd/version with 200."""
    if env("MYLAR_PROFILE", "disabled").lower() != "enabled" or (
        env("JDOWNLOADER2_PROFILE", "disabled").lower() != "enabled"
    ):
        pytest.skip("mylar or jdownloader2 profile is disabled")
    if _using_mock_vpn():
        # jDownloader2 runs a mandatory self-update dance on its own first
        # boot, before its RemoteAPIConfig.json (and therefore this API)
        # exists at all, and that update needs real internet access. The
        # mock WireGuard endpoint (see docs/VPN_MOCK.md) is a same-host hop
        # purely for exercising gluetun's own connection logic, not a real
        # route out; confirmed live, jDownloader2 gets stuck on its own
        # "No Connection to the Internet" dialog behind it and never
        # finishes booting. Not a bug in the fix this test covers, just an
        # environment this specific app can't function in at all.
        pytest.skip(
            "jDownloader2 can't complete its own first-boot self-update behind the mock VPN"
        )
    skip_if_not_running("mylar", running_containers)
    skip_if_not_running("jdownloader2", running_containers)

    jd2_url = _jd2_url()
    assert jd2_url, "jd2_url is not set in Mylar's config.ini"

    container = docker_client.containers.get("mylar")
    exit_code, output = container.exec_run(
        [
            "curl",
            "-sS",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            f"{jd2_url}/jd/version",
        ],
        stdout=True,
        stderr=True,
        demux=False,
    )
    decoded = output.decode("utf-8", errors="replace") if output else ""

    assert exit_code == 0, (
        f"curl from mylar to {jd2_url}/jd/version failed (exit {exit_code}): {decoded}"
    )
    assert decoded.strip() == "200", (
        f"jd2_url {jd2_url}/jd/version returned HTTP {decoded!r} from mylar's network, "
        "expected 200 (check externinterfacelocalhostonly, deprecatedapienabled, "
        "and deprecatedapilocalhostonly in jDownloader2's RemoteAPIConfig.json)"
    )
