#!/usr/bin/env python3
"""Check and repair repo-managed file permissions for rootless containers."""

from __future__ import annotations

import argparse
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


def chmod_chown(
    manifest: dict[str, Any],
    entry: dict[str, Any],
    *,
    runtime: str,
    recursive: bool,
    dry_run: bool,
) -> None:
    path = safe_path(entry["path"])
    result = run([*runtime_prefix(runtime), "mkdir", "-p", str(path)], dry_run=dry_run)
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or f"failed to create: {path}")

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
    host_acl = host_access_acl(manifest, default=False)
    host_default_acl = host_access_acl(manifest, default=True)
    for entry in manifest.get("paths", []):
        rel = entry["path"]
        path = safe_path(rel)
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
    for entry in manifest.get("paths", []):
        chmod_chown(
            manifest, entry, runtime=runtime, recursive=recursive, dry_run=dry_run
        )
        set_acl(manifest, entry, runtime=runtime, recursive=recursive, dry_run=dry_run)


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
