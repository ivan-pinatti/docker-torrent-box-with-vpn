#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/rotate-api-keys.sh [sonarr|radarr|lidarr|readarr|whisparr|prowlarr|bazarr|lazylibrarian|mylar|nzbhydra2|jellyfin|all]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly REPO_ROOT
cd "$REPO_ROOT"

readonly USAGE="Usage: $0 [sonarr|radarr|lidarr|readarr|whisparr|prowlarr|bazarr|lazylibrarian|mylar|nzbhydra2|jellyfin|all]"

if [[ $# -ne 1 ]]; then
  echo "$USAGE" >&2
  exit 1
fi

readonly TARGET="$1"

# Read the network and port variables we need from .env without sourcing it
# (.env defines UID, which is a readonly bash builtin, so `source .env` fails).
env_value() {
  local key="$1"
  grep -m1 "^${key}=" .env | cut -d= -f2-
}

PROWLARR_HTTPS_PORT="$(env_value PROWLARR_HTTPS_PORT)"
JELLYFIN_HTTP_PORT="$(env_value JELLYFIN_HTTP_PORT)"
# BaseUrl is a server-wide Jellyfin setting (see wire-connections.sh), not an
# nginx-only rewrite, so every direct call here needs it too: a bare
# http://127.0.0.1:<port>/... 302-redirects instead of answering, which
# curl --fail treats as success, silently breaking every call below it.
JELLYFIN_BASE_URL="$(env_value JELLYFIN_BASE_URL)"
SONARR_HTTP_PORT="$(env_value SONARR_HTTP_PORT)"
RADARR_HTTPS_PORT="$(env_value RADARR_HTTPS_PORT)"
LIDARR_HTTPS_PORT="$(env_value LIDARR_HTTPS_PORT)"
READARR_HTTPS_PORT="$(env_value READARR_HTTPS_PORT)"
WHISPARR_HTTPS_PORT="$(env_value WHISPARR_HTTPS_PORT)"
BAZARR_HTTP_PORT="$(env_value BAZARR_HTTP_PORT)"
LAZYLIBRARIAN_HTTP_PORT="$(env_value LAZYLIBRARIAN_HTTP_PORT)"
MYLAR_HTTPS_PORT="$(env_value MYLAR_HTTPS_PORT)"
NZBHYDRA2_HTTPS_PORT="$(env_value NZBHYDRA2_HTTPS_PORT)"
readonly PROWLARR_HTTPS_PORT JELLYFIN_HTTP_PORT JELLYFIN_BASE_URL SONARR_HTTP_PORT \
  RADARR_HTTPS_PORT LIDARR_HTTPS_PORT READARR_HTTPS_PORT WHISPARR_HTTPS_PORT \
  BAZARR_HTTP_PORT LAZYLIBRARIAN_HTTP_PORT MYLAR_HTTPS_PORT NZBHYDRA2_HTTPS_PORT

# ---------------------------------------------------------------------------
# Current (old) API keys — read from config.xml at rotation time
# ---------------------------------------------------------------------------

get_xml_apikey() {
  local xml_file="$1"
  grep -oPm1 '(?<=<ApiKey>)[^<]+' "$xml_file"
}

readonly SONARR_XML="configs/sonarr/config/config.xml"
readonly RADARR_XML="configs/radarr/config/config.xml"
readonly LIDARR_XML="configs/lidarr/config/config.xml"
readonly READARR_XML="configs/readarr/config/config.xml"
readonly WHISPARR_XML="configs/whisparr/config/config.xml"
readonly PROWLARR_XML="configs/prowlarr/config/config.xml"

readonly BAZARR_CONFIG="configs/bazarr/config/config/config.yaml"
readonly RECYCLARR_SECRETS="configs/recyclarr/config/secrets.yml" # pragma: allowlist secret

# Single source of truth for each app's API key, consumed via compose
# `secrets:` by homepage instead of being copied into its .env.secrets.
# See docs/COMPOSE_CONVENTIONS.md.
readonly SONARR_API_KEY_SECRET="configs/sonarr/secrets/api_key.txt"     # pragma: allowlist secret
readonly RADARR_API_KEY_SECRET="configs/radarr/secrets/api_key.txt"     # pragma: allowlist secret
readonly READARR_API_KEY_SECRET="configs/readarr/secrets/api_key.txt"   # pragma: allowlist secret
readonly BAZARR_API_KEY_SECRET="configs/bazarr/secrets/api_key.txt"     # pragma: allowlist secret
readonly PROWLARR_API_KEY_SECRET="configs/prowlarr/secrets/api_key.txt" # pragma: allowlist secret
readonly LIDARR_API_KEY_SECRET="configs/lidarr/secrets/api_key.txt"     # pragma: allowlist secret
readonly WHISPARR_API_KEY_SECRET="configs/whisparr/secrets/api_key.txt" # pragma: allowlist secret
readonly MYLAR_API_KEY_SECRET="configs/mylar/secrets/api_key.txt"       # pragma: allowlist secret
# Jellyfin has no independent source of truth for its own current key (it is
# created/revoked live via Jellyfin's own API); this file is that record.
readonly JELLYFIN_API_KEY_SECRET="configs/jellyfin/secrets/api_key.txt" # pragma: allowlist secret
readonly LAZYLIBRARIAN_INI="configs/lazylibrarian/config/config.ini"
readonly MYLAR_INI="configs/mylar/config/mylar/config.ini"
readonly NZBHYDRA_YML="configs/nzbhydra2/config/nzbhydra.yml"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

gen_key() {
  openssl rand -hex 16
}

mask() {
  local val="$1"
  echo "${val:0:4}****"
}

# Write a value shared via compose `secrets:` (path, not name=value, so it can
# be delivered to consumers spelling it differently, e.g. HOMEPAGE_FILE_*
# alongside an app's own config.xml). No trailing newline: consumers read the
# file's contents verbatim, and homepage substitutes them straight into its
# config. Mode 644: rootless podman maps this host file to uid 0 inside the
# container while the app runs as another UID, so 640/600 are unreadable.
# Args: path new_value
write_secret_file() {
  local path="$1"
  local new_value="$2"
  mkdir -p "$(dirname "$path")"
  printf '%s' "$new_value" >"$path"
  chmod 644 "$path"
}

# Run curl inside the target app's own container, hitting its own loopback
# address directly. Apps aren't published to the host on the current bridge
# network, and this avoids routing admin/rotation traffic through nginx.
# Args: container_name curl_args...
container_curl() {
  local container_name="$1"
  shift
  podman exec "$container_name" curl "$@"
}

# Stop the listed containers if they exist, remembering which ones were
# stopped so start_stopped() can bring exactly those back.
# Podman's default stop timeout is 10 seconds. The servarr apps shut down
# cleanly well inside that when idle (measured: sonarr 3s, prowlarr 3s,
# lazylibrarian 5s), but during bootstrap they can be mid-request when the
# stop lands, and Prowlarr's indexer queries alone can block for up to 100s
# against a slow tracker. When that happens podman escalates to SIGKILL, and
# these apps keep their state in SQLite, which is exactly the "killed
# mid-write" corruption this repo warns about elsewhere. A generous timeout
# is free when they are idle and only spends time when it is preventing that.
#
# Mylar is deliberately exempt: its s6 init never forwards SIGTERM to the app
# (measured: it burns the entire timeout, 45s against a 45s limit, where the
# others take 3-5s), so it is always SIGKILLed regardless. Waiting longer for
# it would add minutes to every bootstrap and change nothing.
readonly STOP_TIMEOUT=60
readonly STOP_TIMEOUT_EXEMPT=(mylar)

stop_container() {
  local c exempt=() normal=()
  for c in "$@"; do
    if [[ " ${STOP_TIMEOUT_EXEMPT[*]} " == *" ${c} "* ]]; then
      exempt+=("$c")
    else
      normal+=("$c")
    fi
  done
  # Both batches run concurrently so an exempt container waiting out its
  # timeout never serializes behind the others.
  if [[ ${#normal[@]} -gt 0 ]]; then
    podman stop --time "$STOP_TIMEOUT" "${normal[@]}" >/dev/null &
  fi
  if [[ ${#exempt[@]} -gt 0 ]]; then
    podman stop "${exempt[@]}" >/dev/null &
  fi
  wait
}

STOPPED_CONTAINERS=()
stop_existing() {
  STOPPED_CONTAINERS=()
  local c
  for c in "$@"; do
    if podman container exists "$c" 2>/dev/null; then
      stop_container "$c"
      STOPPED_CONTAINERS+=("$c")
    fi
  done
}

start_stopped() {
  if [[ ${#STOPPED_CONTAINERS[@]} -gt 0 ]]; then
    podman start "${STOPPED_CONTAINERS[@]}" >/dev/null
  fi
}

# Retry a command every 5 seconds until it succeeds or timeout (in seconds).
retry() {
  local timeout="$1"
  shift
  local elapsed=0
  until "$@" >/dev/null 2>&1; do
    sleep 5
    elapsed=$((elapsed + 5))
    if [[ $elapsed -ge $timeout ]]; then
      return 1
    fi
  done
}

# *arr apps silently ignore apiKey changes sent through the config/host API
# endpoint (it's treated as self-protecting, read-only over that route) — a
# PUT returns 202 but echoes back the unchanged old key. The only way to
# actually change it is to edit config.xml directly and restart the app so it
# re-reads the key into memory at startup.
# Args: app_name container_name xml_path
rotate_arr_apikey() {
  local app_name="$1"
  local container_name="$2"
  local xml_path="$3"
  local new_key
  new_key=$(gen_key)

  # The apps read config.xml only at startup and can rewrite it on state
  # changes, so the edit happens while the container is stopped.
  echo "[$app_name] Stopping container and writing new ApiKey to $xml_path..." >&2
  stop_container "$container_name"

  xmlstarlet --quiet ed --inplace --update '/Config/ApiKey' \
    --value "$new_key" "$xml_path" # pragma: allowlist secret

  local written
  written=$(get_xml_apikey "$xml_path")
  if [[ "$written" != "$new_key" ]]; then
    echo "[$app_name] ERROR: ApiKey did not update as expected in $xml_path" >&2
    podman start "$container_name" >/dev/null
    return 1
  fi

  podman start "$container_name" >/dev/null
  echo "$new_key"
}

# Update one application entry in Prowlarr with a new downstream API key.
# The entry is looked up by name; apps without a Prowlarr application entry
# are skipped, and so is a Prowlarr container that doesn't exist at all
# (PROWLARR_PROFILE=disabled) rather than letting `podman exec` fail the
# whole rotation under `set -e`.
# Args: prowlarr_key app_name new_downstream_key
update_prowlarr_application() {
  local prowlarr_key="$1"
  local app_name="$2"
  local new_key="$3"

  if ! podman container exists prowlarr 2>/dev/null; then
    echo "[Prowlarr] Container doesn't exist, skipping application update for '${app_name}'."
    return 0
  fi

  local app_json
  app_json=$(container_curl prowlarr -sk \
    -H "X-Api-Key: $prowlarr_key" \
    "https://127.0.0.1:${PROWLARR_HTTPS_PORT}/prowlarr/api/v1/applications" |
    jq --arg name "$app_name" 'map(select(.name == $name)) | first')

  if [[ -z "$app_json" || "$app_json" == "null" ]]; then
    echo "[Prowlarr] No application entry named '${app_name}', skipping."
    return 0
  fi

  local app_id
  app_id=$(echo "$app_json" | jq -r '.id')
  echo "[Prowlarr] Updating application '${app_name}' (id=${app_id}) with new key..."

  local updated
  updated=$(echo "$app_json" | jq --arg key "$new_key" \
    '.fields[] |= if .name == "apiKey" then .value = $key else . end')

  # forceSave skips Prowlarr's connection validation: the downstream app has
  # not been restarted with the new key yet at this point (restarts happen at
  # the end), so a validated PUT would always fail with a 401 from the app.
  # --fail surfaces any real API error instead of silently discarding it.
  container_curl prowlarr -sk --fail -X PUT \
    -H "X-Api-Key: $prowlarr_key" \
    -H "Content-Type: application/json" \
    -d "$updated" \
    "https://127.0.0.1:${PROWLARR_HTTPS_PORT}/prowlarr/api/v1/applications/${app_id}?forceSave=true" \
    >/dev/null
}

# When Prowlarr's own API key rotates, every indexer it already pushed into
# a downstream app still carries the *old* key, because Prowlarr embeds its
# current key into an indexer record at sync time and does not refresh it
# on every later sync. Confirmed live: after rotating Prowlarr's key and
# manually re-running ApplicationIndexerSync, LazyLibrarian's Torznab entry
# picked up the new key (Prowlarr updates it there through LazyLibrarian's
# own live "changeprovider" API, which this same command call reaches), but
# Radarr's Indexers row still had the old key in its apiKey field. The arr
# apps need an explicit PUT to their own indexer API to pick up the new key;
# LazyLibrarian/Mylar are already fixed by the resync below.
# Args: new_key
propagate_prowlarr_key() {
  local new_key="$1"

  if ! podman container exists prowlarr 2>/dev/null; then
    return 0
  fi

  if ! retry 120 container_curl prowlarr -sk --fail -o /dev/null --max-time 10 \
    -H "X-Api-Key: ${new_key}" \
    "https://127.0.0.1:${PROWLARR_HTTPS_PORT}/prowlarr/api/v1/system/status"; then
    echo "[Prowlarr] Didn't come back up with the new key in time, skipping indexer key propagation."
    echo "[Prowlarr] Once it's healthy, re-run 'make wire_connections' to fix this."
    return 0
  fi

  echo "[Prowlarr] Re-syncing indexers to registered applications with the new key..."
  container_curl prowlarr -sk --fail -X POST \
    -H "X-Api-Key: ${new_key}" -H "Content-Type: application/json" \
    -d '{"name":"ApplicationIndexerSync"}' \
    "https://127.0.0.1:${PROWLARR_HTTPS_PORT}/prowlarr/api/v1/command" >/dev/null || true
  sleep 15

  local targets=(
    "sonarr http ${SONARR_HTTP_PORT} v3 ${SONARR_XML}"
    "radarr https ${RADARR_HTTPS_PORT} v3 ${RADARR_XML}"
    "lidarr https ${LIDARR_HTTPS_PORT} v1 ${LIDARR_XML}"
    "readarr https ${READARR_HTTPS_PORT} v1 ${READARR_XML}"
    "whisparr https ${WHISPARR_HTTPS_PORT} v3 ${WHISPARR_XML}"
  )
  local entry app scheme port api_version xml_path app_key indexers
  for entry in "${targets[@]}"; do
    read -r app scheme port api_version xml_path <<<"$entry"
    podman container exists "$app" 2>/dev/null || continue
    app_key=$(get_xml_apikey "$xml_path") || continue
    indexers=$(container_curl "$app" -sk --fail -H "X-Api-Key: ${app_key}" \
      "${scheme}://127.0.0.1:${port}/${app}/api/${api_version}/indexer" 2>/dev/null) || continue

    local rec id name updated
    while IFS= read -r rec; do
      [[ -z "$rec" ]] && continue
      id=$(echo "$rec" | jq -r '.id')
      name=$(echo "$rec" | jq -r '.name')
      updated=$(echo "$rec" | jq --arg key "$new_key" \
        '.fields |= map(if .name == "apiKey" then .value = $key else . end)')
      if container_curl "$app" -sk --fail -X PUT -H "X-Api-Key: ${app_key}" \
        -H "Content-Type: application/json" -d "$updated" \
        "${scheme}://127.0.0.1:${port}/${app}/api/${api_version}/indexer/${id}?forceSave=true" >/dev/null; then
        echo "[Prowlarr] Updated ${app}'s indexer '${name}' with the new API key."
      else
        echo "[Prowlarr] WARNING: failed to update ${app}'s indexer '${name}' with the new API key."
      fi
    done < <(echo "$indexers" | jq -c '.[] | select(.fields[]? | .name == "baseUrl" and (.value | test("://prowlarr[:/]")))')
  done

  # LazyLibrarian stores its own copy of Prowlarr's key too, in whichever
  # Torznab_N section Prowlarr's own indexer sync created (see
  # docs/CONNECTIONS.md: LazyLibrarian ships with no Prowlarr Torznab entry
  # of its own, Prowlarr populates it live). This was missing entirely:
  # confirmed live, that section's api value stayed at its pre-sync
  # placeholder across a real rotation. LazyLibrarian persists its config
  # on shutdown like every other INI-configured app in this stack, so the
  # edit needs the same stop-edit-start as rotate_nzbhydra2() already uses
  # for the same file, not a live write.
  if [[ -f "$LAZYLIBRARIAN_INI" ]] && podman container exists lazylibrarian 2>/dev/null; then
    stop_existing lazylibrarian
    python3 - <<PYEOF
from pathlib import Path

new_key = '$new_key'
ll = Path('$LAZYLIBRARIAN_INI')
lines = ll.read_text().splitlines()
section_hosts = {}
current = None
for line in lines:
    if line.startswith('['):
        current = line
    elif line.startswith('host = ') and current:
        section_hosts[current] = line
current = None
for i, line in enumerate(lines):
    if line.startswith('['):
        current = line
    elif line.startswith('api = ') and 'prowlarr' in section_hosts.get(current, '').lower():
        lines[i] = f"api = {new_key}"
ll.write_text("\n".join(lines) + "\n")
PYEOF
    start_stopped
    echo "[Prowlarr] Updated LazyLibrarian's Torznab entry with the new API key."
  fi
}

# ---------------------------------------------------------------------------
# Per-app rotation functions
# ---------------------------------------------------------------------------

rotate_sonarr() {
  local old_key
  old_key=$(get_xml_apikey "$SONARR_XML")
  local new_key
  new_key=$(rotate_arr_apikey "Sonarr" "sonarr" "$SONARR_XML")

  local prowlarr_key
  prowlarr_key=$(get_xml_apikey "$PROWLARR_XML")
  update_prowlarr_application "$prowlarr_key" "Sonarr" "$new_key"

  echo "[Bazarr] Updating sonarr.apikey in config.yaml..."
  yq -i ".sonarr.apikey = \"$new_key\"" "$BAZARR_CONFIG"

  if [[ -f "$RECYCLARR_SECRETS" ]]; then
    echo "[recyclarr] Updating sonarr_apikey in secrets.yml..."
    yq -i ".sonarr_apikey = \"$new_key\"" "$RECYCLARR_SECRETS"
  else
    echo "[recyclarr] $RECYCLARR_SECRETS doesn't exist, skipping."
  fi

  write_secret_file "$SONARR_API_KEY_SECRET" "$new_key"

  SUMMARY_SONARR_OLD="$old_key"
  SUMMARY_SONARR_NEW="$new_key"
}

rotate_radarr() {
  local old_key
  old_key=$(get_xml_apikey "$RADARR_XML")
  local new_key
  new_key=$(rotate_arr_apikey "Radarr" "radarr" "$RADARR_XML")

  local prowlarr_key
  prowlarr_key=$(get_xml_apikey "$PROWLARR_XML")
  update_prowlarr_application "$prowlarr_key" "Radarr" "$new_key"

  echo "[Bazarr] Updating radarr.apikey in config.yaml..."
  yq -i ".radarr.apikey = \"$new_key\"" "$BAZARR_CONFIG"

  if [[ -f "$RECYCLARR_SECRETS" ]]; then
    echo "[recyclarr] Updating radarr_apikey in secrets.yml..."
    yq -i ".radarr_apikey = \"$new_key\"" "$RECYCLARR_SECRETS"
  else
    echo "[recyclarr] $RECYCLARR_SECRETS doesn't exist, skipping."
  fi

  write_secret_file "$RADARR_API_KEY_SECRET" "$new_key"

  SUMMARY_RADARR_OLD="$old_key"
  SUMMARY_RADARR_NEW="$new_key"
}

rotate_lidarr() {
  local old_key
  old_key=$(get_xml_apikey "$LIDARR_XML")
  local new_key
  new_key=$(rotate_arr_apikey "Lidarr" "lidarr" "$LIDARR_XML")

  local prowlarr_key
  prowlarr_key=$(get_xml_apikey "$PROWLARR_XML")
  update_prowlarr_application "$prowlarr_key" "Lidarr" "$new_key"

  write_secret_file "$LIDARR_API_KEY_SECRET" "$new_key"

  SUMMARY_LIDARR_OLD="$old_key"
  SUMMARY_LIDARR_NEW="$new_key"
}

rotate_readarr() {
  local old_key
  old_key=$(get_xml_apikey "$READARR_XML")
  local new_key
  new_key=$(rotate_arr_apikey "Readarr" "readarr" "$READARR_XML")

  local prowlarr_key
  prowlarr_key=$(get_xml_apikey "$PROWLARR_XML")
  update_prowlarr_application "$prowlarr_key" "Readarr" "$new_key"

  write_secret_file "$READARR_API_KEY_SECRET" "$new_key"

  SUMMARY_READARR_OLD="$old_key"
  SUMMARY_READARR_NEW="$new_key"
}

rotate_whisparr() {
  local old_key
  old_key=$(get_xml_apikey "$WHISPARR_XML")
  local new_key
  new_key=$(rotate_arr_apikey "Whisparr" "whisparr" "$WHISPARR_XML")

  local prowlarr_key
  prowlarr_key=$(get_xml_apikey "$PROWLARR_XML")
  update_prowlarr_application "$prowlarr_key" "Whisparr" "$new_key"

  write_secret_file "$WHISPARR_API_KEY_SECRET" "$new_key"

  SUMMARY_WHISPARR_OLD="$old_key"
  SUMMARY_WHISPARR_NEW="$new_key"
}

rotate_prowlarr() {
  local old_key
  old_key=$(get_xml_apikey "$PROWLARR_XML")
  local new_key
  new_key=$(rotate_arr_apikey "Prowlarr" "prowlarr" "$PROWLARR_XML")

  write_secret_file "$PROWLARR_API_KEY_SECRET" "$new_key"

  propagate_prowlarr_key "$new_key"

  SUMMARY_PROWLARR_OLD="$old_key"
  SUMMARY_PROWLARR_NEW="$new_key"
}

rotate_bazarr() {
  # Bazarr does not expose an API endpoint to change its own API key.
  # The key is read from config.yaml and written back directly.
  local old_key
  old_key=$(yq '.auth.apikey' "$BAZARR_CONFIG")
  local new_key
  new_key=$(gen_key)

  # Bazarr reads config.yaml at startup; edit it while stopped.
  echo "[Bazarr] Stopping container and updating auth.apikey in config.yaml..."
  stop_container bazarr
  yq -i ".auth.apikey = \"$new_key\"" "$BAZARR_CONFIG"
  podman start bazarr >/dev/null

  write_secret_file "$BAZARR_API_KEY_SECRET" "$new_key"

  SUMMARY_BAZARR_OLD="$old_key"
  SUMMARY_BAZARR_NEW="$new_key"
}

# LazyLibrarian and Mylar keep their API key as a unique "api_key = ..." line
# in their config.ini and read it only at startup.
get_ini_apikey() {
  grep -oPm1 '(?<=^api_key = ).*' "$1"
}

rotate_lazylibrarian() {
  local old_key new_key
  old_key=$(get_ini_apikey "$LAZYLIBRARIAN_INI")
  new_key=$(gen_key)

  # LazyLibrarian persists its in-memory config on shutdown, which would
  # clobber a live file edit; stop it first, edit, then start.
  echo "[LazyLibrarian] Stopping container and writing new api_key..."
  stop_container lazylibrarian
  sed -i "s|^api_key = .*|api_key = ${new_key}|" "$LAZYLIBRARIAN_INI"
  podman start lazylibrarian >/dev/null

  local prowlarr_key
  prowlarr_key=$(get_xml_apikey "$PROWLARR_XML")
  update_prowlarr_application "$prowlarr_key" "LazyLibrarian" "$new_key"

  SUMMARY_LAZYLIBRARIAN_OLD="$old_key"
  SUMMARY_LAZYLIBRARIAN_NEW="$new_key"
}

rotate_mylar() {
  local old_key new_key
  old_key=$(get_ini_apikey "$MYLAR_INI")
  new_key=$(gen_key)

  # Mylar persists its in-memory config on shutdown, which would clobber a
  # live file edit; stop it first, edit, then start.
  echo "[Mylar] Stopping container and writing new api_key..."
  stop_container mylar
  sed -i "s|^api_key = .*|api_key = ${new_key}|" "$MYLAR_INI"
  podman start mylar >/dev/null

  local prowlarr_key
  prowlarr_key=$(get_xml_apikey "$PROWLARR_XML")
  update_prowlarr_application "$prowlarr_key" "Mylar" "$new_key"

  write_secret_file "$MYLAR_API_KEY_SECRET" "$new_key"

  SUMMARY_MYLAR_OLD="$old_key"
  SUMMARY_MYLAR_NEW="$new_key"
}

rotate_nzbhydra2() {
  # nzbhydra.yml stores the key obfuscated ({OBF}...), so the plain current
  # key is read from a consumer (LazyLibrarian's Newznab entry). Writing a
  # plain value back is fine: NZBHydra re-obfuscates it on its next save.
  local old_key new_key
  old_key=$(grep -oPm1 '(?<=^api = ).*' "$LAZYLIBRARIAN_INI")
  new_key=$(gen_key)

  # NZBHydra2, LazyLibrarian, and Mylar persist their configs on shutdown,
  # and the arr apps' Indexers tables are edited on disk, so everything in
  # the blast radius is stopped for the duration of the edits.
  echo "[NZBHydra2] Stopping consumers for config and database edits..."
  stop_existing nzbhydra2 lazylibrarian mylar sonarr radarr lidarr readarr whisparr

  echo "[NZBHydra2] Writing new main.apiKey to $NZBHYDRA_YML..."
  apiKey="$new_key" yq -i '(.main.apiKey) = strenv(apiKey)' "$NZBHYDRA_YML"

  echo "[NZBHydra2] Updating consumers (arr Indexers tables, LazyLibrarian, Mylar)..."
  python3 - <<PYEOF
import json
import re
import sqlite3
from pathlib import Path

new_key = '$new_key'

dbs = {
    "sonarr": "configs/sonarr/config/sonarr.db",
    "radarr": "configs/radarr/config/radarr.db",
    "lidarr": "configs/lidarr/config/lidarr.db",
    "readarr": "configs/readarr/config/readarr.db",
    "whisparr": "configs/whisparr/config/whisparr3.db",
}
for app, db in dbs.items():
    if not Path(db).exists():
        continue
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    for row_id, raw in cur.execute("SELECT Id, Settings FROM Indexers").fetchall():
        settings = json.loads(raw)
        if "nzbhydra" not in str(settings.get("baseUrl", "")).lower():
            continue
        settings["apiKey"] = new_key
        cur.execute("UPDATE Indexers SET Settings = ? WHERE Id = ?", (json.dumps(settings), row_id))
    conn.commit()
    conn.close()

# LazyLibrarian: api = ... lines inside sections whose host points at NZBHydra
ll = Path('$LAZYLIBRARIAN_INI')
lines = ll.read_text().splitlines()
section_hosts = {}
current = None
for line in lines:
    if line.startswith('['):
        current = line
    elif line.startswith('host = ') and current:
        section_hosts[current] = line
current = None
for i, line in enumerate(lines):
    if line.startswith('['):
        current = line
    elif line.startswith('api = ') and current and 'nzbhydra' in section_hosts.get(current, '').lower():
        lines[i] = f"api = {new_key}"
ll.write_text("\n".join(lines) + "\n")

# Mylar: extra_newznabs/extra_torznabs CSV entries carry the key after the URL
my = Path('$MYLAR_INI')
text = my.read_text()
text = re.sub(
    r"(https?://[^,]*nzbhydra[^,]*,\s*\d+,\s*)[A-Za-z0-9]+",
    lambda m: m.group(1) + new_key,
    text,
)
my.write_text(text)
PYEOF

  start_stopped

  SUMMARY_NZBHYDRA2_OLD="$old_key"
  SUMMARY_NZBHYDRA2_NEW="$new_key"
}

rotate_jellyfin() {
  # Jellyfin API keys are created and revoked through its own API; the value
  # cannot be chosen, so the flow is: create new, adopt it, revoke old. That
  # API only works once Jellyfin's own first-run setup wizard has created an
  # admin account, which nothing in this stack automates (unlike the arr
  # apps' WebUI login, it involves real choices: media libraries, metadata
  # language, remote access) — skip with a note rather than aborting the
  # whole rotation run over a step that's inherently manual.
  local base_url="http://127.0.0.1:${JELLYFIN_HTTP_PORT}${JELLYFIN_BASE_URL}"
  if [[ "$(container_curl jellyfin -s --fail \
    "${base_url}/System/Info/Public" |
    jq -r '.StartupWizardCompleted')" != "true" ]]; then
    echo "[Jellyfin] Setup wizard not completed yet, skipping API key rotation."
    echo "[Jellyfin] Finish it at http://localhost:${JELLYFIN_HTTP_PORT}/, then re-run"
    echo "[Jellyfin] 'make rotate_all SERVICE=jellyfin'."
    return 0
  fi

  local old_key new_key
  old_key=$(cat "$JELLYFIN_API_KEY_SECRET")

  echo "[Jellyfin] Creating a new API key..."
  container_curl jellyfin -s --fail -X POST \
    -H "Authorization: MediaBrowser Token=\"${old_key}\"" \
    "${base_url}/Auth/Keys?App=homepage" >/dev/null

  new_key=$(container_curl jellyfin -s --fail \
    -H "Authorization: MediaBrowser Token=\"${old_key}\"" \
    "${base_url}/Auth/Keys" |
    jq -r --arg old "$old_key" \
      '[.Items[] | select(.AccessToken != $old)] | sort_by(.DateCreated) | last.AccessToken')

  if [[ -z "$new_key" || "$new_key" == "null" ]]; then
    echo "[Jellyfin] ERROR: could not obtain the newly created API key" >&2
    return 1
  fi

  write_secret_file "$JELLYFIN_API_KEY_SECRET" "$new_key"

  echo "[Jellyfin] Revoking the old API key..."
  container_curl jellyfin -s --fail -X DELETE \
    -H "Authorization: MediaBrowser Token=\"${new_key}\"" \
    "${base_url}/Auth/Keys/${old_key}" >/dev/null

  SUMMARY_JELLYFIN_OLD="$old_key"
  SUMMARY_JELLYFIN_NEW="$new_key"
}

# ---------------------------------------------------------------------------
# Summary variables (populated by rotation functions)
# ---------------------------------------------------------------------------

SUMMARY_SONARR_OLD=""
SUMMARY_SONARR_NEW=""
SUMMARY_RADARR_OLD=""
SUMMARY_RADARR_NEW=""
SUMMARY_LIDARR_OLD=""
SUMMARY_LIDARR_NEW=""
SUMMARY_READARR_OLD=""
SUMMARY_READARR_NEW=""
SUMMARY_WHISPARR_OLD=""
SUMMARY_WHISPARR_NEW=""
SUMMARY_PROWLARR_OLD=""
SUMMARY_PROWLARR_NEW=""
SUMMARY_BAZARR_OLD=""
SUMMARY_BAZARR_NEW=""
SUMMARY_LAZYLIBRARIAN_OLD=""
SUMMARY_LAZYLIBRARIAN_NEW=""
SUMMARY_MYLAR_OLD=""
SUMMARY_MYLAR_NEW=""
SUMMARY_NZBHYDRA2_OLD=""
SUMMARY_NZBHYDRA2_NEW=""
SUMMARY_JELLYFIN_OLD=""
SUMMARY_JELLYFIN_NEW=""

# Rotate one service, but only when its compose profile is enabled (and, for
# arr apps, only when the container it needs stopped/exec'd into actually
# exists). Mirrors rotate-passwords.sh's rotate_if_enabled(): in "all" mode a
# disabled service is skipped with a note; an explicitly requested disabled
# service is an error.
# Args: profile_var_prefix container_name rotate_function
rotate_if_enabled() {
  local profile_var="$1" container_name="$2" func="$3"
  if [[ "$(env_value "${profile_var}_PROFILE")" != "enabled" ]]; then
    if [[ "$TARGET" == "all" ]]; then
      echo "[$container_name] Skipped, ${profile_var}_PROFILE is disabled"
      return
    fi
    echo "ERROR: ${profile_var}_PROFILE is disabled in .env; not rotating $container_name" >&2
    exit 1
  fi
  if ! podman container exists "$container_name" 2>/dev/null; then
    if [[ "$TARGET" == "all" ]]; then
      echo "[$container_name] Skipped, container doesn't exist"
      return
    fi
    echo "ERROR: container '$container_name' doesn't exist; not rotating it" >&2
    exit 1
  fi
  "$func"
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

case "$TARGET" in
sonarr) rotate_if_enabled SONARR sonarr rotate_sonarr ;;
radarr) rotate_if_enabled RADARR radarr rotate_radarr ;;
lidarr) rotate_if_enabled LIDARR lidarr rotate_lidarr ;;
readarr) rotate_if_enabled READARR readarr rotate_readarr ;;
whisparr) rotate_if_enabled WHISPARR whisparr rotate_whisparr ;;
prowlarr) rotate_if_enabled PROWLARR prowlarr rotate_prowlarr ;;
bazarr) rotate_if_enabled BAZARR bazarr rotate_bazarr ;;
lazylibrarian) rotate_if_enabled LAZYLIBRARIAN lazylibrarian rotate_lazylibrarian ;;
mylar) rotate_if_enabled MYLAR mylar rotate_mylar ;;
nzbhydra2) rotate_if_enabled NZBHYDRA2 nzbhydra2 rotate_nzbhydra2 ;;
jellyfin) rotate_if_enabled JELLYFIN jellyfin rotate_jellyfin ;;
all)
  rotate_if_enabled SONARR sonarr rotate_sonarr
  rotate_if_enabled RADARR radarr rotate_radarr
  rotate_if_enabled LIDARR lidarr rotate_lidarr
  rotate_if_enabled READARR readarr rotate_readarr
  rotate_if_enabled WHISPARR whisparr rotate_whisparr
  rotate_if_enabled PROWLARR prowlarr rotate_prowlarr
  rotate_if_enabled BAZARR bazarr rotate_bazarr
  rotate_if_enabled LAZYLIBRARIAN lazylibrarian rotate_lazylibrarian
  rotate_if_enabled MYLAR mylar rotate_mylar
  rotate_if_enabled NZBHYDRA2 nzbhydra2 rotate_nzbhydra2
  rotate_if_enabled JELLYFIN jellyfin rotate_jellyfin
  ;;
*)
  echo "Unknown target: $TARGET" >&2
  echo "$USAGE" >&2
  exit 1
  ;;
esac

# ---------------------------------------------------------------------------
# Homepage reads every key this script writes from a bind-mounted secret
# file, not env_file, so a plain restart is enough to pick up new values
# (env_file bakes in at container creation and would need --force-recreate;
# a mounted file's contents are re-read on every restart).
# ---------------------------------------------------------------------------

if podman container exists homepage 2>/dev/null; then
  echo ""
  echo "Restarting homepage to load the new keys..."
  podman restart homepage >/dev/null
fi

# ---------------------------------------------------------------------------
# Host-side SQLite writes above can leave -wal/-shm files owned by the host
# user, which the app user inside the container cannot open after a restart;
# normalize ownership before finishing.
# ---------------------------------------------------------------------------

"$SCRIPT_DIR/permissions.py" repair --runtime podman --recursive >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

echo ""
echo "======================================================================"
echo " API key rotation summary  (shown as: first4****)"
echo "======================================================================"
printf "%-12s  %-12s  %-12s\n" "Service" "Old key" "New key"
echo "----------------------------------------------------------------------"

print_row() {
  local svc="$1" old="$2" new="$3"
  if [[ -n "$old" ]]; then
    printf "%-12s  %-12s  %-12s\n" "$svc" "$(mask "$old")" "$(mask "$new")"
  fi
}

print_row "sonarr" "$SUMMARY_SONARR_OLD" "$SUMMARY_SONARR_NEW"
print_row "radarr" "$SUMMARY_RADARR_OLD" "$SUMMARY_RADARR_NEW"
print_row "lidarr" "$SUMMARY_LIDARR_OLD" "$SUMMARY_LIDARR_NEW"
print_row "readarr" "$SUMMARY_READARR_OLD" "$SUMMARY_READARR_NEW"
print_row "whisparr" "$SUMMARY_WHISPARR_OLD" "$SUMMARY_WHISPARR_NEW"
print_row "prowlarr" "$SUMMARY_PROWLARR_OLD" "$SUMMARY_PROWLARR_NEW"
print_row "bazarr" "$SUMMARY_BAZARR_OLD" "$SUMMARY_BAZARR_NEW"
print_row "lazylibrarian" "$SUMMARY_LAZYLIBRARIAN_OLD" "$SUMMARY_LAZYLIBRARIAN_NEW"
print_row "mylar" "$SUMMARY_MYLAR_OLD" "$SUMMARY_MYLAR_NEW"
print_row "nzbhydra2" "$SUMMARY_NZBHYDRA2_OLD" "$SUMMARY_NZBHYDRA2_NEW"
print_row "jellyfin" "$SUMMARY_JELLYFIN_OLD" "$SUMMARY_JELLYFIN_NEW"

echo "======================================================================"
# ---------------------------------------------------------------------------
# Validation: prove each rotated API key is accepted by its service. Each
# check retries while the restarted container comes back up.
# ---------------------------------------------------------------------------

arr_key_ok() {
  local container="$1" scheme="$2" port="$3" base="$4" api_ver="$5" key="$6"
  container_curl "$container" -sk --fail -o /dev/null -H "X-Api-Key: ${key}" \
    "${scheme}://127.0.0.1:${port}/${base}/api/${api_ver}/health"
}

bazarr_key_ok() {
  container_curl bazarr -s --fail -o /dev/null -H "X-API-KEY: $1" \
    "http://127.0.0.1:${BAZARR_HTTP_PORT}/bazarr/api/system/status"
}

lazylibrarian_key_ok() {
  local body
  # LazyLibrarian serves HTTPS on its port when https_enabled is set
  body=$(container_curl lazylibrarian -sk \
    "https://127.0.0.1:${LAZYLIBRARIAN_HTTP_PORT}/lazylibrarian/api?cmd=getVersion&apikey=$1")
  [[ -n "$body" && "$body" != *"Incorrect API key"* ]]
}

mylar_key_ok() {
  local body
  body=$(container_curl mylar -sk \
    "https://127.0.0.1:${MYLAR_HTTPS_PORT}/mylar/api?cmd=getVersion&apikey=$1")
  [[ -n "$body" && "$body" != *"Incorrect API key"* && "$body" != *"Invalid apikey"* ]]
}

nzbhydra_key_ok() {
  local body
  body=$(container_curl nzbhydra2 -sk \
    "https://127.0.0.1:${NZBHYDRA2_HTTPS_PORT}/nzbhydra2/api?t=caps&apikey=$1")
  [[ -n "$body" && "$body" != *"<error"* ]]
}

jellyfin_key_ok() {
  container_curl jellyfin -s --fail -o /dev/null \
    -H "Authorization: MediaBrowser Token=\"$1\"" \
    "http://127.0.0.1:${JELLYFIN_HTTP_PORT}${JELLYFIN_BASE_URL}/Auth/Keys"
}

VALIDATION_FAILURES=()
validate() {
  local name="$1" timeout="$2"
  shift 2
  if retry "$timeout" "$@"; then
    printf "%-14s  OK\n" "$name"
  else
    printf "%-14s  FAILED\n" "$name"
    VALIDATION_FAILURES+=("$name")
  fi
}

echo ""
echo "======================================================================"
echo " Validating rotated API keys"
echo "======================================================================"
[[ -n "$SUMMARY_SONARR_NEW" ]] && validate sonarr 180 arr_key_ok sonarr http "$SONARR_HTTP_PORT" sonarr v3 "$SUMMARY_SONARR_NEW"
[[ -n "$SUMMARY_RADARR_NEW" ]] && validate radarr 180 arr_key_ok radarr https "$RADARR_HTTPS_PORT" radarr v3 "$SUMMARY_RADARR_NEW"
[[ -n "$SUMMARY_LIDARR_NEW" ]] && validate lidarr 180 arr_key_ok lidarr https "$LIDARR_HTTPS_PORT" lidarr v1 "$SUMMARY_LIDARR_NEW"
[[ -n "$SUMMARY_READARR_NEW" ]] && validate readarr 180 arr_key_ok readarr https "$READARR_HTTPS_PORT" readarr v1 "$SUMMARY_READARR_NEW"
[[ -n "$SUMMARY_WHISPARR_NEW" ]] && validate whisparr 180 arr_key_ok whisparr https "$WHISPARR_HTTPS_PORT" whisparr v3 "$SUMMARY_WHISPARR_NEW"
[[ -n "$SUMMARY_PROWLARR_NEW" ]] && validate prowlarr 180 arr_key_ok prowlarr https "$PROWLARR_HTTPS_PORT" prowlarr v1 "$SUMMARY_PROWLARR_NEW"
[[ -n "$SUMMARY_BAZARR_NEW" ]] && validate bazarr 180 bazarr_key_ok "$SUMMARY_BAZARR_NEW"
[[ -n "$SUMMARY_LAZYLIBRARIAN_NEW" ]] && validate lazylibrarian 180 lazylibrarian_key_ok "$SUMMARY_LAZYLIBRARIAN_NEW"
[[ -n "$SUMMARY_MYLAR_NEW" ]] && validate mylar 300 mylar_key_ok "$SUMMARY_MYLAR_NEW"
[[ -n "$SUMMARY_NZBHYDRA2_NEW" ]] && validate nzbhydra2 240 nzbhydra_key_ok "$SUMMARY_NZBHYDRA2_NEW"
[[ -n "$SUMMARY_JELLYFIN_NEW" ]] && validate jellyfin 120 jellyfin_key_ok "$SUMMARY_JELLYFIN_NEW"
echo "======================================================================"

if [[ ${#VALIDATION_FAILURES[@]} -gt 0 ]]; then
  echo ""
  echo "ERROR: validation failed for: ${VALIDATION_FAILURES[*]}" >&2
  exit 1
fi
