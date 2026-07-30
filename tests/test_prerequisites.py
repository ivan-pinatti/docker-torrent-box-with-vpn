"""Pre-flight checks: verify system requirements before starting the stack."""

import pathlib
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


# --- Repo hygiene: live runtime state must never become committable ---------
#
# configs/*/.gitignore each start with a blanket `*` and then re-include the
# handful of files that belong in git. A stray `!config/<app>.db` negation in
# one of those files silently re-armed every live database for `git add -A`,
# which is how they were committed in the first place. These tests fail if a
# negation like that comes back.

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Ignored live files that need no committed seed, because the app writes them
# itself on first run. Jellyfin's network.xml is then patched in place by
# `make configure_jellyfin_network` and `make generate_certificate`, so a
# checked-in template would only go stale.
APP_GENERATED_NO_SEED = {
    "configs/jellyfin/config/network.xml",
    "configs/jellyfin/config/config/network.xml",
}

RUNTIME_STATE = [
    "configs/bazarr/config/config/config.yaml",
    "configs/bazarr/config/db/bazarr.db",
    "configs/calibre/config/.config/calibre/gui.json",
    "configs/calibre/config/.config/calibre/gui.py.json",
    "configs/calibre/config/.config/calibre/global.py.json",
    "configs/calibre/config/.config/calibre/dynamic.pickle.json",
    "configs/calibre-web/config/app.db",
    "configs/calibre-web/config/client_secrets.json",
    "configs/jellyfin/config/network.xml",
    "configs/jellyfin/config/config/network.xml",
    "configs/jellyfin/config/data/jellyfin.db",
    "configs/korsync/data/koreader-sync.db",
    "configs/lazylibrarian/config/lazylibrarian.db",
    "configs/lidarr/config/lidarr.db",
    "configs/mylar/config/mylar/mylar.db",
    "configs/notifiarr/.env",
    "configs/prowlarr/config/prowlarr.db",
    "configs/qbittorrent/config/qBittorrent/qBittorrent.conf",
    "configs/radarr/config/radarr.db",
    "configs/readarr/config/readarr.db",
    "configs/sabnzbd/config/sabnzbd.ini",
    "configs/sonarr/config/sonarr.db",
    "configs/whisparr/config/whisparr.db",
    "configs/whisparr/config/whisparr2.db",
    "configs/whisparr/config/whisparr3.db",
]


@pytest.mark.parametrize("rel_path", RUNTIME_STATE)
def test_runtime_state_is_gitignored(rel_path):
    """Live databases and app-rewritten configs must be ignored by git.

    --no-index matters: `git check-ignore` stays silent for paths already in
    the index, which would mask a file that is both tracked and ignored.
    """
    result = run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "--no-index", "-q", rel_path]
    )
    assert result.returncode == 0, (
        f"{rel_path} is not gitignored. It holds live state or credentials and "
        f"would be staged by `git add -A`. Check configs/*/.gitignore for a "
        f"`!` negation that re-includes it."
    )


@pytest.mark.parametrize("rel_path", RUNTIME_STATE)
def test_runtime_state_is_not_tracked(rel_path):
    """Nothing in RUNTIME_STATE may be in the index, ignored or not."""
    result = run(["git", "-C", str(REPO_ROOT), "ls-files", "--error-unmatch", rel_path])
    assert result.returncode != 0, (
        f"{rel_path} is tracked in git. Run "
        f"`git rm --cached {rel_path}` (the file stays on disk)."
    )


def test_no_databases_tracked():
    """No SQLite database anywhere in the repo may be tracked."""
    result = run(["git", "-C", str(REPO_ROOT), "ls-files"])
    assert result.returncode == 0
    tracked_dbs = [
        line
        for line in result.stdout.splitlines()
        if line.endswith((".db", ".sqlite", ".sqlite3"))
    ]
    assert not tracked_dbs, f"tracked database files: {tracked_dbs}"


def _seeded_configs() -> list[str]:
    """Live paths that `make bootstrap` seeds via scripts/seed-configs.sh."""
    makefile = (REPO_ROOT / "Makefile").read_text()
    return re.findall(r"seed-configs\.sh (\S+)", makefile)


def test_bootstrap_seeds_something():
    assert _seeded_configs(), "no seed-configs.sh invocations found in the Makefile"


@pytest.mark.parametrize("live_path", _seeded_configs())
def test_seeded_config_has_tracked_example(live_path):
    """Every seeded path needs a committed <path>.example, or bootstrap breaks.

    seed-configs.sh exits non-zero when the .example is missing, so a fresh
    clone would fail at `make bootstrap` rather than at first container start.
    """
    example = f"{live_path}.example"
    assert (REPO_ROOT / example).is_file(), f"{example} does not exist"
    result = run(["git", "-C", str(REPO_ROOT), "ls-files", "--error-unmatch", example])
    assert result.returncode == 0, f"{example} exists but is not tracked by git"


@pytest.mark.parametrize("rel_path", RUNTIME_STATE)
def test_runtime_state_has_seed_when_app_needs_one(rel_path):
    """A live file that is ignored must either be app-generated or have a seed.

    Databases the app creates on first run need no seed. Hand-tuned configs do,
    otherwise untracking them silently drops settings for fresh clones.
    """
    if rel_path.endswith((".db", ".sqlite", ".sqlite3")):
        pytest.skip("app creates its own database on first run")
    if rel_path in APP_GENERATED_NO_SEED:
        pytest.skip("app generates this file; see APP_GENERATED_NO_SEED")
    example = REPO_ROOT / f"{rel_path}.example"
    assert example.is_file(), (
        f"{rel_path} is ignored but has no {example.name} seed, so a fresh "
        f"clone loses its curated settings"
    )
    assert rel_path in _seeded_configs(), (
        f"{rel_path}.example exists but `make bootstrap` never copies it into place"
    )
