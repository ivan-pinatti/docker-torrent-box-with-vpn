#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/rotate-api-keys.sh [sonarr|radarr|lidarr|readarr|whisparr|prowlarr|bazarr|all]
# Must be run from repo root.

readonly USAGE="Usage: $0 [sonarr|radarr|lidarr|readarr|whisparr|prowlarr|bazarr|all]"

if [[ $# -ne 1 ]]; then
  echo "$USAGE" >&2
  exit 1
fi

readonly TARGET="$1"

# Container names that need a restart at the end for a rewritten ApiKey to
# take effect (populated by rotate_arr_apikey).
RESTART_NEEDED=()

# Read the network and port variables we need from .env without sourcing it
# (.env defines UID, which is a readonly bash builtin, so `source .env` fails).
env_value() {
  local key="$1"
  grep -m1 "^${key}=" .env | cut -d= -f2-
}

PROWLARR_HTTPS_PORT="$(env_value PROWLARR_HTTPS_PORT)"
readonly PROWLARR_HTTPS_PORT

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
readonly HOMEPAGE_ENV="configs/homepage/.env.secrets"

# Prowlarr application IDs
readonly PROWLARR_APP_ID_LIDARR=1
readonly PROWLARR_APP_ID_READARR=2
readonly PROWLARR_APP_ID_SONARR=3
readonly PROWLARR_APP_ID_RADARR=5
readonly PROWLARR_APP_ID_WHISPARR=7

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

gen_key() {
  openssl rand -hex 16
}

# Update a HOMEPAGE_VAR_* entry in configs/homepage/.env.
# Args: var_name new_value
update_homepage_env() {
  local var_name="$1"
  local new_value="$2"
  echo "[Homepage] Updating ${var_name} in ${HOMEPAGE_ENV}..."
  sed -i "s|^${var_name}=.*|${var_name}=${new_value}|" "$HOMEPAGE_ENV"
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

  echo "[$app_name] Writing new ApiKey to $xml_path..." >&2
  xmlstarlet --quiet ed --inplace --update '/Config/ApiKey' \
    --value "$new_key" "$xml_path" # pragma: allowlist secret

  local written
  written=$(get_xml_apikey "$xml_path")
  if [[ "$written" != "$new_key" ]]; then
    echo "[$app_name] ERROR: ApiKey did not update as expected in $xml_path" >&2
    return 1
  fi

  # NOTE: RESTART_NEEDED can't be appended here — this function's output is
  # captured via $(...), which runs it in a subshell, so array mutations here
  # would be lost. Callers append container_name to RESTART_NEEDED themselves.
  echo "$new_key"
}

# Update one application entry in Prowlarr with a new downstream API key.
# Args: prowlarr_key app_id app_name new_downstream_key
update_prowlarr_application() {
  local prowlarr_key="$1"
  local app_id="$2"
  local app_name="$3"
  local new_key="$4"

  echo "[Prowlarr] Updating application '${app_name}' (id=${app_id}) with new key..."

  local app_json
  app_json=$(container_curl prowlarr -sk \
    -H "X-Api-Key: $prowlarr_key" \
    "https://127.0.0.1:${PROWLARR_HTTPS_PORT}/prowlarr/api/v1/applications/${app_id}")

  local updated
  updated=$(echo "$app_json" | jq --arg key "$new_key" \
    '.fields[] |= if .name == "apiKey" then .value = $key else . end')

  container_curl prowlarr -sk -X PUT \
    -H "X-Api-Key: $prowlarr_key" \
    -H "Content-Type: application/json" \
    -d "$updated" \
    "https://127.0.0.1:${PROWLARR_HTTPS_PORT}/prowlarr/api/v1/applications/${app_id}" \
    >/dev/null
}

# ---------------------------------------------------------------------------
# Per-app rotation functions
# ---------------------------------------------------------------------------

rotate_sonarr() {
  local old_key
  old_key=$(get_xml_apikey "$SONARR_XML")
  local new_key
  new_key=$(rotate_arr_apikey "Sonarr" "sonarr" "$SONARR_XML")
  RESTART_NEEDED+=("sonarr")

  local prowlarr_key
  prowlarr_key=$(get_xml_apikey "$PROWLARR_XML")
  update_prowlarr_application "$prowlarr_key" "$PROWLARR_APP_ID_SONARR" "Sonarr" "$new_key"

  echo "[Bazarr] Updating sonarr.apikey in config.yaml..."
  yq -i ".sonarr.apikey = \"$new_key\"" "$BAZARR_CONFIG"

  echo "[recyclarr] Updating sonarr_apikey in secrets.yml..."
  yq -i ".sonarr_apikey = \"$new_key\"" "$RECYCLARR_SECRETS"

  update_homepage_env "HOMEPAGE_VAR_SONARR_API_KEY" "$new_key"

  SUMMARY_SONARR_OLD="$old_key"
  SUMMARY_SONARR_NEW="$new_key"
}

rotate_radarr() {
  local old_key
  old_key=$(get_xml_apikey "$RADARR_XML")
  local new_key
  new_key=$(rotate_arr_apikey "Radarr" "radarr" "$RADARR_XML")
  RESTART_NEEDED+=("radarr")

  local prowlarr_key
  prowlarr_key=$(get_xml_apikey "$PROWLARR_XML")
  update_prowlarr_application "$prowlarr_key" "$PROWLARR_APP_ID_RADARR" "Radarr" "$new_key"

  echo "[Bazarr] Updating radarr.apikey in config.yaml..."
  yq -i ".radarr.apikey = \"$new_key\"" "$BAZARR_CONFIG"

  echo "[recyclarr] Updating radarr_apikey in secrets.yml..."
  yq -i ".radarr_apikey = \"$new_key\"" "$RECYCLARR_SECRETS"

  update_homepage_env "HOMEPAGE_VAR_RADARR_API_KEY" "$new_key"

  SUMMARY_RADARR_OLD="$old_key"
  SUMMARY_RADARR_NEW="$new_key"
}

rotate_lidarr() {
  local old_key
  old_key=$(get_xml_apikey "$LIDARR_XML")
  local new_key
  new_key=$(rotate_arr_apikey "Lidarr" "lidarr" "$LIDARR_XML")
  RESTART_NEEDED+=("lidarr")

  local prowlarr_key
  prowlarr_key=$(get_xml_apikey "$PROWLARR_XML")
  update_prowlarr_application "$prowlarr_key" "$PROWLARR_APP_ID_LIDARR" "Lidarr" "$new_key"

  update_homepage_env "HOMEPAGE_VAR_LIDARR_API_KEY" "$new_key"

  SUMMARY_LIDARR_OLD="$old_key"
  SUMMARY_LIDARR_NEW="$new_key"
}

rotate_readarr() {
  local old_key
  old_key=$(get_xml_apikey "$READARR_XML")
  local new_key
  new_key=$(rotate_arr_apikey "Readarr" "readarr" "$READARR_XML")
  RESTART_NEEDED+=("readarr")

  local prowlarr_key
  prowlarr_key=$(get_xml_apikey "$PROWLARR_XML")
  update_prowlarr_application "$prowlarr_key" "$PROWLARR_APP_ID_READARR" "Readarr" "$new_key"

  update_homepage_env "HOMEPAGE_VAR_READARR_API_KEY" "$new_key"

  SUMMARY_READARR_OLD="$old_key"
  SUMMARY_READARR_NEW="$new_key"
}

rotate_whisparr() {
  local old_key
  old_key=$(get_xml_apikey "$WHISPARR_XML")
  local new_key
  new_key=$(rotate_arr_apikey "Whisparr" "whisparr" "$WHISPARR_XML")
  RESTART_NEEDED+=("whisparr")

  local prowlarr_key
  prowlarr_key=$(get_xml_apikey "$PROWLARR_XML")
  update_prowlarr_application "$prowlarr_key" "$PROWLARR_APP_ID_WHISPARR" "Whisparr" "$new_key"

  update_homepage_env "HOMEPAGE_VAR_WHISPARR_API_KEY" "$new_key"

  SUMMARY_WHISPARR_OLD="$old_key"
  SUMMARY_WHISPARR_NEW="$new_key"
}

rotate_prowlarr() {
  local old_key
  old_key=$(get_xml_apikey "$PROWLARR_XML")
  local new_key
  new_key=$(rotate_arr_apikey "Prowlarr" "prowlarr" "$PROWLARR_XML")
  RESTART_NEEDED+=("prowlarr")

  update_homepage_env "HOMEPAGE_VAR_PROWLARR_API_KEY" "$new_key"

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

  echo "[Bazarr] Updating auth.apikey in config.yaml..."
  yq -i ".auth.apikey = \"$new_key\"" "$BAZARR_CONFIG"
  RESTART_NEEDED+=("bazarr")

  update_homepage_env "HOMEPAGE_VAR_BAZARR_API_KEY" "$new_key"

  SUMMARY_BAZARR_OLD="$old_key"
  SUMMARY_BAZARR_NEW="$new_key"
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

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

case "$TARGET" in
sonarr) rotate_sonarr ;;
radarr) rotate_radarr ;;
lidarr) rotate_lidarr ;;
readarr) rotate_readarr ;;
whisparr) rotate_whisparr ;;
prowlarr) rotate_prowlarr ;;
bazarr) rotate_bazarr ;;
all)
  rotate_sonarr
  rotate_radarr
  rotate_lidarr
  rotate_readarr
  rotate_whisparr
  rotate_prowlarr
  rotate_bazarr
  ;;
*)
  echo "Unknown target: $TARGET" >&2
  echo "$USAGE" >&2
  exit 1
  ;;
esac

# ---------------------------------------------------------------------------
# Restart apps whose ApiKey was rewritten on disk, so they pick it up
# ---------------------------------------------------------------------------

if [[ ${#RESTART_NEEDED[@]} -gt 0 ]]; then
  echo ""
  echo "======================================================================"
  echo " Restarting apps to apply the new ApiKey: ${RESTART_NEEDED[*]}"
  echo "======================================================================"
  podman-compose --file docker-compose.yml --profile enabled up -d --force-recreate \
    "${RESTART_NEEDED[@]}"
fi

# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

echo ""
echo "======================================================================"
echo " API key rotation summary"
echo "======================================================================"
printf "%-12s  %-34s  %-34s\n" "Service" "Old key" "New key"
echo "----------------------------------------------------------------------"

print_row() {
  local svc="$1" old="$2" new="$3"
  if [[ -n "$old" ]]; then
    printf "%-12s  %-34s  %-34s\n" "$svc" "$old" "$new"
  fi
}

print_row "sonarr" "$SUMMARY_SONARR_OLD" "$SUMMARY_SONARR_NEW"
print_row "radarr" "$SUMMARY_RADARR_OLD" "$SUMMARY_RADARR_NEW"
print_row "lidarr" "$SUMMARY_LIDARR_OLD" "$SUMMARY_LIDARR_NEW"
print_row "readarr" "$SUMMARY_READARR_OLD" "$SUMMARY_READARR_NEW"
print_row "whisparr" "$SUMMARY_WHISPARR_OLD" "$SUMMARY_WHISPARR_NEW"
print_row "prowlarr" "$SUMMARY_PROWLARR_OLD" "$SUMMARY_PROWLARR_NEW"
print_row "bazarr" "$SUMMARY_BAZARR_OLD" "$SUMMARY_BAZARR_NEW"

echo "======================================================================"
