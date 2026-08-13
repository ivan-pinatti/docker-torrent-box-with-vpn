"""Tests for the symlink provisioning in scripts/permissions.py.

The *arr apps look for MediaCover and Backups inside /config, but those are
bind mounted outside it so the artwork and scheduled backups follow the data
tree onto external storage. Each one is therefore a symlink, and nothing
created them until this: a fresh clone got real directories in configs/
instead, on local disk and excluded from the config backup.

These run against a temporary manifest and temporary directories, never the
live install.

Run explicitly with:
    pytest -m scripts tests/test_permissions_symlinks.py
"""

import importlib.util

import pytest

from conftest import REPO_ROOT

pytestmark = pytest.mark.scripts

MANIFEST = REPO_ROOT / "permissions.yml"


@pytest.fixture
def permissions(monkeypatch, tmp_path):
    """Loads permissions.py with its REPO_ROOT pointed at a temporary tree."""
    spec = importlib.util.spec_from_file_location(
        "permissions_under_test", REPO_ROOT / "scripts/permissions.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    return module


@pytest.fixture
def manifest():
    return {
        "symlinks": [
            {"path": "configs/sonarr/config/MediaCover", "target": "/mediacover"},
            {"path": "configs/sonarr/config/Backups", "target": "/appbackups"},
        ]
    }


def _link(tmp_path, name="MediaCover"):
    return tmp_path / "configs/sonarr/config" / name


def test_creates_missing_symlinks(permissions, manifest, tmp_path):
    permissions.ensure_symlinks(manifest, dry_run=False)
    link = _link(tmp_path)
    assert link.is_symlink()
    assert link.readlink().as_posix() == "/mediacover"
    assert _link(tmp_path, "Backups").readlink().as_posix() == "/appbackups"


def test_is_idempotent(permissions, manifest, tmp_path):
    permissions.ensure_symlinks(manifest, dry_run=False)
    permissions.ensure_symlinks(manifest, dry_run=False)
    assert _link(tmp_path).readlink().as_posix() == "/mediacover"


def test_repoints_a_symlink_aimed_somewhere_else(permissions, manifest, tmp_path):
    link = _link(tmp_path)
    link.parent.mkdir(parents=True)
    link.symlink_to("/somewhere-else")
    permissions.ensure_symlinks(manifest, dry_run=False)
    assert link.readlink().as_posix() == "/mediacover"


def test_replaces_an_empty_directory(permissions, manifest, tmp_path):
    """An app that started once without the link leaves an empty directory."""
    link = _link(tmp_path)
    link.mkdir(parents=True)
    permissions.ensure_symlinks(manifest, dry_run=False)
    assert link.is_symlink()


def test_refuses_to_delete_a_populated_directory(permissions, manifest, tmp_path):
    """This is the pre-migration artwork. Removing it to make room for a link
    would throw away the only copy."""
    link = _link(tmp_path)
    link.mkdir(parents=True)
    (link / "poster.jpg").write_bytes(b"artwork")
    with pytest.raises(SystemExit) as excinfo:
        permissions.ensure_symlinks(manifest, dry_run=False)
    assert "non-empty" in str(excinfo.value)
    assert (link / "poster.jpg").read_bytes() == b"artwork", "artwork was destroyed"


def test_refuses_when_a_file_is_in_the_way(permissions, manifest, tmp_path):
    link = _link(tmp_path)
    link.parent.mkdir(parents=True)
    link.write_text("not a directory")
    with pytest.raises(SystemExit):
        permissions.ensure_symlinks(manifest, dry_run=False)


def test_dry_run_changes_nothing(permissions, manifest, tmp_path, capsys):
    permissions.ensure_symlinks(manifest, dry_run=True)
    assert not _link(tmp_path).exists()
    assert "ln -s" in capsys.readouterr().out


def test_containment_is_checked_on_the_link_not_its_target(permissions, tmp_path):
    """The targets are container paths outside the repository on purpose, so
    resolving the whole path refuses every one of them. Only where the link
    lives has to be contained."""
    manifest = {
        "symlinks": [
            {"path": "configs/sonarr/config/MediaCover", "target": "/mediacover"}
        ]
    }
    permissions.ensure_symlinks(manifest, dry_run=False)
    assert _link(tmp_path).is_symlink()

    outside = {"symlinks": [{"path": "../escape/MediaCover", "target": "/mediacover"}]}
    with pytest.raises(SystemExit) as excinfo:
        permissions.ensure_symlinks(outside, dry_run=False)
    assert "outside repository" in str(excinfo.value)


# ---------------------------------------------------------------------------
# The real manifest
# ---------------------------------------------------------------------------


def test_manifest_declares_every_mounted_cover_and_backup_directory():
    """Every /mediacover and /appbackups bind mount in the compose file needs a
    matching link, or that app writes into configs/ instead."""
    import yaml

    declared = {
        entry["path"]
        for entry in yaml.safe_load(MANIFEST.read_text()).get("symlinks", [])
    }
    compose = (REPO_ROOT / "docker-compose-servarr.yml").read_text()
    expected = set()
    for line in compose.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- ${"):
            continue
        if ":/mediacover" in stripped:
            app = stripped.split("MEDIA_COVERS_FOLDER}/")[1].split(":")[0]
            expected.add(f"configs/{app}/config/MediaCover")
        elif ":/appbackups" in stripped:
            app = stripped.split("APP_BACKUPS_FOLDER}/")[1].split(":")[0]
            expected.add(f"configs/{app}/config/Backups")
    assert expected, "no bind mounts found, the parser is wrong"
    assert expected <= declared, f"missing from permissions.yml: {expected - declared}"
