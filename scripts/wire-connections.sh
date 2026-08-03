#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/wire-connections.sh
#
# Wires the app-to-app connections that can only exist through each app's own
# live API: qBittorrent and SABnzbd as download clients inside Sonarr, Radarr,
# Lidarr, Readarr, and Whisparr, and those apps (plus LazyLibrarian and Mylar)
# registered as Applications in Prowlarr, if it's enabled. Along the way it
# also creates each arr app's initial WebUI login (the placeholder
# username/password the README's login table documents) and relaxes
# CertificateValidation for internal addresses, since download client
# creation needs both and nothing else in this stack sets them up.
#
# It also attempts the first-run setup that Jellyfin, Audiobookshelf,
# Calibre's content server, and Calibre-Web each need before they have any
# usable account at all (see the "First-run setup" section below), since
# scripts/rotate-*.sh can't rotate a credential that doesn't exist yet. This
# reliably succeeds for three of the four; Jellyfin's is unreliable for
# reasons not fully understood (see that function's own comment) and often
# needs a one-time manual visit to its web UI instead.
#
# These specifically cannot be seeded from a template the way most of this
# stack's config is: they live in each arr app's SQLite database
# (DownloadClients / Applications tables), which is deliberately never
# tracked or pre-populated (see docs/HARDENING.md). Two related connections
# are NOT handled here because they already work out of the box:
#   - Bazarr's Sonarr/Radarr connections: configs/bazarr/config/config/
#     config.yaml.example already ships ip/port/base_url/ssl plus the same
#     placeholder API key sonarr/radarr's own config.xml.example uses, so
#     they match by construction.
#   - Mylar/LazyLibrarian's qBittorrent/SABnzbd connections: their
#     config.ini.example files are pre-filled the same way, since both apps
#     are configured from a flat file rather than a database.
# See docs/CONNECTIONS.md for the full picture.
#
# Idempotent: every creation is preceded by a check for an existing entry, so
# re-running this after `make start` again, or after rotating credentials, is
# always safe and just confirms everything is still wired.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly REPO_ROOT
cd "$REPO_ROOT"

# Read a variable from .env without sourcing it (.env defines UID, which is a
# readonly bash builtin, so `source .env` fails).
env_value() {
  local key="$1"
  grep -m1 "^${key}=" .env | cut -d= -f2-
}

GLUETUN_SERVICES_IP="$(env_value GLUETUN_SERVICES_IP)"
QBITTORRENT_HTTPS_PORT="$(env_value QBITTORRENT_HTTPS_PORT)"
SABNZBD_HTTP_PORT="$(env_value SABNZBD_HTTP_PORT)"
SONARR_HTTP_PORT="$(env_value SONARR_HTTP_PORT)"
RADARR_HTTPS_PORT="$(env_value RADARR_HTTPS_PORT)"
LIDARR_HTTPS_PORT="$(env_value LIDARR_HTTPS_PORT)"
READARR_HTTPS_PORT="$(env_value READARR_HTTPS_PORT)"
WHISPARR_HTTPS_PORT="$(env_value WHISPARR_HTTPS_PORT)"
PROWLARR_HTTPS_PORT="$(env_value PROWLARR_HTTPS_PORT)"
LAZYLIBRARIAN_HTTP_PORT="$(env_value LAZYLIBRARIAN_HTTP_PORT)"
MYLAR_HTTPS_PORT="$(env_value MYLAR_HTTPS_PORT)"
JELLYFIN_HTTP_PORT="$(env_value JELLYFIN_HTTP_PORT)"
AUDIOBOOKSHELF_HTTP_PORT="$(env_value AUDIOBOOKSHELF_HTTP_PORT)"
readonly GLUETUN_SERVICES_IP QBITTORRENT_HTTPS_PORT SABNZBD_HTTP_PORT \
  SONARR_HTTP_PORT RADARR_HTTPS_PORT LIDARR_HTTPS_PORT READARR_HTTPS_PORT \
  WHISPARR_HTTPS_PORT PROWLARR_HTTPS_PORT LAZYLIBRARIAN_HTTP_PORT MYLAR_HTTPS_PORT \
  JELLYFIN_HTTP_PORT AUDIOBOOKSHELF_HTTP_PORT

readonly SONARR_XML="configs/sonarr/config/config.xml"
readonly RADARR_XML="configs/radarr/config/config.xml"
readonly LIDARR_XML="configs/lidarr/config/config.xml"
readonly READARR_XML="configs/readarr/config/config.xml"
readonly WHISPARR_XML="configs/whisparr/config/config.xml"
readonly PROWLARR_XML="configs/prowlarr/config/config.xml"
readonly LAZYLIBRARIAN_INI="configs/lazylibrarian/config/config.ini"
readonly MYLAR_INI="configs/mylar/config/mylar/config.ini"

readonly QBITTORRENT_USERNAME_FILE="configs/qbittorrent/secrets/username.txt"
readonly QBITTORRENT_PASSWORD_FILE="configs/qbittorrent/secrets/password.txt" # pragma: allowlist secret
readonly SABNZBD_API_KEY_FILE="configs/sabnzbd/secrets/api_key.txt"           # pragma: allowlist secret

readonly JELLYFIN_API_KEY_FILE="configs/jellyfin/secrets/api_key.txt" # pragma: allowlist secret
readonly CALIBRE_USERS_DB_CONTAINER_PATH="/config/.config/calibre/server-users.sqlite"
readonly CALIBRE_PASSWORD_FILE="configs/calibre/secrets/password.txt" # pragma: allowlist secret
readonly CALIBREWEB_DB="configs/calibre-web/config/app.db"
readonly CALIBRE_CONTENT_SERVER_USER="calibre"
readonly CALIBRE_LIBRARY_DIR="/data/media/calibre-library"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

get_xml_apikey() {
  grep -oPm1 '(?<=<ApiKey>)[^<]+' "$1"
}

get_ini_apikey() {
  grep -oPm1 '(?<=^api_key = ).*' "$1"
}

# Run curl inside the target app's own container, hitting its own loopback
# address directly. Apps aren't published to the host on the current bridge
# network. Mirrors scripts/rotate-api-keys.sh's container_curl().
container_curl() {
  local container_name="$1"
  shift
  podman exec "$container_name" curl "$@"
}

# Retry a command every 5 seconds until it succeeds or timeout (in seconds).
# Apps can still be warming up right after `make start`. Prints a heartbeat
# every 30s so a long wait (Jellyfin's Startup/User retry alone can run up
# to 180s) doesn't sit silent with no sign anything is happening.
# Args: timeout label command...
retry() {
  local timeout="$1" label="$2"
  shift 2
  local elapsed=0
  until "$@" >/dev/null 2>&1; do
    sleep 5
    elapsed=$((elapsed + 5))
    if [[ $elapsed -ge $timeout ]]; then
      return 1
    fi
    if ((elapsed % 30 == 0)); then
      echo "${label} ...still waiting (${elapsed}s/${timeout}s)"
    fi
  done
}

# Every unit below (one app's first-run setup, one arr app's download client
# wiring, Prowlarr's application registrations) touches its own container and
# its own config/database, with no dependency on any other unit's result, so
# they all run as background jobs instead of one after another. That matters
# because several of them poll for up to 180s while an app is still warming
# up: run sequentially, worst case adds up (Jellyfin alone can burn 360s);
# run in parallel, the whole batch takes as long as its single slowest job.
# Output streams live rather than being captured and printed after the job
# finishes: every echo in these functions already prefixes its own app name
# (e.g. "[Jellyfin] ..."), so interleaved lines from concurrent jobs stay
# attributable, and a slow job (Calibre-Web, Jellyfin) no longer looks like
# nothing is happening for minutes at a time.
declare -A JOB_PID

start_job() {
  local name="$1"
  shift
  "$@" &
  JOB_PID["$name"]=$!
}

wait_job() {
  local name="$1"
  wait "${JOB_PID[$name]}" || true
}

# ---------------------------------------------------------------------------
# First-run setup
#
# Four apps in this stack ship with no usable account at all until a human
# completes their own first-run setup wizard once: Jellyfin, Audiobookshelf,
# Calibre's content server, and Calibre-Web. Nothing else in this project's
# bootstrap flow creates that initial account, so their credentials were
# previously stuck skipping rotation forever (see docs/ROTATION.md). Each
# one is driven here through its own documented first-run API (Jellyfin,
# Audiobookshelf), a documented non-interactive CLI flag (Calibre's content
# server), or a direct one-time database write while stopped, matching the
# project's existing stop-edit-start convention (Calibre-Web, which has no
# API or env var for this) — using the same placeholder
# username = password = app name convention already used everywhere else.
# ---------------------------------------------------------------------------

ensure_jellyfin_setup() {
  if ! podman container exists jellyfin 2>/dev/null; then
    echo "[Jellyfin] Container doesn't exist, skipping."
    return 0
  fi

  local base_url="http://127.0.0.1:${JELLYFIN_HTTP_PORT}"
  if ! retry 180 "[Jellyfin]" container_curl jellyfin -s --fail "${base_url}/System/Info/Public"; then
    echo "[Jellyfin] Not reachable, skipping."
    return 0
  fi
  if [[ "$(container_curl jellyfin -sS --fail "${base_url}/System/Info/Public" | jq -r '.StartupWizardCompleted')" == "true" ]]; then
    echo "[Jellyfin] Setup wizard already completed, skipping."
    return 0
  fi

  echo "[Jellyfin] Completing first-run setup wizard..."
  container_curl jellyfin -sS --fail -X POST -H "Content-Type: application/json" \
    -d '{"UICulture":"en-US","MetadataCountryCode":"US","PreferredMetadataLanguage":"en"}' \
    "${base_url}/Startup/Configuration" >/dev/null

  # UpdateStartupUser() updates Jellyfin's own lazily-created default user
  # (internally named "abc"), which only exists once something has
  # already triggered UserManager to notice there are no users yet. This
  # is unreliable: in repeated testing against genuinely fresh containers,
  # that trigger sometimes never fired even after 10 continuous minutes of
  # retrying this exact call, with no reproducible cause identified — it
  # is not simply a matter of waiting longer. Retrying for a bounded 180s
  # is a best effort, not a guarantee; when it fails, skip with a note
  # rather than block the rest of setup on it (see docs/CONNECTIONS.md).
  if ! retry 180 "[Jellyfin]" container_curl jellyfin -s --fail -X POST -H "Content-Type: application/json" \
    -d '{"Name":"jellyfin","Password":"jellyfin"}' "${base_url}/Startup/User"; then # pragma: allowlist secret
    echo "[Jellyfin] Startup/User did not succeed after 180s, skipping the rest of setup."
    echo "[Jellyfin] This step is unreliable; visit http://localhost:${JELLYFIN_HTTP_PORT}/"
    echo "[Jellyfin] once in a browser to complete it, then re-run 'make wire_connections'."
    return 0
  fi

  container_curl jellyfin -sS --fail -X POST -H "Content-Type: application/json" \
    -d '{"EnableRemoteAccess":false,"EnableAutomaticPortMapping":false}' \
    "${base_url}/Startup/RemoteAccess" >/dev/null
  container_curl jellyfin -sS --fail -X POST "${base_url}/Startup/Complete" >/dev/null

  echo "[Jellyfin] Creating initial API key..."
  local token
  token=$(container_curl jellyfin -sS --fail -X POST \
    -H "Content-Type: application/json" \
    -H 'X-Emby-Authorization: MediaBrowser Client="wire-connections", Device="bootstrap", DeviceId="bootstrap", Version="1.0.0"' \
    -d '{"Username":"jellyfin","Pw":"jellyfin"}' \
    "${base_url}/Users/AuthenticateByName" | jq -r '.AccessToken')

  container_curl jellyfin -sS --fail -X POST -H "Authorization: MediaBrowser Token=\"${token}\"" \
    "${base_url}/Auth/Keys?App=homepage" >/dev/null
  local api_key
  api_key=$(container_curl jellyfin -sS --fail -H "Authorization: MediaBrowser Token=\"${token}\"" \
    "${base_url}/Auth/Keys" | jq -r '.Items | sort_by(.DateCreated) | last.AccessToken')
  printf '%s' "$api_key" >"$JELLYFIN_API_KEY_FILE"
  chmod 644 "$JELLYFIN_API_KEY_FILE"
  echo "[Jellyfin] Done."
}

# Audiobookshelf's own image ships no curl, only wget (verified directly),
# so this talks to it the same way scripts/rotate-passwords.sh's
# homepage_http() talks to Homepage for the same reason.
ensure_audiobookshelf_setup() {
  if ! podman container exists audiobookshelf 2>/dev/null; then
    echo "[Audiobookshelf] Container doesn't exist, skipping."
    return 0
  fi

  local base_url="http://127.0.0.1:${AUDIOBOOKSHELF_HTTP_PORT}"
  if ! retry 180 "[Audiobookshelf]" podman exec audiobookshelf wget -qO- "${base_url}/status"; then
    echo "[Audiobookshelf] Not reachable, skipping."
    return 0
  fi
  local status
  status=$(podman exec audiobookshelf wget -qO- "${base_url}/status")
  if [[ "$(echo "$status" | jq -r '.isInit')" == "true" ]]; then
    echo "[Audiobookshelf] Already initialized, skipping."
    return 0
  fi

  echo "[Audiobookshelf] Creating initial root user..."
  local init_payload='{"newRoot":{"username":"root","password":"audiobookshelf"}}' # pragma: allowlist secret
  podman exec audiobookshelf wget -qO- --header='Content-Type: application/json' \
    --post-data="$init_payload" "${base_url}/init" >/dev/null
  echo "[Audiobookshelf] Done."
}

# calibre-server --manage-users is a real, non-interactive CLI command
# (verified directly), unlike the desktop GUI/noVNC login, which is already
# usable from its own committed secret file.
ensure_calibre_content_server_user() {
  if ! podman container exists calibre 2>/dev/null; then
    echo "[Calibre] Container doesn't exist, skipping."
    return 0
  fi
  if podman exec calibre calibre-server --userdb "$CALIBRE_USERS_DB_CONTAINER_PATH" \
    --manage-users -- list 2>/dev/null | grep -qx "$CALIBRE_CONTENT_SERVER_USER"; then
    echo "[Calibre] Content server user already exists, skipping."
    return 0
  fi

  echo "[Calibre] Creating content server user..."
  local password
  password=$(cat "$CALIBRE_PASSWORD_FILE")
  podman exec calibre calibre-server --userdb "$CALIBRE_USERS_DB_CONTAINER_PATH" \
    --manage-users -- add "$CALIBRE_CONTENT_SERVER_USER" "$password" >/dev/null
  echo "[Calibre] Done."
}

# Calibre-Web has no API, env var, or config file for this (confirmed by
# inspecting its image and GitHub wiki directly) — only its own admin UI at
# /admin/dbconfig, which every request redirects to until config_calibre_dir
# is set. Writes straight to app.db's settings row while stopped, matching
# this project's established stop-edit-start convention.
#
# This deliberately only sets config_calibre_dir. Also setting
# config_certfile/config_keyfile (Calibre-Web repurposes its single
# config_port for HTTPS once those are set, rather than adding a second
# port) reproducibly wiped the entire `user` table on the very next start —
# including the built-in "Guest" row — in live testing; the mechanism
# wasn't identified in the time available, so this stays off rather than
# risk it. See docs/ROTATION.md: Calibre-Web is only ever configured for
# plain HTTP here, and its default admin user keeps the image's own
# hardcoded username ("admin"), not this project's usual per-app placeholder.
calibre_web_db_ready() {
  python3 - <<PYEOF
import sqlite3, sys
conn = sqlite3.connect('$CALIBREWEB_DB')
row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'").fetchone()
conn.close()
sys.exit(0 if row else 1)
PYEOF
}

ensure_calibre_web_setup() {
  if ! podman container exists calibre-web 2>/dev/null; then
    echo "[Calibre-Web] Container doesn't exist, skipping."
    return 0
  fi
  # app.db's own schema (created by Calibre-Web itself on first boot) may
  # not exist yet the moment the container is created, especially since it
  # reinstalls its Calibre mod on every start.
  if ! retry 180 "[Calibre-Web]" calibre_web_db_ready; then
    echo "[Calibre-Web] app.db not initialized yet after 180s, skipping."
    return 0
  fi

  local configured
  configured=$(
    python3 - <<PYEOF
import sqlite3
conn = sqlite3.connect('$CALIBREWEB_DB')
row = conn.execute('SELECT config_calibre_dir FROM settings WHERE id = 1').fetchone()
conn.close()
print('yes' if row and row[0] else 'no')
PYEOF
  )
  if [[ "$configured" == "yes" ]]; then
    echo "[Calibre-Web] Already configured, skipping."
    return 0
  fi

  echo "[Calibre-Web] Configuring library path..."
  podman stop calibre-web >/dev/null
  # app.db was just created live by the container under its own remapped
  # UID; the one-time `permissions.py repair` earlier in bootstrap ran
  # before this file existed, so it isn't host-writable yet without this.
  ./scripts/permissions.py repair --runtime podman --recursive >/dev/null 2>&1 || true
  python3 - <<PYEOF
import sqlite3
conn = sqlite3.connect('$CALIBREWEB_DB')
conn.execute(
    "UPDATE settings SET config_calibre_dir = ? WHERE id = 1",
    ('$CALIBRE_LIBRARY_DIR',),
)
conn.commit()
conn.close()
PYEOF
  podman start calibre-web >/dev/null
  echo "[Calibre-Web] Done."
}

# ---------------------------------------------------------------------------
# Arr app host prerequisites
#
# Two things block every download client POST below until they're in place,
# and both live in config/host rather than config.xml (config.xml only holds
# the small set of bootstrap settings the app needs before its database is
# available):
#   - CertificateValidation defaults to "enabled", which rejects this stack's
#     self-signed cert on qBittorrent/SABnzbd's internal addresses.
#   - AuthenticationMethod=Forms requires a non-empty username/password
#     before config/host accepts ANY update, including one that only touches
#     CertificateValidation (FluentValidation validates the whole object).
#     Nothing else in this stack creates that initial WebUI login, so it's
#     done here using the same per-app placeholder credential (username =
#     password = app name) the README's login table already documents.
# ---------------------------------------------------------------------------

# Args: app_name container scheme port api_ver api_key
ensure_arr_host_prereqs() {
  local app_name="$1" container="$2" scheme="$3" port="$4" api_ver="$5" api_key="$6"
  local base_url="${scheme}://127.0.0.1:${port}/${app_name}/api/${api_ver}/config/host"

  local current
  current=$(container_curl "$container" -sk --fail -H "X-Api-Key: ${api_key}" "$base_url")
  if [[ "$(echo "$current" | jq -r '.username')" != "" ]]; then
    echo "[$app_name] WebUI login already set up, skipping."
    return 0
  fi

  echo "[$app_name] Setting up initial WebUI login and relaxing certificate validation for internal addresses..."
  local id updated
  id=$(echo "$current" | jq -r '.id')
  updated=$(echo "$current" | jq \
    --arg cred "$app_name" \
    '.username = $cred | .password = $cred | .passwordConfirmation = $cred |
    .certificateValidation = "disabledForLocalAddresses"')

  container_curl "$container" -sk --fail -X PUT \
    -H "X-Api-Key: ${api_key}" -H "Content-Type: application/json" \
    -d "$updated" "${base_url}/${id}" >/dev/null # pragma: allowlist secret
  echo "[$app_name] Done."
}

# ---------------------------------------------------------------------------
# Download clients (Sonarr/Radarr/Lidarr/Readarr/Whisparr -> qBittorrent/SABnzbd)
#
# Rather than hand-building the fields array, this fetches the app's own
# /downloadclient/schema for the implementation, which already carries every
# field at its sensible default, and only overrides the handful of fields
# that are actually connection-specific. The category is always passed
# explicitly rather than trusted from either implementation's schema
# default: qBittorrent's own categories.json uses each app's bare name
# (radarr, sonarr, ...), but e.g. Sonarr's own qBittorrent schema defaults
# tvCategory to "tv-sonarr" instead of "sonarr" — qBittorrent doesn't
# validate the category on creation, it just silently auto-creates an empty
# one, which would silently break the pre-configured save-path layout.
# SABnzbd's genre-based categories (tv, movies, ebooks, ...) are unrelated
# to qBittorrent's app-named ones, so each caller passes both explicitly.
# ---------------------------------------------------------------------------

# Args: app_name container scheme port api_ver api_key category
ensure_qbittorrent_client() {
  local app_name="$1" container="$2" scheme="$3" port="$4" api_ver="$5" api_key="$6" category="$7"
  local base_url="${scheme}://127.0.0.1:${port}/${app_name}/api/${api_ver}/downloadclient"

  local existing
  existing=$(container_curl "$container" -sk --fail -H "X-Api-Key: ${api_key}" "$base_url" |
    jq 'map(select(.implementation == "QBittorrent")) | first')
  if [[ -n "$existing" && "$existing" != "null" ]]; then
    echo "[$app_name] qBittorrent download client already exists, skipping."
    return 0
  fi

  local username password
  username=$(cat "$QBITTORRENT_USERNAME_FILE")
  password=$(cat "$QBITTORRENT_PASSWORD_FILE")

  echo "[$app_name] Creating qBittorrent download client..."
  local schema
  schema=$(container_curl "$container" -sk --fail -H "X-Api-Key: ${api_key}" "${base_url}/schema" |
    jq 'map(select(.implementation == "QBittorrent")) | first')

  local payload
  payload=$(echo "$schema" | jq \
    --arg host "$GLUETUN_SERVICES_IP" \
    --arg port "$QBITTORRENT_HTTPS_PORT" \
    --arg username "$username" \
    --arg password "$password" \
    --arg category "$category" \
    '.name = "QBittorrent" | .enable = true |
    .fields |= map(
      if .name == "host" then .value = $host
      elif .name == "port" then .value = ($port | tonumber)
      elif .name == "useSsl" then .value = true
      elif .name == "username" then .value = $username
      elif .name == "password" then .value = $password
      elif (.name | test("Category$")) and ((.name | test("Imported")) | not) then .value = $category
      else . end)')

  container_curl "$container" -sk --fail -X POST \
    -H "X-Api-Key: ${api_key}" -H "Content-Type: application/json" \
    -d "$payload" "$base_url" >/dev/null # pragma: allowlist secret
  echo "[$app_name] Created."
}

# Args: app_name container scheme port api_ver api_key category
ensure_sabnzbd_client() {
  local app_name="$1" container="$2" scheme="$3" port="$4" api_ver="$5" api_key="$6" category="$7"
  local base_url="${scheme}://127.0.0.1:${port}/${app_name}/api/${api_ver}/downloadclient"

  local existing
  existing=$(container_curl "$container" -sk --fail -H "X-Api-Key: ${api_key}" "$base_url" |
    jq 'map(select(.implementation == "Sabnzbd")) | first')
  if [[ -n "$existing" && "$existing" != "null" ]]; then
    echo "[$app_name] SABnzbd download client already exists, skipping."
    return 0
  fi

  local sab_api_key
  sab_api_key=$(cat "$SABNZBD_API_KEY_FILE")

  echo "[$app_name] Creating SABnzbd download client..."
  local schema
  schema=$(container_curl "$container" -sk --fail -H "X-Api-Key: ${api_key}" "${base_url}/schema" |
    jq 'map(select(.implementation == "Sabnzbd")) | first')

  local payload
  payload=$(echo "$schema" | jq \
    --arg host "$GLUETUN_SERVICES_IP" \
    --arg port "$SABNZBD_HTTP_PORT" \
    --arg urlBase "/sabnzbd" \
    --arg apiKey "$sab_api_key" \
    --arg category "$category" \
    '.name = "SABnzbd" | .enable = true |
    .fields |= map(
      if .name == "host" then .value = $host
      elif .name == "port" then .value = ($port | tonumber)
      elif .name == "useSsl" then .value = false
      elif .name == "urlBase" then .value = $urlBase
      elif .name == "apiKey" then .value = $apiKey
      elif (.name | test("Category$")) and ((.name | test("Imported")) | not) then .value = $category
      else . end)')

  container_curl "$container" -sk --fail -X POST \
    -H "X-Api-Key: ${api_key}" -H "Content-Type: application/json" \
    -d "$payload" "$base_url" >/dev/null # pragma: allowlist secret
  echo "[$app_name] Created."
}

# ---------------------------------------------------------------------------
# Arr app dispatch: host prereqs plus both download clients for one app.
# curl's -k is harmless against a plain http:// URL (Sonarr's own scheme),
# so every caller can pass it uniformly rather than branching on scheme.
# ---------------------------------------------------------------------------

# Args: app_name container scheme port api_ver qbit_category sab_category
wire_arr_app() {
  local app_name="$1" container="$2" scheme="$3" port="$4" api_ver="$5"
  local qbit_category="$6" sab_category="$7"
  local xml="configs/${app_name}/config/config.xml"

  if ! podman container exists "$container" 2>/dev/null; then
    echo "[$app_name] Container does not exist, skipping."
    return 0
  fi

  if ! retry 180 "[$app_name]" container_curl "$container" -sk --fail -H "X-Api-Key: $(get_xml_apikey "$xml")" \
    "${scheme}://127.0.0.1:${port}/${app_name}/api/${api_ver}/system/status"; then
    echo "[$app_name] Not reachable, skipping."
    return 0
  fi

  local key
  key=$(get_xml_apikey "$xml")
  ensure_arr_host_prereqs "$app_name" "$container" "$scheme" "$port" "$api_ver" "$key"
  ensure_qbittorrent_client "$app_name" "$container" "$scheme" "$port" "$api_ver" "$key" "$qbit_category"
  ensure_sabnzbd_client "$app_name" "$container" "$scheme" "$port" "$api_ver" "$key" "$sab_category"
}

# ---------------------------------------------------------------------------
# Prowlarr Applications (Sonarr/Radarr/Lidarr/Readarr/Whisparr/LazyLibrarian/
# Mylar registered so Prowlarr can push indexer sync to them). Skipped
# entirely if the prowlarr container doesn't exist, matching how
# scripts/rotate-api-keys.sh's update_prowlarr_application() already treats
# a missing entry as a no-op rather than an error.
# ---------------------------------------------------------------------------

wire_prowlarr_apps() {
  if ! podman container exists prowlarr 2>/dev/null; then
    echo "[Prowlarr] Container doesn't exist (PROWLARR_PROFILE=disabled), skipping."
    return 0
  fi
  if ! retry 180 "[Prowlarr]" container_curl prowlarr -sk --fail -H "X-Api-Key: $(get_xml_apikey "$PROWLARR_XML")" \
    "https://127.0.0.1:${PROWLARR_HTTPS_PORT}/prowlarr/api/v1/system/status"; then
    echo "[Prowlarr] Not reachable, skipping."
    return 0
  fi

  local prowlarr_key
  prowlarr_key=$(get_xml_apikey "$PROWLARR_XML")

  # Every other arr app gets this from wire_arr_app; Prowlarr itself never
  # went through that dispatch, so without this its own WebUI login was
  # never initialized (username stays empty), which rotate_prowlarr's
  # password-only PUT can't fix on its own since it never sets a username.
  # Confirmed live: password rotation silently "succeeded" but login
  # validation then failed for the full 180s retry, since the real
  # username was still empty, not "prowlarr".
  ensure_arr_host_prereqs prowlarr prowlarr https "$PROWLARR_HTTPS_PORT" v1 "$prowlarr_key"

  # https, not http, despite the port variable's name: LazyLibrarian
  # repurposes its single configured port for HTTPS once https_enabled=True
  # (the shipped default in config.ini.example), the same way Calibre-Web
  # does, rather than adding a second port. nginx's own upstream definition
  # already accounts for this (LAZYLIBRARIAN_UPSTREAM_SCHEME=https paired
  # with LAZYLIBRARIAN_HTTP_PORT); this call didn't, and Prowlarr's POST
  # failed outright when it tried to verify connectivity to the wrong
  # scheme, aborting the rest of this function under set -e, confirmed live
  # by the "Connection reset by peer" a plain http request gets back.
  ensure_prowlarr_application lazylibrarian "LazyLibrarian" "LazyLibrarian" "LazyLibrarianSettings" \
    "https://lazylibrarian:${LAZYLIBRARIAN_HTTP_PORT}/lazylibrarian" \
    "$(get_ini_apikey "$LAZYLIBRARIAN_INI")" "$prowlarr_key"

  ensure_prowlarr_application lidarr "Lidarr" "Lidarr" "LidarrSettings" \
    "https://lidarr:${LIDARR_HTTPS_PORT}/lidarr" "$(get_xml_apikey "$LIDARR_XML")" "$prowlarr_key"

  ensure_prowlarr_application mylar "Mylar" "Mylar" "MylarSettings" \
    "https://mylar:${MYLAR_HTTPS_PORT}/mylar" "$(get_ini_apikey "$MYLAR_INI")" "$prowlarr_key"

  ensure_prowlarr_application radarr "Radarr" "Radarr" "RadarrSettings" \
    "https://radarr:${RADARR_HTTPS_PORT}/radarr" "$(get_xml_apikey "$RADARR_XML")" "$prowlarr_key"

  ensure_prowlarr_application readarr "Readarr" "Readarr" "ReadarrSettings" \
    "https://readarr:${READARR_HTTPS_PORT}/readarr" "$(get_xml_apikey "$READARR_XML")" "$prowlarr_key"

  ensure_prowlarr_application sonarr "Sonarr" "Sonarr" "SonarrSettings" \
    "http://sonarr:${SONARR_HTTP_PORT}/sonarr" "$(get_xml_apikey "$SONARR_XML")" "$prowlarr_key"

  ensure_prowlarr_application whisparr "Whisparr" "Whisparr" "WhisparrSettings" \
    "https://whisparr:${WHISPARR_HTTPS_PORT}/whisparr" "$(get_xml_apikey "$WHISPARR_XML")" "$prowlarr_key"
}

# Args: container display_name implementation config_contract app_url app_api_key prowlarr_api_key
ensure_prowlarr_application() {
  local container="$1" display_name="$2" implementation="$3" config_contract="$4"
  local app_url="$5" app_api_key="$6"
  local prowlarr_api_key="$7"
  local base_url="https://127.0.0.1:${PROWLARR_HTTPS_PORT}/prowlarr/api/v1/applications"

  # A disabled app's container doesn't exist, so there's nothing to
  # register and no point asking Prowlarr to test connectivity to a host
  # that isn't there. Every entry in this dispatch runs sequentially in
  # one function, so skipping cleanly here (like every other ensure_*
  # helper in this file already does) matters beyond just this one app:
  # one entry failing outright used to abort every entry after it too,
  # confirmed live when a wrong URL scheme for one app silently prevented
  # every other app from ever being registered.
  if ! podman container exists "$container" 2>/dev/null; then
    echo "[Prowlarr] ${display_name} container doesn't exist, skipping registration."
    return 0
  fi

  local existing
  existing=$(container_curl prowlarr -sk --fail -H "X-Api-Key: ${prowlarr_api_key}" "$base_url" |
    jq --arg name "$display_name" 'map(select(.name == $name)) | first')
  if [[ -n "$existing" && "$existing" != "null" ]]; then
    echo "[Prowlarr] Application '${display_name}' already exists, skipping."
    return 0
  fi

  echo "[Prowlarr] Registering application '${display_name}'..."
  local schema
  schema=$(container_curl prowlarr -sk --fail -H "X-Api-Key: ${prowlarr_api_key}" "${base_url}/schema" |
    jq --arg impl "$implementation" 'map(select(.implementation == $impl)) | first')

  local payload
  payload=$(echo "$schema" | jq \
    --arg name "$display_name" \
    --arg prowlarrUrl "https://prowlarr:${PROWLARR_HTTPS_PORT}/prowlarr" \
    --arg baseUrl "$app_url" \
    --arg apiKey "$app_api_key" \
    '.name = $name | .syncLevel = "fullSync" |
    .fields |= map(
      if .name == "prowlarrUrl" then .value = $prowlarrUrl
      elif .name == "baseUrl" then .value = $baseUrl
      elif .name == "apiKey" then .value = $apiKey
      else . end)')

  container_curl prowlarr -sk --fail -X POST \
    -H "X-Api-Key: ${prowlarr_api_key}" -H "Content-Type: application/json" \
    -d "$payload" "$base_url" >/dev/null # pragma: allowlist secret
  echo "[Prowlarr] Registered."
}

# ---------------------------------------------------------------------------
# Dispatch — alphabetical by service, matching the convention documented in
# docs/ROTATION.md for the sibling rotation scripts.
# ---------------------------------------------------------------------------

# All ten jobs are launched together, immediately after this one combined
# header, and their output streams live rather than being sorted into
# separate per-section headers: every echo in these functions already
# prefixes its own app name (e.g. "[Jellyfin] ..."), so a single stream of
# self-labeled lines from ten concurrent jobs stays readable without needing
# a fixed section to sort each line under. Waiting on the jobs afterward
# just lets the script exit only once everything is actually done; the
# order below doesn't gate when each job's output appears on screen.
echo "======================================================================"
echo " First-run setup, download client wiring, and Prowlarr registration"
echo " (running concurrently; each line is prefixed with its own app name)"
echo "======================================================================"
start_job audiobookshelf ensure_audiobookshelf_setup
start_job calibre ensure_calibre_content_server_user
start_job calibre-web ensure_calibre_web_setup
start_job jellyfin ensure_jellyfin_setup
start_job lidarr wire_arr_app lidarr lidarr https "$LIDARR_HTTPS_PORT" v1 lidarr music
start_job radarr wire_arr_app radarr radarr https "$RADARR_HTTPS_PORT" v3 radarr movies
start_job readarr wire_arr_app readarr readarr https "$READARR_HTTPS_PORT" v1 readarr ebooks
start_job sonarr wire_arr_app sonarr sonarr http "$SONARR_HTTP_PORT" v3 sonarr tv
start_job whisparr wire_arr_app whisparr whisparr https "$WHISPARR_HTTPS_PORT" v3 whisparr mature
start_job prowlarr wire_prowlarr_apps

for name in audiobookshelf calibre calibre-web jellyfin \
  lidarr radarr readarr sonarr whisparr prowlarr; do
  wait_job "$name"
done

echo ""
echo "======================================================================"
echo " Done. Bazarr's Sonarr/Radarr connections and Mylar/LazyLibrarian's"
echo " qBittorrent/SABnzbd connections are pre-wired via their .example"
echo " templates and need no action here. See docs/CONNECTIONS.md."
echo "======================================================================"
