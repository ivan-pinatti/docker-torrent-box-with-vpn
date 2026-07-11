"""Smoke tests for the standalone maintenance scripts in scripts/.

These tests never mutate live stack state. Filesystem scenarios run against
temporary directories, permissions.py runs in dry-run mode, the Readarr
profile script runs against a throwaway copy of the database, and the
korsync/exporter checks are read-only probes that skip when the container is
not running.

Run explicitly with:
    pytest -m scripts tests/test_scripts.py
"""

import os
import sqlite3
import subprocess

import pytest

from conftest import REPO_ROOT

pytestmark = pytest.mark.scripts

SCRIPTS = REPO_ROOT / "scripts"
READARR_DB = REPO_ROOT / "configs/readarr/config/readarr.db"


def _skip_unless_running(container: str) -> None:
    result = subprocess.run(
        ["podman", "ps", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0 or container not in result.stdout.split():
        pytest.skip(f"container '{container}' is not running")


def _run(cmd, *, env=None, cwd=REPO_ROOT, stdin=subprocess.DEVNULL):
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=merged_env,
        stdin=stdin,
        capture_output=True,
        text=True,
        timeout=300,
    )


# ---------------------------------------------------------------------------
# disk-status.sh
# ---------------------------------------------------------------------------


def _disk_status(tmp_path, warn_gb: str, crit_gb: str) -> subprocess.CompletedProcess:
    for name in ("torrents", "usenet", "logs", "cache", "storage"):
        (tmp_path / name).mkdir(exist_ok=True)
    env = {
        "TORRENTS_FOLDER": str(tmp_path / "torrents"),
        "USENET_FOLDER": str(tmp_path / "usenet"),
        "LOGS_FOLDER": str(tmp_path / "logs"),
        "CACHE_FOLDER": str(tmp_path / "cache"),
        "STORAGE_FOLDER": str(tmp_path / "storage"),
        "DOWNLOADS_WARN_GB": warn_gb,
        "DOWNLOADS_CRIT_GB": crit_gb,
    }
    return _run([str(SCRIPTS / "disk-status.sh")], env=env)


def test_disk_status_ok(tmp_path):
    result = _disk_status(tmp_path, warn_gb="1", crit_gb="2")
    assert result.returncode == 0, result.stderr
    assert "OK: downloads are 0G" in result.stdout


def test_disk_status_warning(tmp_path):
    result = _disk_status(tmp_path, warn_gb="0", crit_gb="9999")
    assert result.returncode == 0, result.stderr
    assert "WARNING: downloads are 0G" in result.stdout


def test_disk_status_critical(tmp_path):
    result = _disk_status(tmp_path, warn_gb="0", crit_gb="0")
    assert result.returncode == 0, result.stderr
    assert "CRITICAL: downloads are 0G" in result.stdout


def test_disk_status_reports_missing_paths(tmp_path):
    env = {
        "TORRENTS_FOLDER": str(tmp_path / "does-not-exist"),
        "USENET_FOLDER": str(tmp_path / "also-missing"),
        "LOGS_FOLDER": str(tmp_path / "missing-too"),
        "CACHE_FOLDER": str(tmp_path / "nope"),
        "STORAGE_FOLDER": str(tmp_path / "still-nope"),
        "DOWNLOADS_WARN_GB": "1",
        "DOWNLOADS_CRIT_GB": "2",
    }
    result = _run([str(SCRIPTS / "disk-status.sh")], env=env)
    assert result.returncode == 0, result.stderr
    assert "missing" in result.stdout


# ---------------------------------------------------------------------------
# seed-secrets.sh
# ---------------------------------------------------------------------------


def test_seed_secrets_requires_config_dir_argument():
    result = _run([str(SCRIPTS / "seed-secrets.sh")])
    assert result.returncode == 1
    assert "Usage" in result.stderr


def test_seed_secrets_noop_without_example(tmp_path):
    result = _run([str(SCRIPTS / "seed-secrets.sh"), str(tmp_path)])
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / ".env.secrets").exists()


def test_seed_secrets_seeds_from_example(tmp_path):
    (tmp_path / ".env.secrets.example").write_text("TOKEN=changeme\n")
    result = _run([str(SCRIPTS / "seed-secrets.sh"), str(tmp_path)])
    assert result.returncode == 0, result.stderr
    assert (tmp_path / ".env.secrets").read_text() == "TOKEN=changeme\n"
    assert "Seeded" in result.stdout


def test_seed_secrets_keeps_existing_when_not_a_tty(tmp_path):
    (tmp_path / ".env.secrets.example").write_text("TOKEN=changeme\n")
    (tmp_path / ".env.secrets").write_text("TOKEN=real-value\n")
    result = _run([str(SCRIPTS / "seed-secrets.sh"), str(tmp_path)])
    assert result.returncode == 0, result.stderr
    assert (tmp_path / ".env.secrets").read_text() == "TOKEN=real-value\n"


# ---------------------------------------------------------------------------
# permissions.py
# ---------------------------------------------------------------------------


def test_permissions_dry_run_prints_commands_only(tmp_path):
    marker = tmp_path / "untouched"
    marker.write_text("before\n")
    result = _run([str(SCRIPTS / "permissions.py"), "dry-run", "--recursive"])
    assert result.returncode == 0, result.stderr
    assert "chown" in result.stdout
    assert "chmod" in result.stdout
    assert "setfacl" in result.stdout
    assert marker.read_text() == "before\n"


# ---------------------------------------------------------------------------
# readarr-add-comic-profile.py
# ---------------------------------------------------------------------------


def test_readarr_comic_profile_is_idempotent(tmp_path):
    if not READARR_DB.exists():
        pytest.skip("readarr database not present")
    db_copy = tmp_path / "readarr.db"
    source = sqlite3.connect(f"file:{READARR_DB}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(db_copy)
        with target:
            source.backup(target)
        target.close()
    finally:
        source.close()

    env = {"READARR_DB": str(db_copy)}
    script = str(SCRIPTS / "readarr-add-comic-profile.py")

    first = _run(["python3", script], env=env)
    assert first.returncode == 0, first.stderr

    second = _run(["python3", script], env=env)
    assert second.returncode == 0, second.stderr
    assert "already exists" in second.stdout

    con = sqlite3.connect(db_copy)
    try:
        profiles = con.execute(
            "SELECT COUNT(*) FROM QualityProfiles WHERE Name = 'Comic'"
        ).fetchone()[0]
        formats = con.execute(
            "SELECT COUNT(*) FROM CustomFormats WHERE Name IN ('CBZ', 'CBR')"
        ).fetchone()[0]
    finally:
        con.close()
    assert profiles == 1
    assert formats == 2


def test_readarr_comic_profile_fails_cleanly_without_db(tmp_path):
    env = {"READARR_DB": str(tmp_path / "missing.db")}
    result = _run(["python3", str(SCRIPTS / "readarr-add-comic-profile.py")], env=env)
    assert result.returncode != 0
    assert "Database not found" in result.stderr


# ---------------------------------------------------------------------------
# korsync-users.sh (read-only against the live container)
# ---------------------------------------------------------------------------


def test_korsync_users_usage_without_arguments():
    result = _run([str(SCRIPTS / "korsync-users.sh")])
    assert result.returncode == 1
    assert "Usage" in result.stdout


def test_korsync_users_list():
    _skip_unless_running("korsync")
    result = _run([str(SCRIPTS / "korsync-users.sh"), "list"])
    assert result.returncode == 0, result.stderr
    assert "Username" in result.stdout or "no users" in result.stdout


# ---------------------------------------------------------------------------
# podman-limits-exporter.py (read-only probe of the live container)
# ---------------------------------------------------------------------------


def test_podman_limits_exporter_metrics():
    _skip_unless_running("podman_limits_exporter")
    result = _run(
        [
            "podman",
            "exec",
            "podman_limits_exporter",
            "wget",
            "-q",
            "-O",
            "-",
            "http://127.0.0.1:9889/metrics",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert "podman_container_cpu_limit_vcpus" in result.stdout
    assert "podman_container_pids_limit" in result.stdout


# ---------------------------------------------------------------------------
# prune-nginx-cache.sh (abort path only; never deletes anything)
# ---------------------------------------------------------------------------


def test_prune_nginx_cache_aborts_without_confirmation(tmp_path):
    cache_dir = tmp_path / "nginx"
    cache_dir.mkdir()
    sentinel = cache_dir / "cached-object"
    sentinel.write_text("cached\n")
    env = {"CACHE_FOLDER": str(tmp_path)}
    result = subprocess.run(
        [str(SCRIPTS / "prune-nginx-cache.sh")],
        cwd=REPO_ROOT,
        env={**os.environ, **env},
        input="n\n",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "Aborted" in result.stdout
    assert sentinel.exists()


def test_prune_nginx_cache_noop_without_cache_dir(tmp_path):
    env = {"CACHE_FOLDER": str(tmp_path / "empty")}
    result = _run([str(SCRIPTS / "prune-nginx-cache.sh")], env=env)
    assert result.returncode == 0, result.stderr
    assert "No nginx cache directory" in result.stdout
