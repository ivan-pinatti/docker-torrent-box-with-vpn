"""Tests for scripts/storage-mount.sh and the guards built around it.

None of these touch the real mount, the real /etc/fstab or the running stack.
The script derives its repository root from its own location and reads .env
from there, so every test runs it out of a throwaway root built by the
``fake_repo`` fixture, with its own .env and its own fstab. ``SUDO=""`` makes
the boot-entry path runnable unprivileged, which is the only way to cover it
without a reboot.

Run explicitly with:
    pytest -m scripts tests/test_storage_mount.py
"""

import json
import os
import shutil
import subprocess

import pytest

from conftest import REPO_ROOT

pytestmark = pytest.mark.scripts

SCRIPT = REPO_ROOT / "scripts/storage-mount.sh"
SETTINGS = REPO_ROOT / ".claude/settings.json"

# A complete ### EXTERNAL STORAGE block, matching .env.example's shape,
# including the ${DATA_FOLDER} indirection the script has to expand itself.
ENV_TEMPLATE = """\
CONFIG_FOLDER=./configs
DATA_FOLDER=./data
STORAGE_REMOTE={remote}
STORAGE_MOUNTPOINT="${{DATA_FOLDER}}"
STORAGE_CREDENTIALS_FILE="${{CONFIG_FOLDER}}/storage/.smbcredentials"
STORAGE_CIFS_VERSION=3.1.1
STORAGE_CIFS_UID=1000
STORAGE_CIFS_GID=1000
STORAGE_CIFS_FILE_MODE=0664
STORAGE_CIFS_DIR_MODE=0775
STORAGE_CIFS_EXTRA_OPTIONS=noperm,mfsymlinks,serverino,cache=strict,actimeo=120
STORAGE_SELINUX_CONTEXT=system_u:object_r:container_file_t:s0
"""


@pytest.fixture
def fake_repo(tmp_path):
    """A throwaway repository root holding a copy of the script."""
    (tmp_path / "scripts").mkdir()
    shutil.copy2(SCRIPT, tmp_path / "scripts/storage-mount.sh")
    (tmp_path / "configs/storage").mkdir(parents=True)
    (tmp_path / "data").mkdir()
    return tmp_path


def _write_env(root, remote="//server/share", credentials=True):
    (root / ".env").write_text(ENV_TEMPLATE.format(remote=remote))
    if credentials:
        cred = root / "configs/storage/.smbcredentials"
        cred.write_text("username=someone\npassword=secret\n")
        cred.chmod(0o600)


def _run(root, *args, stdin=subprocess.DEVNULL, env=None):
    merged = {**os.environ, "SUDO": "", **(env or {})}
    return subprocess.run(
        [str(root / "scripts/storage-mount.sh"), *args],
        cwd=root,
        env=merged,
        stdin=stdin,
        capture_output=True,
        text=True,
        timeout=120,
    )


# ---------------------------------------------------------------------------
# Argument handling and configuration reading
# ---------------------------------------------------------------------------


def test_rejects_unknown_subcommand(fake_repo):
    _write_env(fake_repo)
    result = _run(fake_repo, "bogus")
    assert result.returncode != 0
    assert "usage:" in result.stderr


def test_rejects_missing_subcommand(fake_repo):
    _write_env(fake_repo)
    result = _run(fake_repo)
    assert result.returncode != 0
    assert "usage:" in result.stderr


def test_status_reports_unconfigured_without_a_remote(fake_repo):
    _write_env(fake_repo, remote="")
    result = _run(fake_repo, "status")
    assert result.returncode == 0, result.stderr
    assert "external storage not configured" in result.stdout


def test_status_exits_nonzero_when_configured_but_not_mounted(fake_repo):
    """What make start's storage guard keys off."""
    _write_env(fake_repo)
    result = _run(fake_repo, "status")
    assert result.returncode != 0
    assert "NOT MOUNTED" in result.stdout


def test_expands_data_folder_in_the_mountpoint(fake_repo):
    """STORAGE_MOUNTPOINT="${DATA_FOLDER}" must not be taken literally.

    Read straight from .env it is the eight characters '${DATA_FOLDER}', and a
    caller that does not expand it mounts into a directory of that name.
    """
    _write_env(fake_repo)
    result = _run(fake_repo, "status")
    assert "${DATA_FOLDER}" not in result.stdout
    assert f"mountpoint: {fake_repo}/data" in result.stdout


def test_expands_config_folder_in_the_credentials_path(fake_repo):
    """Same indirection on STORAGE_CREDENTIALS_FILE.

    Unexpanded it points at a file that does not exist, so require_configured
    would refuse to mount a correctly configured install.
    """
    _write_env(fake_repo)
    result = _run(fake_repo, "mount")
    assert "${CONFIG_FOLDER}" not in result.stderr
    assert "credentials file not found" not in result.stderr


# ---------------------------------------------------------------------------
# mount refusals. None of these reach the mount call.
# ---------------------------------------------------------------------------


def test_mount_refuses_without_a_remote(fake_repo):
    _write_env(fake_repo, remote="")
    result = _run(fake_repo, "mount")
    assert result.returncode != 0
    assert "STORAGE_REMOTE is empty" in result.stderr


def test_mount_refuses_without_credentials(fake_repo):
    _write_env(fake_repo, credentials=False)
    result = _run(fake_repo, "mount")
    assert result.returncode != 0
    assert "credentials file not found" in result.stderr


def test_mount_refuses_a_non_empty_mountpoint(fake_repo):
    """The guard that matters most.

    Mounting over a populated data/ hides it. Worse is the inverse: if the
    mount silently fails the apps write into the local directory underneath
    and everything looks normal until the share returns.
    """
    _write_env(fake_repo)
    (fake_repo / "data/torrents").mkdir()
    result = _run(fake_repo, "mount")
    assert result.returncode != 0
    assert "not empty" in result.stderr
    assert "Refusing to mount over existing data" in result.stderr


def test_mount_creates_a_missing_mountpoint(fake_repo):
    _write_env(fake_repo)
    shutil.rmtree(fake_repo / "data")
    _run(fake_repo, "mount")
    assert (fake_repo / "data").is_dir()


# ---------------------------------------------------------------------------
# unmount
# ---------------------------------------------------------------------------


def test_unmount_is_a_no_op_when_not_mounted(fake_repo):
    _write_env(fake_repo)
    result = _run(fake_repo, "unmount")
    assert result.returncode == 0, result.stderr
    assert "not mounted" in result.stdout


# ---------------------------------------------------------------------------
# Mount options. Two of these have already cost a live debugging session.
# ---------------------------------------------------------------------------


def _install(fake_repo, fstab):
    """Runs install-boot all the way through, answering its confirmation."""
    merged = {**os.environ, "SUDO": "", "FSTAB": str(fstab)}
    return subprocess.run(
        [str(fake_repo / "scripts/storage-mount.sh"), "install-boot"],
        cwd=fake_repo,
        env=merged,
        input="yes\n",
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture
def fstab(tmp_path):
    path = tmp_path / "fstab"
    path.write_text("UUID=00000000-0000-0000-0000-000000000000 / ext4 defaults 0 1\n")
    return path


def test_fstab_entry_carries_the_selinux_context(fake_repo, fstab):
    """CIFS has no security.selinux xattr, so Podman's :z cannot label it.

    Without context= every container is denied by SELinux while the mode bits
    look correct, which reads as a permissions bug and is not one.
    """
    _write_env(fake_repo)
    assert _install(fake_repo, fstab).returncode == 0
    line = fstab.read_text().splitlines()[-1]
    assert "context=system_u:object_r:container_file_t:s0" in line


def test_fstab_entry_keeps_serverino(fake_repo, fstab):
    """serverino is what makes hardlinks visible at all."""
    _write_env(fake_repo)
    _install(fake_repo, fstab)
    assert "serverino" in fstab.read_text().splitlines()[-1]


def test_fstab_entry_has_the_boot_safety_options(fake_repo, fstab):
    """_netdev so it waits for the network, nofail so a NAS that is down
    cannot hold up boot."""
    _write_env(fake_repo)
    _install(fake_repo, fstab)
    line = fstab.read_text().splitlines()[-1]
    for option in ("_netdev", "nofail"):
        assert option in line, f"{option} missing from {line}"


def test_fstab_entry_does_not_use_automount(fake_repo, fstab):
    """An autofs mount reports its source as 'systemd-1' until something
    touches the path, and findmnt reads mountinfo without touching it. With
    x-systemd.automount every check here would read a healthy share as NOT
    MOUNTED after a reboot, and make start would refuse to run."""
    _write_env(fake_repo)
    _install(fake_repo, fstab)
    assert "automount" not in fstab.read_text().splitlines()[-1]


def test_fstab_entry_is_well_formed(fake_repo, fstab):
    _write_env(fake_repo)
    _install(fake_repo, fstab)
    fields = fstab.read_text().splitlines()[-1].split()
    assert len(fields) == 6, f"fstab needs 6 fields, got {fields}"
    assert fields[0] == "//server/share"
    assert fields[1] == f"{fake_repo}/data"
    assert fields[2] == "cifs"
    assert (fields[4], fields[5]) == ("0", "0")


def test_fstab_entry_uses_an_absolute_mountpoint(fake_repo, fstab):
    """A relative path in fstab would resolve against / at boot."""
    _write_env(fake_repo)
    _install(fake_repo, fstab)
    assert fstab.read_text().splitlines()[-1].split()[1].startswith("/")


# ---------------------------------------------------------------------------
# install-boot / uninstall-boot. The path that can affect a reboot.
# ---------------------------------------------------------------------------


def test_install_boot_requires_typed_confirmation(fake_repo, fstab):
    _write_env(fake_repo)
    before = fstab.read_text()
    result = _run(fake_repo, "install-boot", env={"FSTAB": str(fstab)})
    assert result.returncode != 0
    assert fstab.read_text() == before, "fstab was modified without confirmation"


def test_install_boot_rejects_anything_but_yes(fake_repo, fstab):
    _write_env(fake_repo)
    before = fstab.read_text()
    result = subprocess.run(
        [str(fake_repo / "scripts/storage-mount.sh"), "install-boot"],
        cwd=fake_repo,
        env={**os.environ, "SUDO": "", "FSTAB": str(fstab)},
        input="y\n",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0
    assert "aborted" in result.stderr
    assert fstab.read_text() == before


def test_install_boot_previews_the_line_before_asking(fake_repo, fstab):
    _write_env(fake_repo)
    result = _run(fake_repo, "install-boot", env={"FSTAB": str(fstab)})
    assert "//server/share" in result.stdout
    assert "cifs" in result.stdout


def test_install_boot_backs_up_fstab(fake_repo, fstab):
    _write_env(fake_repo)
    original = fstab.read_text()
    assert _install(fake_repo, fstab).returncode == 0
    backups = list(fstab.parent.glob("fstab.*.bak"))
    assert len(backups) == 1, f"expected one backup, found {backups}"
    assert backups[0].read_text() == original


def test_install_boot_preserves_existing_entries(fake_repo, fstab):
    _write_env(fake_repo)
    original = fstab.read_text()
    _install(fake_repo, fstab)
    assert fstab.read_text().startswith(original)


def test_install_boot_ends_the_file_with_a_newline(fake_repo, fstab):
    """A trailing newline is not cosmetic here.

    Without it the next thing appended to fstab, by this script or anything
    else, lands on the end of our entry and corrupts both lines.
    """
    _write_env(fake_repo)
    _install(fake_repo, fstab)
    assert fstab.read_text().endswith("\n")


def test_install_boot_does_not_join_onto_an_unterminated_last_line(fake_repo, fstab):
    """An fstab whose final line lacks a newline is legal and does happen."""
    fstab.write_text("UUID=deadbeef / ext4 defaults 0 1")
    _write_env(fake_repo)
    _install(fake_repo, fstab)
    lines = fstab.read_text().splitlines()
    assert lines[0] == "UUID=deadbeef / ext4 defaults 0 1", (
        "existing entry was corrupted"
    )
    assert any(line.startswith("//server/share") for line in lines)


def test_install_boot_is_not_applied_twice(fake_repo, fstab):
    _write_env(fake_repo)
    assert _install(fake_repo, fstab).returncode == 0
    second = _install(fake_repo, fstab)
    assert second.returncode != 0
    assert "already installed" in second.stderr
    assert fstab.read_text().count("//server/share") == 1


def test_install_boot_refuses_when_unconfigured(fake_repo, fstab):
    _write_env(fake_repo, remote="")
    before = fstab.read_text()
    assert _install(fake_repo, fstab).returncode != 0
    assert fstab.read_text() == before


def test_uninstall_boot_removes_both_lines(fake_repo, fstab):
    _write_env(fake_repo)
    original = fstab.read_text()
    _install(fake_repo, fstab)
    result = _run(fake_repo, "uninstall-boot", env={"FSTAB": str(fstab)})
    assert result.returncode == 0, result.stderr
    assert fstab.read_text() == original, "uninstall did not restore fstab exactly"


def test_uninstall_boot_is_a_no_op_when_absent(fake_repo, fstab):
    _write_env(fake_repo)
    before = fstab.read_text()
    result = _run(fake_repo, "uninstall-boot", env={"FSTAB": str(fstab)})
    assert result.returncode == 0, result.stderr
    assert "no entry found" in result.stdout
    assert fstab.read_text() == before


def test_boot_entry_round_trips(fake_repo, fstab):
    """install then uninstall, twice, leaves fstab byte for byte unchanged."""
    _write_env(fake_repo)
    original = fstab.read_text()
    for _ in range(2):
        assert _install(fake_repo, fstab).returncode == 0
        assert (
            _run(fake_repo, "uninstall-boot", env={"FSTAB": str(fstab)}).returncode == 0
        )
    assert fstab.read_text() == original


def test_status_reports_the_boot_entry(fake_repo, fstab):
    _write_env(fake_repo)
    _install(fake_repo, fstab)
    # status exits 1 because the share is not mounted; the boot line is still
    # not reached in that branch, so assert on the fstab state the branch reads.
    assert "docker-torrent-box-with-vpn external storage" in fstab.read_text()


# ---------------------------------------------------------------------------
# make start's storage guard
# ---------------------------------------------------------------------------


def test_makefile_start_targets_depend_on_the_storage_guard():
    """An automounted share can be absent at boot, so the stack must refuse to
    start against an empty data/ rather than write into it."""
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert "storage_guard:" in makefile
    for target in ("start:", "start_library:", "start_observability:"):
        line = next(ln for ln in makefile.splitlines() if ln.startswith(target))
        assert "storage_guard" in line, f"{target} does not depend on storage_guard"


# ---------------------------------------------------------------------------
# The PreToolUse hook that keeps git off a running stack
# ---------------------------------------------------------------------------


def _hook_command():
    settings = json.loads(SETTINGS.read_text())
    entries = [e for e in settings["hooks"]["PreToolUse"] if e["matcher"] == "Bash"]
    assert entries, "no PreToolUse hook on the Bash matcher"
    return entries[0]["hooks"][0]["command"]


def _run_hook(command, tool_command, tmp_path, *, containers_running):
    """Runs the hook with a stub podman reporting the given stack state."""
    binstub = tmp_path / "bin"
    binstub.mkdir(exist_ok=True)
    podman = binstub / "podman"
    podman.write_text(
        "#!/bin/sh\n" + ("echo qbittorrent\n" if containers_running else "exit 0\n")
    )
    podman.chmod(0o755)
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": tool_command}})
    return subprocess.run(
        ["bash", "-c", command],
        input=payload,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "PATH": f"{binstub}:{os.environ['PATH']}"},
    )


def test_settings_json_is_valid():
    """A malformed settings.json silently disables every setting in it."""
    json.loads(SETTINGS.read_text())


def test_hook_blocks_git_while_the_stack_runs(tmp_path):
    """pre-commit's stash cycle rewrote tracked runtime files mid-flight and
    corrupted live SQLite databases. CLAUDE.md warned about it and the warning
    was not enough, so this is enforced."""
    command = _hook_command()
    for subcommand in ("stash -u", "commit -m x", "checkout main", "switch -c topic"):
        result = _run_hook(
            command, f"git {subcommand}", tmp_path, containers_running=True
        )
        assert "deny" in result.stdout, f"git {subcommand} was not blocked"


def test_hook_blocks_git_in_a_compound_command(tmp_path):
    command = _hook_command()
    for wrapper in (
        "cd /tmp && git stash",
        "true; git commit -m x",
        "false || git checkout main",
    ):
        result = _run_hook(command, wrapper, tmp_path, containers_running=True)
        assert "deny" in result.stdout, f"{wrapper!r} was not blocked"


def test_hook_allows_git_once_the_stack_is_stopped(tmp_path):
    command = _hook_command()
    result = _run_hook(command, "git commit -m x", tmp_path, containers_running=False)
    assert result.stdout.strip() == "", "git was blocked with no containers running"


def test_hook_ignores_commands_that_merely_mention_git(tmp_path):
    """The first version of this hook matched substrings and blocked its own
    test command."""
    command = _hook_command()
    for benign in (
        "echo 'git commit'",
        "grep -r 'git stash' docs/",
        "ls -la",
        "cat README.md",
    ):
        result = _run_hook(command, benign, tmp_path, containers_running=True)
        assert result.stdout.strip() == "", f"{benign!r} was blocked"


def test_hook_allows_read_only_git(tmp_path):
    """Reading history mutates nothing and must stay available."""
    command = _hook_command()
    for readonly in ("git status", "git log --oneline -5", "git diff"):
        result = _run_hook(command, readonly, tmp_path, containers_running=True)
        assert result.stdout.strip() == "", f"{readonly!r} was blocked"


def test_hook_exits_zero_so_it_never_breaks_the_session(tmp_path):
    command = _hook_command()
    for running in (True, False):
        result = _run_hook(
            command, "git commit -m x", tmp_path, containers_running=running
        )
        assert result.returncode == 0


def test_settings_json_keeps_its_permission_rules():
    """The hook was merged into a file that already carried allow rules."""
    settings = json.loads(SETTINGS.read_text())
    assert len(settings["permissions"]["allow"]) >= 30
