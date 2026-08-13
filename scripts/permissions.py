#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2022 Ivan Pinatti
"""Check and repair repo-managed file permissions for rootless containers."""

from __future__ import annotations

import argparse
import functools
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "permissions.yml"

# Filesystems that cannot represent per-file ownership or POSIX ACLs. There the
# mount options fix uid, gid and mode for the whole tree, so chown, chmod and
# setfacl either fail outright or silently do nothing, and the manifest's
# ownership model simply does not apply. DATA_FOLDER sits on one of these
# whenever STORAGE_REMOTE is configured; see docs/STORAGE.md. Without this,
# `make start` dies before starting anything, because it depends on
# permissions_repair and the first setfacl against the share exits non-zero.
#
# NFS is deliberately absent: it carries real uid/gid and supports ACLs, so the
# manifest applies there as it does on local disk. That is the whole reason
# docs/STORAGE.md offers it as the alternative to SMB. It is not unconditional,
# since an export that squashes root, or a server without NFSACL/NFSv4 ACL
# support, will reject the chown or setfacl. Failing loudly is the right
# outcome for a setup chosen specifically to preserve ownership, rather than
# silently skipping and leaving the tree with whatever the export decided.
UNMANAGED_FSTYPES = frozenset(
    {
        "cifs",
        "smb3",
        "vfat",
        "exfat",
        "msdos",
        "ntfs",
        "ntfs3",
        "fuseblk",
    }
)


@functools.cache
def mount_table() -> tuple[tuple[str, str], ...]:
    """Mountpoints and their filesystem types, longest mountpoint first."""
    entries: list[tuple[str, str]] = []
    try:
        with open("/proc/self/mounts", encoding="utf-8") as handle:
            for line in handle:
                fields = line.split()
                if len(fields) >= 3:
                    entries.append((fields[1].replace("\\040", " "), fields[2]))
    except OSError:
        return ()
    entries.sort(key=lambda item: len(item[0]), reverse=True)
    return tuple(entries)


def path_fstype(path: Path) -> str | None:
    """Filesystem type backing path, by longest mountpoint prefix match.

    Deliberately string based rather than stat based so it also answers for
    paths that do not exist yet: repair() creates directories as it walks the
    manifest, and needs the answer before the mkdir.
    """
    target = str(path)
    for mountpoint, fstype in mount_table():
        if target == mountpoint or target.startswith(mountpoint.rstrip("/") + "/"):
            return fstype
    return None


def unmanaged_fstype(path: Path) -> str | None:
    """The fstype if path is on a filesystem the manifest cannot manage."""
    fstype = path_fstype(path)
    return fstype if fstype in UNMANAGED_FSTYPES else None


def report_unmanaged(skipped: dict[str, str]) -> None:
    if not skipped:
        return
    by_type: dict[str, list[str]] = {}
    for rel, fstype in skipped.items():
        by_type.setdefault(fstype, []).append(rel)
    for fstype, paths in sorted(by_type.items()):
        print(
            f"note: skipped ownership and ACLs for {len(paths)} path(s) on {fstype}: "
            f"{paths[0]}{' ...' if len(paths) > 1 else ''}"
        )
        print(
            f"      {fstype} carries no per-file ownership or POSIX ACLs; access "
            "there comes from the mount options instead."
        )


def load_manifest() -> dict[str, Any]:
    with MANIFEST.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise SystemExit("permissions.yml must contain a mapping")
    return data


def identity_id(manifest: dict[str, Any], name: str | None) -> tuple[int, int]:
    if name in (None, "root"):
        return 0, 0
    identities = manifest.get("identities", {})
    if name not in identities:
        raise SystemExit(f"unknown identity in permissions.yml: {name}")
    ident = identities[name]
    return int(ident["uid"]), int(ident["gid"])


def safe_path(rel_path: str) -> Path:
    path = (REPO_ROOT / rel_path).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise SystemExit(f"refusing path outside repository: {rel_path}") from exc
    return path


def safe_link_path(rel_path: str) -> Path:
    """Containment check for a path that is itself a symlink.

    safe_path resolves the whole path, which for these follows the link to its
    target. The targets are container paths like /mediacover and are outside
    the repository on purpose, so that check refuses them. What has to stay
    inside the repository is where the link lives, so resolve the parent and
    leave the final component alone.
    """
    path = REPO_ROOT / rel_path
    parent = path.parent.resolve()
    try:
        parent.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise SystemExit(f"refusing path outside repository: {rel_path}") from exc
    return parent / path.name


def run(cmd: list[str], *, dry_run: bool = False) -> subprocess.CompletedProcess[str]:
    printable = " ".join(shlex.quote(part) for part in cmd)
    if dry_run:
        print(printable)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def runtime_prefix(runtime: str) -> list[str]:
    if runtime == "podman":
        return ["podman", "unshare"]
    return []


def ensure_dir(path: Path, *, runtime: str, dry_run: bool) -> None:
    result = run([*runtime_prefix(runtime), "mkdir", "-p", str(path)], dry_run=dry_run)
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or f"failed to create: {path}")


def ensure_symlinks(manifest: dict[str, Any], *, dry_run: bool) -> None:
    """Points each app's artwork and backup directory at its bind mount.

    The compose files mount these outside /config and the apps still look for
    them inside it, so without the link the app quietly creates a real
    directory in configs/ instead. That is on local disk rather than the data
    tree, and the backup targets exclude those paths, so it goes unnoticed.

    Never replaces a directory that has anything in it. A populated MediaCover
    is the pre-migration copy of the artwork, and deleting it to make room for
    a link would throw away the only copy.
    """
    for entry in manifest.get("symlinks", []):
        path = safe_link_path(entry["path"])
        target = entry["target"]
        if path.is_symlink():
            if os.readlink(path) == target:
                continue
            if dry_run:
                print(f"ln -sfn {target} {path}")
                continue
            path.unlink()
        elif path.exists():
            if not path.is_dir():
                raise SystemExit(f"{path} exists and is not a directory; move it aside")
            if any(path.iterdir()):
                raise SystemExit(
                    f"{path} is a non-empty directory where a symlink to {target} "
                    f"belongs. Move its contents onto the mounted tree first, then "
                    f"remove the directory; refusing to delete it here."
                )
            if dry_run:
                print(f"rmdir {path} && ln -s {target} {path}")
                continue
            path.rmdir()
        elif dry_run:
            print(f"ln -s {target} {path}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)


def chmod_chown(
    manifest: dict[str, Any],
    entry: dict[str, Any],
    *,
    runtime: str,
    recursive: bool,
    dry_run: bool,
) -> None:
    path = safe_path(entry["path"])
    ensure_dir(path, runtime=runtime, dry_run=dry_run)

    uid, gid = identity_id(manifest, entry.get("owner"))
    prefix = runtime_prefix(runtime)
    if recursive and entry.get("chown_files", False):
        chown_cmd = [*prefix, "chown", "-R", f"{uid}:{gid}", str(path)]
    elif recursive:
        chown_cmd = [
            *prefix,
            "find",
            str(path),
            "-type",
            "d",
            "-exec",
            "chown",
            f"{uid}:{gid}",
            "{}",
            "+",
        ]
    else:
        chown_cmd = [*prefix, "chown", f"{uid}:{gid}", str(path)]
    result = run(chown_cmd, dry_run=dry_run)
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or f"failed: {chown_cmd}")

    mode = str(entry["mode"])
    chmod_cmd = [*prefix, "chmod", mode, str(path)]
    result = run(chmod_cmd, dry_run=dry_run)
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or f"failed: {chmod_cmd}")


def host_access_acl(manifest: dict[str, Any], *, default: bool) -> list[dict[str, str]]:
    host_access = manifest.get("host_access") or {}
    if not host_access.get("enabled", False):
        return []
    perms_key = "default_perms" if default else "perms"
    perms = host_access.get(perms_key)
    if not perms:
        return []
    return [{"identity": host_access.get("identity", "root"), "perms": perms}]


def effective_acl(
    manifest: dict[str, Any],
    entry: dict[str, Any],
    *,
    default: bool,
) -> list[dict[str, str]]:
    key = "default_acl" if default else "acl"
    entries = [*entry.get(key, []), *host_access_acl(manifest, default=default)]
    by_identity: dict[str, dict[str, str]] = {}
    for acl in entries:
        by_identity[acl["identity"]] = acl
    return list(by_identity.values())


def acl_args(
    manifest: dict[str, Any], entries: list[dict[str, str]], default: bool
) -> list[str]:
    args: list[str] = []
    for acl in entries:
        uid, _ = identity_id(manifest, acl["identity"])
        prefix = "d:u" if default else "u"
        args.extend(["-m", f"{prefix}:{uid}:{acl['perms']}"])
    return args


def is_dir_namespace(path: Path, runtime: str) -> bool:
    result = run([*runtime_prefix(runtime), "test", "-d", str(path)])
    return result.returncode == 0


def set_acl(
    manifest: dict[str, Any],
    entry: dict[str, Any],
    *,
    runtime: str,
    recursive: bool,
    dry_run: bool,
) -> None:
    acl = effective_acl(manifest, entry, default=False)
    default_acl = effective_acl(manifest, entry, default=True)
    if not acl and not default_acl:
        return
    path = safe_path(entry["path"])
    if acl:
        mask_perms = "rwx" if any("w" in item["perms"] for item in acl) else "r-x"
        cmd = [*runtime_prefix(runtime), "setfacl", *acl_args(manifest, acl, False)]
        if recursive:
            cmd.append("-R")
        cmd.extend(["-m", f"m::{mask_perms}", str(path)])
        result = run(cmd, dry_run=dry_run)
        if result.returncode != 0:
            raise SystemExit(result.stderr.strip() or f"failed: {cmd}")

    if default_acl:
        default_mask_perms = (
            "rwx" if any("w" in item["perms"] for item in default_acl) else "r-x"
        )
        default_args = [
            *acl_args(manifest, default_acl, True),
            "-m",
            f"d:m::{default_mask_perms}",
        ]
        if recursive:
            cmd = [
                *runtime_prefix(runtime),
                "find",
                str(path),
                "-type",
                "d",
                "-exec",
                "setfacl",
                *default_args,
                "{}",
                "+",
            ]
        elif dry_run or is_dir_namespace(path, runtime):
            cmd = [*runtime_prefix(runtime), "setfacl", *default_args, str(path)]
        else:
            return
        result = run(cmd, dry_run=dry_run)
        if result.returncode != 0:
            raise SystemExit(result.stderr.strip() or f"failed: {cmd}")


def expected_stat_mode(manifest: dict[str, Any], entry: dict[str, Any]) -> str:
    mode = int(str(entry["mode"]), 8)
    acl = [
        *effective_acl(manifest, entry, default=False),
        *effective_acl(manifest, entry, default=True),
    ]
    if any("w" in item["perms"] for item in acl):
        mode |= 0o020
    return f"{mode:04o}"


def path_mode(path: Path) -> str:
    return f"{path.stat().st_mode & 0o777:04o}"


def stat_namespace(path: Path, runtime: str) -> tuple[int, int, str]:
    cmd = [*runtime_prefix(runtime), "stat", "-c", "%u %g %a", str(path)]
    result = run(cmd)
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip())
    uid, gid, mode = result.stdout.strip().split()
    return int(uid), int(gid), f"{int(mode, 8):04o}"


def getfacl_namespace(path: Path, runtime: str) -> set[str]:
    cmd = [*runtime_prefix(runtime), "getfacl", "-cpn", str(path)]
    result = run(cmd)
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip())
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def manifest_entry_for_path(
    manifest: dict[str, Any], path: Path
) -> dict[str, Any] | None:
    for entry in manifest.get("paths", []):
        if safe_path(entry["path"]) == path.resolve():
            return entry
    return None


def check(manifest: dict[str, Any], *, runtime: str) -> int:
    failures: list[str] = []
    skipped: dict[str, str] = {}
    host_acl = host_access_acl(manifest, default=False)
    host_default_acl = host_access_acl(manifest, default=True)
    for entry in manifest.get("paths", []):
        rel = entry["path"]
        path = safe_path(rel)
        fstype = unmanaged_fstype(path)
        if fstype:
            skipped[rel] = fstype
            continue
        expected_uid, expected_gid = identity_id(manifest, entry.get("owner"))
        try:
            actual_uid, actual_gid, actual_mode = stat_namespace(path, runtime)
        except SystemExit as exc:
            failures.append(f"missing or inaccessible: {rel}: {exc}")
            continue
        expected_mode = expected_stat_mode(manifest, entry)
        if (actual_uid, actual_gid) != (expected_uid, expected_gid):
            failures.append(
                f"{rel}: owner {actual_uid}:{actual_gid}, expected {expected_uid}:{expected_gid}"
            )
        if actual_mode != expected_mode:
            failures.append(f"{rel}: mode {actual_mode}, expected {expected_mode}")
        if host_acl or host_default_acl:
            try:
                acl_lines = getfacl_namespace(path, runtime)
            except SystemExit as exc:
                failures.append(f"{rel}: cannot inspect ACL: {exc}")
                continue
            for acl in host_acl:
                uid, _ = identity_id(manifest, acl["identity"])
                expected_acl = f"user:{uid}:{acl['perms']}"
                if expected_acl not in acl_lines:
                    failures.append(f"{rel}: missing host ACL {expected_acl}")
            if is_dir_namespace(path, runtime):
                for acl in host_default_acl:
                    uid, _ = identity_id(manifest, acl["identity"])
                    expected_acl = f"default:user:{uid}:{acl['perms']}"
                    if expected_acl not in acl_lines:
                        failures.append(
                            f"{rel}: missing host default ACL {expected_acl}"
                        )
    for entry in manifest.get("symlinks", []):
        path = safe_link_path(entry["path"])
        rel = entry["path"]
        if not path.is_symlink():
            what = "a directory" if path.is_dir() else "missing"
            failures.append(
                f"{rel}: expected a symlink to {entry['target']}, found {what}"
            )
        elif os.readlink(path) != entry["target"]:
            failures.append(
                f"{rel}: points at {os.readlink(path)}, expected {entry['target']}"
            )
    report_unmanaged(skipped)
    if failures:
        print("\n".join(failures))
        return 1
    print("permissions manifest check passed")
    return 0


def repair(
    manifest: dict[str, Any],
    *,
    runtime: str,
    dry_run: bool,
    recursive: bool,
) -> None:
    if runtime == "podman" and not shutil.which("podman"):
        raise SystemExit("podman is required for rootless permission repair")
    skipped: dict[str, str] = {}
    for entry in manifest.get("paths", []):
        path = safe_path(entry["path"])
        fstype = unmanaged_fstype(path)
        if fstype:
            # The tree still has to exist, the apps expect these directories.
            # Only the ownership and ACL work is meaningless here.
            ensure_dir(path, runtime=runtime, dry_run=dry_run)
            skipped[entry["path"]] = fstype
            continue
        chmod_chown(
            manifest, entry, runtime=runtime, recursive=recursive, dry_run=dry_run
        )
        set_acl(manifest, entry, runtime=runtime, recursive=recursive, dry_run=dry_run)
    # After the directories exist: a link is created inside configs/<app>/config,
    # which the loop above is what guarantees is there.
    ensure_symlinks(manifest, dry_run=dry_run)
    report_unmanaged(skipped)


def smoke(manifest: dict[str, Any], *, runtime: str) -> int:
    failures: list[str] = []
    tests = manifest.get("smoke_tests", {}).get("hardlinks", [])
    for test in tests:
        importer_uid, importer_gid = identity_id(manifest, test["user"])
        source_dir = safe_path(test["source_dir"])
        target_dir = safe_path(test["target_dir"])
        source_entry = manifest_entry_for_path(manifest, source_dir)
        if source_entry is None:
            failures.append(
                f"{test['name']}: source_dir is not declared in permissions.yml"
            )
            continue
        source_uid, source_gid = identity_id(manifest, source_entry.get("owner"))
        source = source_dir / ".permissions_source"
        target = target_dir / ".permissions_target"
        source_arg = shlex.quote(str(source.relative_to(REPO_ROOT)))
        target_arg = shlex.quote(str(target.relative_to(REPO_ROOT)))
        cmd = [
            *runtime_prefix(runtime),
            "sh",
            "-c",
            (
                f"rm -f {source_arg} {target_arg} && "
                f"setpriv --reuid {source_uid} --regid {source_gid} --clear-groups "
                f"touch {source_arg} && "
                f"setpriv --reuid {importer_uid} --regid {importer_gid} --clear-groups "
                f"ln {source_arg} {target_arg} && "
                f"rm -f {source_arg} {target_arg}"
            ),
        ]
        result = run(cmd)
        if result.returncode != 0:
            failures.append(
                f"{test['name']}: {result.stderr.strip() or result.stdout.strip()}"
            )
    if failures:
        print("\n".join(failures))
        return 1
    print("hardlink smoke tests passed")
    return 0


def host_smoke(manifest: dict[str, Any]) -> int:
    failures: list[str] = []
    for entry in manifest.get("paths", []):
        path = safe_path(entry["path"])
        if not path.is_dir():
            continue
        test_file = path / ".host_access_smoke"
        test_dir = path / ".host_access_smoke_dir"
        moved_dir = path / ".host_access_smoke_dir_moved"
        try:
            test_file.write_text("host access smoke\n", encoding="utf-8")
            test_file.write_text("host access smoke edited\n", encoding="utf-8")
            test_file.unlink()
            test_dir.mkdir(exist_ok=True)
            if moved_dir.exists():
                moved_dir.rmdir()
            test_dir.rename(moved_dir)
            moved_dir.rmdir()
        except OSError as exc:
            failures.append(f"{entry['path']}: {exc}")
            for cleanup in (test_file, test_dir, moved_dir):
                try:
                    if cleanup.is_dir():
                        cleanup.rmdir()
                    elif cleanup.exists():
                        cleanup.unlink()
                except OSError:
                    pass
    if failures:
        print("\n".join(failures))
        return 1
    print("host access smoke tests passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("check", "repair", "dry-run", "smoke", "host-smoke")
    )
    parser.add_argument(
        "--runtime",
        default=os.environ.get("CONTAINER_RUNTIME", "podman"),
        choices=("podman", "docker"),
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="apply ownership and mode recursively below each managed path",
    )
    args = parser.parse_args()

    manifest = load_manifest()
    if args.command == "check":
        return check(manifest, runtime=args.runtime)
    if args.command == "smoke":
        return smoke(manifest, runtime=args.runtime)
    if args.command == "host-smoke":
        return host_smoke(manifest)
    repair(
        manifest,
        runtime=args.runtime,
        dry_run=args.command == "dry-run",
        recursive=args.recursive,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
