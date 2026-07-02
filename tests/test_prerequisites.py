"""Pre-flight checks: verify system requirements before starting the stack."""

import platform
import re
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.prerequisites


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=10)


def _version_tuple(version_str: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", version_str)
    return tuple(int(p) for p in parts[:3])


def test_docker_or_podman_available():
    has_docker = shutil.which("docker") is not None
    has_podman = shutil.which("podman") is not None
    assert has_docker or has_podman, "Neither docker nor podman found in PATH"


def test_docker_version():
    runtime = "podman" if shutil.which("podman") else "docker"
    result = run([runtime, "--version"])
    assert result.returncode == 0, f"{runtime} --version failed: {result.stderr}"
    ver = _version_tuple(result.stdout)
    if runtime == "docker":
        assert ver >= (26, 0, 0), f"Docker {ver} < 26.0.0 required"
    else:
        assert ver >= (4, 0, 0), f"Podman {ver} < 4.0.0 required"


def test_compose_available():
    has_docker_compose_plugin = run(["docker", "compose", "version"]).returncode == 0
    has_docker_compose_standalone = shutil.which("docker-compose") is not None
    has_podman_compose = shutil.which("podman-compose") is not None
    assert (
        has_docker_compose_plugin or has_docker_compose_standalone or has_podman_compose
    ), (
        "No Docker Compose found. Install via: apt install docker-compose-plugin "
        "(or podman-compose for Podman)"
    )


def test_container_daemon_running():
    runtime = "podman" if shutil.which("podman") else "docker"
    result = run([runtime, "info"])
    assert result.returncode == 0, (
        f"{runtime} daemon is not running or not accessible: {result.stderr}"
    )


def test_linux_kernel_version():
    release = platform.release()
    major, minor = map(int, release.split(".")[:2])
    assert (major, minor) >= (5, 6), (
        f"Kernel {release} is below 5.6 (required for WireGuard in-tree support)"
    )


def test_wireguard_available():
    """WireGuard must be either loaded (lsmod) or available as a loadable module (modinfo)."""
    in_lsmod = "wireguard" in run(["lsmod"]).stdout
    if in_lsmod:
        return
    # Module built-in to kernel or available but not yet loaded — check with modinfo
    modinfo = run(["modinfo", "wireguard"])
    assert modinfo.returncode == 0, (
        "WireGuard is neither loaded nor available as a kernel module. "
        "Install wireguard or wireguard-dkms, or use a kernel ≥5.6 with CONFIG_WIREGUARD."
    )


def test_make_version():
    result = run(["make", "--version"])
    assert result.returncode == 0, "make not found"
    ver = _version_tuple(result.stdout)
    assert ver >= (4, 0), f"make {ver} < 4.0 required"


def test_yq_version():
    assert shutil.which("yq"), "yq not found in PATH"
    result = run(["yq", "--version"])
    assert result.returncode == 0
    ver = _version_tuple(result.stdout)
    assert ver >= (4, 44), f"yq {ver} < 4.44 required"


def test_xmlstarlet_available():
    assert shutil.which("xmlstarlet"), "xmlstarlet not found in PATH"
    result = run(["xmlstarlet", "--version"])
    assert result.returncode == 0
