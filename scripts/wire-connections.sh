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
readonly GLUETUN_SERVICES_IP QBITTORRENT_HTTPS_PORT SABNZBD_HTTP_PORT \
  SONARR_HTTP_PORT RADARR_HTTPS_PORT LIDARR_HTTPS_PORT READARR_HTTPS_PORT \
  WHISPARR_HTTPS_PORT PROWLARR_HTTPS_PORT LAZYLIBRARIAN_HTTP_PORT MYLAR_HTTPS_PORT

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
# Apps can still be warming up right after `make start`.
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
# Prowlarr Applications (Sonarr/Radarr/Lidarr/Readarr/Whisparr/LazyLibrarian/
# Mylar registered so Prowlarr can push indexer sync to them). Skipped
# entirely if the prowlarr container doesn't exist, matching how
# scripts/rotate-api-keys.sh's update_prowlarr_application() already treats
# a missing entry as a no-op rather than an error.
# ---------------------------------------------------------------------------

# Args: display_name implementation config_contract app_url app_api_key
ensure_prowlarr_application() {
  local display_name="$1" implementation="$2" config_contract="$3"
  local app_url="$4" app_api_key="$5"
  local prowlarr_api_key="$6"
  local base_url="https://127.0.0.1:${PROWLARR_HTTPS_PORT}/prowlarr/api/v1/applications"

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

echo "======================================================================"
echo " Wiring download clients"
echo "======================================================================"

if retry 180 container_curl lidarr -sk --fail -H "X-Api-Key: $(get_xml_apikey "$LIDARR_XML")" \
  "https://127.0.0.1:${LIDARR_HTTPS_PORT}/lidarr/api/v1/system/status"; then
  key=$(get_xml_apikey "$LIDARR_XML")
  ensure_arr_host_prereqs lidarr lidarr https "$LIDARR_HTTPS_PORT" v1 "$key"
  ensure_qbittorrent_client lidarr lidarr https "$LIDARR_HTTPS_PORT" v1 "$key" lidarr
  ensure_sabnzbd_client lidarr lidarr https "$LIDARR_HTTPS_PORT" v1 "$key" music
else
  echo "[lidarr] Not reachable, skipping."
fi

if retry 180 container_curl radarr -sk --fail -H "X-Api-Key: $(get_xml_apikey "$RADARR_XML")" \
  "https://127.0.0.1:${RADARR_HTTPS_PORT}/radarr/api/v3/system/status"; then
  key=$(get_xml_apikey "$RADARR_XML")
  ensure_arr_host_prereqs radarr radarr https "$RADARR_HTTPS_PORT" v3 "$key"
  ensure_qbittorrent_client radarr radarr https "$RADARR_HTTPS_PORT" v3 "$key" radarr
  ensure_sabnzbd_client radarr radarr https "$RADARR_HTTPS_PORT" v3 "$key" movies
else
  echo "[radarr] Not reachable, skipping."
fi

if retry 180 container_curl readarr -sk --fail -H "X-Api-Key: $(get_xml_apikey "$READARR_XML")" \
  "https://127.0.0.1:${READARR_HTTPS_PORT}/readarr/api/v1/system/status"; then
  key=$(get_xml_apikey "$READARR_XML")
  ensure_arr_host_prereqs readarr readarr https "$READARR_HTTPS_PORT" v1 "$key"
  ensure_qbittorrent_client readarr readarr https "$READARR_HTTPS_PORT" v1 "$key" readarr
  ensure_sabnzbd_client readarr readarr https "$READARR_HTTPS_PORT" v1 "$key" ebooks
else
  echo "[readarr] Not reachable, skipping."
fi

if retry 180 container_curl sonarr -s --fail -H "X-Api-Key: $(get_xml_apikey "$SONARR_XML")" \
  "http://127.0.0.1:${SONARR_HTTP_PORT}/sonarr/api/v3/system/status"; then
  key=$(get_xml_apikey "$SONARR_XML")
  ensure_arr_host_prereqs sonarr sonarr http "$SONARR_HTTP_PORT" v3 "$key"
  ensure_qbittorrent_client sonarr sonarr http "$SONARR_HTTP_PORT" v3 "$key" sonarr
  ensure_sabnzbd_client sonarr sonarr http "$SONARR_HTTP_PORT" v3 "$key" tv
else
  echo "[sonarr] Not reachable, skipping."
fi

if retry 180 container_curl whisparr -sk --fail -H "X-Api-Key: $(get_xml_apikey "$WHISPARR_XML")" \
  "https://127.0.0.1:${WHISPARR_HTTPS_PORT}/whisparr/api/v3/system/status"; then
  key=$(get_xml_apikey "$WHISPARR_XML")
  ensure_arr_host_prereqs whisparr whisparr https "$WHISPARR_HTTPS_PORT" v3 "$key"
  ensure_qbittorrent_client whisparr whisparr https "$WHISPARR_HTTPS_PORT" v3 "$key" whisparr
  ensure_sabnzbd_client whisparr whisparr https "$WHISPARR_HTTPS_PORT" v3 "$key" mature
else
  echo "[whisparr] Not reachable, skipping."
fi

echo ""
echo "======================================================================"
echo " Wiring Prowlarr applications"
echo "======================================================================"

if ! podman container exists prowlarr 2>/dev/null; then
  echo "[Prowlarr] Container doesn't exist (PROWLARR_PROFILE=disabled), skipping."
elif ! retry 180 container_curl prowlarr -sk --fail -H "X-Api-Key: $(get_xml_apikey "$PROWLARR_XML")" \
  "https://127.0.0.1:${PROWLARR_HTTPS_PORT}/prowlarr/api/v1/system/status"; then
  echo "[Prowlarr] Not reachable, skipping."
else
  prowlarr_key=$(get_xml_apikey "$PROWLARR_XML")

  ensure_prowlarr_application "LazyLibrarian" "LazyLibrarian" "LazyLibrarianSettings" \
    "http://lazylibrarian:${LAZYLIBRARIAN_HTTP_PORT}/lazylibrarian" \
    "$(get_ini_apikey "$LAZYLIBRARIAN_INI")" "$prowlarr_key"

  ensure_prowlarr_application "Lidarr" "Lidarr" "LidarrSettings" \
    "https://lidarr:${LIDARR_HTTPS_PORT}/lidarr" "$(get_xml_apikey "$LIDARR_XML")" "$prowlarr_key"

  ensure_prowlarr_application "Mylar" "Mylar" "MylarSettings" \
    "https://mylar:${MYLAR_HTTPS_PORT}/mylar" "$(get_ini_apikey "$MYLAR_INI")" "$prowlarr_key"

  ensure_prowlarr_application "Radarr" "Radarr" "RadarrSettings" \
    "https://radarr:${RADARR_HTTPS_PORT}/radarr" "$(get_xml_apikey "$RADARR_XML")" "$prowlarr_key"

  ensure_prowlarr_application "Readarr" "Readarr" "ReadarrSettings" \
    "https://readarr:${READARR_HTTPS_PORT}/readarr" "$(get_xml_apikey "$READARR_XML")" "$prowlarr_key"

  ensure_prowlarr_application "Sonarr" "Sonarr" "SonarrSettings" \
    "http://sonarr:${SONARR_HTTP_PORT}/sonarr" "$(get_xml_apikey "$SONARR_XML")" "$prowlarr_key"

  ensure_prowlarr_application "Whisparr" "Whisparr" "WhisparrSettings" \
    "https://whisparr:${WHISPARR_HTTPS_PORT}/whisparr" "$(get_xml_apikey "$WHISPARR_XML")" "$prowlarr_key"
fi

echo ""
echo "======================================================================"
echo " Done. Bazarr's Sonarr/Radarr connections and Mylar/LazyLibrarian's"
echo " qBittorrent/SABnzbd connections are pre-wired via their .example"
echo " templates and need no action here. See docs/CONNECTIONS.md."
echo "======================================================================"
