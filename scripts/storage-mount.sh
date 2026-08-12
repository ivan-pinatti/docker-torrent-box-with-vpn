#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2022 Ivan Pinatti
#
# Mounts, unmounts and reports on the external storage share that backs
# DATA_FOLDER, and installs the fstab entry that brings it back after a reboot.
# All settings come from .env's ### EXTERNAL STORAGE block; see docs/STORAGE.md.
#
# Usage: storage-mount.sh {mount|unmount|status|install-boot|uninstall-boot}
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

FSTAB=/etc/fstab
FSTAB_MARKER="# docker-torrent-box-with-vpn external storage"

# Reads one key from .env, stripping surrounding quotes. Deliberately not a
# `source`: .env defines UID, which is a readonly bash builtin, so sourcing it
# fails outright. Same approach as scripts/disk-status.sh.
env_value() {
  local key="$1" value
  [ -f .env ] || return 1
  value="$(
    awk -v key="$key" '
      index($0, key "=") == 1 {
        sub("^[^=]*=", "")
        sub(/^"/, ""); sub(/"$/, "")
        sub(/^'\''/, ""); sub(/'\''$/, "")
        print
        exit
      }
    ' .env
  )"
  [ -n "$value" ] || return 1
  printf '%s' "$value"
}

# .env expresses several paths in terms of other variables, e.g.
# STORAGE_MOUNTPOINT="${DATA_FOLDER}". env_value returns that literally, so a
# naive caller would mount into a directory named '${DATA_FOLDER}'. Expand the
# handful of keys that actually appear on the right hand side.
expand_env() {
  local v="$1"
  v="${v//\$\{DATA_FOLDER\}/$DATA_FOLDER}"
  v="${v//\$\{CONFIG_FOLDER\}/$CONFIG_FOLDER}"
  printf '%s' "$v"
}

DATA_FOLDER="$(env_value DATA_FOLDER || printf './data')"
CONFIG_FOLDER="$(env_value CONFIG_FOLDER || printf './configs')"
STORAGE_REMOTE="$(env_value STORAGE_REMOTE || printf '')"
STORAGE_MOUNTPOINT="$(expand_env "$(env_value STORAGE_MOUNTPOINT || printf "$DATA_FOLDER")")"
STORAGE_CREDENTIALS_FILE="$(expand_env "$(env_value STORAGE_CREDENTIALS_FILE || printf "$CONFIG_FOLDER/storage/.smbcredentials")")"

# Absolute paths: fstab needs them, and so does every mount check below.
mountpoint_abs="$(cd "$(dirname "$STORAGE_MOUNTPOINT")" 2>/dev/null && pwd)/$(basename "$STORAGE_MOUNTPOINT")"
credentials_abs="$repo_root/${STORAGE_CREDENTIALS_FILE#./}"

log() { printf '%s\n' "$*"; }
die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_configured() {
  [ -n "$STORAGE_REMOTE" ] || die "STORAGE_REMOTE is empty in .env; external storage is not configured."
  [ -f "$credentials_abs" ] || die "credentials file not found: $credentials_abs (copy .smbcredentials.example and fill it in)"
}

is_mounted() { findmnt --noheadings --target "$mountpoint_abs" --source "$STORAGE_REMOTE" >/dev/null 2>&1; }

# Builds the option string. context= is not optional: CIFS has no
# security.selinux xattr, so Podman's :z relabel cannot work and the label has
# to arrive with the mount. Without it every container is denied by SELinux
# while the mode bits look perfectly fine, which reads as a permissions bug and
# is not one.
mount_options() {
  local opts="credentials=${credentials_abs}"
  opts="${opts},uid=$(env_value STORAGE_CIFS_UID || printf '1000')"
  opts="${opts},gid=$(env_value STORAGE_CIFS_GID || printf '1000')"
  opts="${opts},vers=$(env_value STORAGE_CIFS_VERSION || printf '3.1.1')"
  opts="${opts},file_mode=$(env_value STORAGE_CIFS_FILE_MODE || printf '0664')"
  opts="${opts},dir_mode=$(env_value STORAGE_CIFS_DIR_MODE || printf '0775')"
  local extra context
  extra="$(env_value STORAGE_CIFS_EXTRA_OPTIONS || printf '')"
  [ -n "$extra" ] && opts="${opts},${extra}"
  context="$(env_value STORAGE_SELINUX_CONTEXT || printf '')"
  [ -n "$context" ] && opts="${opts},context=${context}"
  printf '%s' "$opts"
}

stack_containers_running() {
  command -v podman >/dev/null 2>&1 || return 1
  [ -n "$(podman ps --filter "label=com.docker.compose.project=$(basename "$repo_root")" --format '{{.Names}}' 2>/dev/null)" ]
}

verify_mount() {
  local opts probe
  opts="$(findmnt --noheadings --output OPTIONS --target "$mountpoint_abs" 2>/dev/null || true)"
  case ",$opts," in
  *,noserverino,*) log "WARNING: mounted with noserverino; hardlinks will be invisible to rsync -H and to the apps." ;;
  esac
  # The whole point of one share is that imports hardlink instead of copying.
  # Prove it here rather than discovering it after a library has doubled.
  probe="$mountpoint_abs/.storage-probe"
  rm -rf "$probe" 2>/dev/null || true
  if mkdir -p "$probe/a" "$probe/b" 2>/dev/null &&
    : >"$probe/a/f" 2>/dev/null &&
    ln "$probe/a/f" "$probe/b/f" 2>/dev/null &&
    [ "$(stat -c %h "$probe/a/f" 2>/dev/null)" = "2" ]; then
    log "hardlinks: OK (link count 2 across subdirectories)"
  else
    log "WARNING: hardlink probe failed; imports will copy instead of link."
  fi
  rm -rf "$probe" 2>/dev/null || true
}

cmd_mount() {
  require_configured
  if is_mounted; then
    log "already mounted: $STORAGE_REMOTE -> $mountpoint_abs"
    return 0
  fi
  mkdir -p "$mountpoint_abs"
  # The check that matters most. A mount that silently fails leaves the apps
  # writing into the local directory underneath, which looks completely normal
  # until the share comes back and that data is nowhere to be seen.
  if [ -n "$(ls -A "$mountpoint_abs" 2>/dev/null)" ]; then
    die "$mountpoint_abs is not empty. Refusing to mount over existing data; move it aside first."
  fi
  log "mounting $STORAGE_REMOTE -> $mountpoint_abs"
  sudo mount -t cifs -o "$(mount_options)" "$STORAGE_REMOTE" "$mountpoint_abs" ||
    die "mount failed. Check the share name, credentials and that cifs-utils is installed."
  log "mounted."
  verify_mount
}

cmd_unmount() {
  if ! is_mounted; then
    log "not mounted: $mountpoint_abs"
    return 0
  fi
  if stack_containers_running; then
    die "stack containers are running; stop them first (make stop_all)."
  fi
  log "unmounting $mountpoint_abs"
  sudo umount "$mountpoint_abs" 2>/dev/null || {
    log "busy; retrying lazily"
    sudo umount --lazy "$mountpoint_abs" || die "unmount failed."
  }
  log "unmounted."
}

cmd_status() {
  log "remote:     ${STORAGE_REMOTE:-<not configured>}"
  log "mountpoint: $mountpoint_abs"
  if [ -z "$STORAGE_REMOTE" ]; then
    log "state:      external storage not configured"
    return 0
  fi
  if is_mounted; then
    log "state:      mounted"
    log "fstype:     $(findmnt --noheadings --output FSTYPE --target "$mountpoint_abs")"
    log "options:    $(findmnt --noheadings --output OPTIONS --target "$mountpoint_abs")"
    df -h "$mountpoint_abs" | tail -1 | awk '{printf "space:      %s used of %s (%s free)\n", $3, $2, $4}'
  else
    log "state:      NOT MOUNTED"
    return 1
  fi
  if grep -qF "$FSTAB_MARKER" "$FSTAB" 2>/dev/null; then
    log "boot:       fstab entry installed"
  else
    log "boot:       no fstab entry (run: make storage_install_boot)"
  fi
}

fstab_line() {
  # nofail so a NAS that is down cannot block boot, _netdev so the mount waits
  # for the network, and x-systemd.automount so it happens on first access
  # rather than stalling startup. The trade is that the stack can start with an
  # empty data/, which is why make start refuses when STORAGE_REMOTE is set and
  # the share is not mounted.
  printf '%s %s cifs %s,_netdev,nofail,x-systemd.automount 0 0\n' \
    "$STORAGE_REMOTE" "$mountpoint_abs" "$(mount_options)"
}

cmd_install_boot() {
  require_configured
  if grep -qF "$FSTAB_MARKER" "$FSTAB" 2>/dev/null; then
    die "an entry is already installed in $FSTAB; run uninstall-boot first."
  fi
  log "This will append the following to $FSTAB:"
  log ""
  log "  $FSTAB_MARKER"
  log "  $(fstab_line)"
  log ""
  log "A malformed fstab entry can affect boot. $FSTAB will be backed up first."
  printf 'Type yes to continue: '
  read -r reply
  [ "$reply" = "yes" ] || die "aborted."
  local backup="${FSTAB}.$(date +%Y-%m-%d-%H%M%S).bak"
  sudo cp -a "$FSTAB" "$backup"
  log "backed up $FSTAB -> $backup"
  printf '%s\n%s' "$FSTAB_MARKER" "$(fstab_line)" | sudo tee -a "$FSTAB" >/dev/null
  # Prove it parses before trusting it to a reboot.
  if ! sudo findmnt --verify --verbose >/dev/null 2>&1; then
    log "WARNING: findmnt --verify reported problems; review $FSTAB (backup at $backup)."
  fi
  sudo systemctl daemon-reload 2>/dev/null || true
  log "installed. The share will mount on first access after boot."
}

cmd_uninstall_boot() {
  grep -qF "$FSTAB_MARKER" "$FSTAB" 2>/dev/null || {
    log "no entry found in $FSTAB"
    return 0
  }
  local backup="${FSTAB}.$(date +%Y-%m-%d-%H%M%S).bak"
  sudo cp -a "$FSTAB" "$backup"
  log "backed up $FSTAB -> $backup"
  sudo sed -i "\|^${FSTAB_MARKER}\$|,+1d" "$FSTAB"
  sudo systemctl daemon-reload 2>/dev/null || true
  log "removed."
}

case "${1:-}" in
mount) cmd_mount ;;
unmount) cmd_unmount ;;
status) cmd_status ;;
install-boot) cmd_install_boot ;;
uninstall-boot) cmd_uninstall_boot ;;
*) die "usage: $(basename "$0") {mount|unmount|status|install-boot|uninstall-boot}" ;;
esac
