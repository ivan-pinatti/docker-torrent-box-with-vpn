#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/rotate-passwords.sh [sonarr|radarr|lidarr|readarr|whisparr|prowlarr|bazarr|qbittorrent|sabnzbd|all]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly REPO_ROOT
cd "$REPO_ROOT"

readonly USAGE="Usage: $0 [sonarr|radarr|lidarr|readarr|whisparr|prowlarr|bazarr|qbittorrent|sabnzbd|all]"

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

SONARR_HTTP_PORT="$(env_value SONARR_HTTP_PORT)"
RADARR_HTTPS_PORT="$(env_value RADARR_HTTPS_PORT)"
LIDARR_HTTPS_PORT="$(env_value LIDARR_HTTPS_PORT)"
READARR_HTTPS_PORT="$(env_value READARR_HTTPS_PORT)"
WHISPARR_HTTPS_PORT="$(env_value WHISPARR_HTTPS_PORT)"
PROWLARR_HTTPS_PORT="$(env_value PROWLARR_HTTPS_PORT)"
QBITTORRENT_HTTPS_PORT="$(env_value QBITTORRENT_HTTPS_PORT)"
# qBittorrent's WebUI binds to the Gluetun services IP (WebUI\Address in
# qBittorrent.conf), not loopback, so in-container curl must target it.
GLUETUN_SERVICES_IP="$(env_value GLUETUN_SERVICES_IP)"
readonly SONARR_HTTP_PORT RADARR_HTTPS_PORT LIDARR_HTTPS_PORT READARR_HTTPS_PORT \
  WHISPARR_HTTPS_PORT PROWLARR_HTTPS_PORT QBITTORRENT_HTTPS_PORT GLUETUN_SERVICES_IP

# ---------------------------------------------------------------------------
# Config file paths
# ---------------------------------------------------------------------------

readonly SONARR_XML="configs/sonarr/config/config.xml"
readonly RADARR_XML="configs/radarr/config/config.xml"
readonly LIDARR_XML="configs/lidarr/config/config.xml"
readonly READARR_XML="configs/readarr/config/config.xml"
readonly WHISPARR_XML="configs/whisparr/config/config.xml"
readonly PROWLARR_XML="configs/prowlarr/config/config.xml"

readonly BAZARR_CONFIG="configs/bazarr/config/config/config.yaml"
readonly SABNZBD_CONFIG="configs/sabnzbd/config/sabnzbd.ini"
readonly SABNZBD_ENV="configs/sabnzbd/.env.secrets"
readonly QBITTORRENT_SECRETS="configs/qbittorrent/.env.secrets"                   # pragma: allowlist secret
readonly QBITTORRENT_EXPORTER_SECRETS="configs/qbittorrent_exporter/.env.secrets" # pragma: allowlist secret
readonly LAZYLIBRARIAN_CONFIG="configs/lazylibrarian/config/config.ini"
readonly MYLAR_CONFIG="configs/mylar/config/mylar/config.ini"
readonly NOTIFIARR_CONFIG="configs/notifiarr/config/notifiarr.conf"

readonly SONARR_DB="configs/sonarr/config/sonarr.db"
readonly RADARR_DB="configs/radarr/config/radarr.db"
readonly LIDARR_DB="configs/lidarr/config/lidarr.db"
readonly READARR_DB="configs/readarr/config/readarr.db"
readonly WHISPARR_DB="configs/whisparr/config/whisparr3.db"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

gen_password() {
  openssl rand -base64 18 | tr -d '=+/' | cut -c1-16
}

gen_apikey() {
  openssl rand -hex 16
}

get_xml_apikey() {
  local xml_file="$1"
  grep -oPm1 '(?<=<ApiKey>)[^<]+' "$xml_file"
}

mask() {
  local val="$1"
  echo "${val:0:4}****"
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

# Rotate login password for an arr app via its host config API endpoint.
# The app hashes the plain text password internally upon receiving the PUT.
# Args: app_name container_name api_key port url_base api_version new_password [scheme]
# scheme defaults to https; Sonarr passes http because its SSL listener is not
# configured (see the known issues section in the README).
rotate_arr_password() {
  local app_name="$1"
  local container_name="$2"
  local api_key="$3"
  local port="$4"
  local url_base="$5"
  local api_ver="$6"
  local new_password="$7"
  local scheme="${8:-https}"

  echo "[$app_name] Fetching current host config..."
  local config
  config=$(container_curl "$container_name" -sk -H "X-Api-Key: $api_key" \
    "${scheme}://127.0.0.1:${port}/${url_base}/api/${api_ver}/config/host")

  echo "[$app_name] Setting new password..."
  local updated
  updated=$(echo "$config" | jq \
    --arg pw "$new_password" \
    '.password = $pw | .passwordConfirmation = $pw')

  container_curl "$container_name" -sk -X PUT \
    -H "X-Api-Key: $api_key" \
    -H "Content-Type: application/json" \
    -d "$updated" \
    "${scheme}://127.0.0.1:${port}/${url_base}/api/${api_ver}/config/host" \
    >/dev/null
}

# Update qBittorrent password in one arr app's DownloadClients SQLite table.
# Args: db_path new_password
update_arr_qbt_password() {
  local db_path="$1"
  local new_password="$2"

  python3 - <<PYEOF
import sqlite3, json
conn = sqlite3.connect('$db_path')
cur = conn.cursor()
cur.execute("SELECT Id, Settings FROM DownloadClients WHERE ConfigContract='QBittorrentSettings'")
rows = cur.fetchall()
for row in rows:
    s = json.loads(row[1])
    s['password'] = '$new_password'
    cur.execute('UPDATE DownloadClients SET Settings = ? WHERE Id = ?', (json.dumps(s), row[0]))
conn.commit()
conn.close()
PYEOF
}

# Update SABnzbd credentials in one arr app's DownloadClients SQLite table.
# Args: db_path new_password new_api_key
update_arr_sabnzbd_credentials() {
  local db_path="$1"
  local new_password="$2"
  local new_api_key="$3"

  python3 - <<PYEOF
import json
import sqlite3
conn = sqlite3.connect('$db_path')
cur = conn.cursor()
cur.execute("SELECT Id, Settings FROM DownloadClients WHERE ConfigContract='SabnzbdSettings'")
for row_id, raw_settings in cur.fetchall():
    settings = json.loads(raw_settings)
    settings['username'] = 'sabnzbd'
    settings['password'] = '$new_password'
    settings['apiKey'] = '$new_api_key'
    cur.execute('UPDATE DownloadClients SET Settings = ? WHERE Id = ?', (json.dumps(settings, indent=2), row_id))
conn.commit()
conn.close()
PYEOF
}

# ---------------------------------------------------------------------------
# Summary variables
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
SUMMARY_QBITTORRENT_OLD=""
SUMMARY_QBITTORRENT_NEW=""
SUMMARY_SABNZBD_OLD=""
SUMMARY_SABNZBD_NEW=""

# ---------------------------------------------------------------------------
# Per-app rotation functions
# ---------------------------------------------------------------------------

rotate_sonarr() {
  local new_password
  new_password=$(gen_password)
  local api_key
  api_key=$(get_xml_apikey "$SONARR_XML")
  rotate_arr_password "Sonarr" "sonarr" "$api_key" "$SONARR_HTTP_PORT" "sonarr" "v3" "$new_password" "http"
  SUMMARY_SONARR_OLD="sonarr"
  SUMMARY_SONARR_NEW="$new_password"
}

rotate_radarr() {
  local new_password
  new_password=$(gen_password)
  local api_key
  api_key=$(get_xml_apikey "$RADARR_XML")
  rotate_arr_password "Radarr" "radarr" "$api_key" "$RADARR_HTTPS_PORT" "radarr" "v3" "$new_password"
  SUMMARY_RADARR_OLD="radarr"
  SUMMARY_RADARR_NEW="$new_password"
}

rotate_lidarr() {
  local new_password
  new_password=$(gen_password)
  local api_key
  api_key=$(get_xml_apikey "$LIDARR_XML")
  rotate_arr_password "Lidarr" "lidarr" "$api_key" "$LIDARR_HTTPS_PORT" "lidarr" "v1" "$new_password"
  SUMMARY_LIDARR_OLD="lidarr"
  SUMMARY_LIDARR_NEW="$new_password"
}

rotate_readarr() {
  local new_password
  new_password=$(gen_password)
  local api_key
  api_key=$(get_xml_apikey "$READARR_XML")
  rotate_arr_password "Readarr" "readarr" "$api_key" "$READARR_HTTPS_PORT" "readarr" "v1" "$new_password"
  SUMMARY_READARR_OLD="readarr"
  SUMMARY_READARR_NEW="$new_password"
}

rotate_whisparr() {
  local new_password
  new_password=$(gen_password)
  local api_key
  api_key=$(get_xml_apikey "$WHISPARR_XML")
  rotate_arr_password "Whisparr" "whisparr" "$api_key" "$WHISPARR_HTTPS_PORT" "whisparr" "v3" "$new_password"
  SUMMARY_WHISPARR_OLD="whisparr"
  SUMMARY_WHISPARR_NEW="$new_password"
}

rotate_prowlarr() {
  local new_password
  new_password=$(gen_password)
  local api_key
  api_key=$(get_xml_apikey "$PROWLARR_XML")
  rotate_arr_password "Prowlarr" "prowlarr" "$api_key" "$PROWLARR_HTTPS_PORT" "prowlarr" "v1" "$new_password"
  SUMMARY_PROWLARR_OLD="prowlarr"
  SUMMARY_PROWLARR_NEW="$new_password"
}

rotate_bazarr() {
  local new_password
  new_password=$(gen_password)
  # Bazarr stores its login password as an MD5 hash (no salt, by design).
  local new_md5
  new_md5=$(echo -n "$new_password" | md5sum | cut -d' ' -f1)
  echo "[Bazarr] Writing MD5-hashed password to config.yaml..."
  yq -i ".auth.password = \"$new_md5\"" "$BAZARR_CONFIG"
  SUMMARY_BAZARR_OLD="bazarr"
  SUMMARY_BAZARR_NEW="$new_password"
}

rotate_qbittorrent() {
  local new_password
  new_password=$(gen_password)

  # Read the current plain-text password from Sonarr's DownloadClients table.
  local current_password
  current_password=$(
    python3 - <<PYEOF
import sqlite3, json
conn = sqlite3.connect('$SONARR_DB')
cur = conn.cursor()
cur.execute("SELECT Settings FROM DownloadClients WHERE ConfigContract='QBittorrentSettings' LIMIT 1")
row = cur.fetchone()
if row:
    s = json.loads(row[0])
    print(s.get('password', ''))
conn.close()
PYEOF
  )

  if [[ -z "$current_password" ]]; then
    echo "[qBittorrent] Could not read current password from Sonarr DB. Aborting qBittorrent rotation." >&2
    exit 1
  fi

  echo "[qBittorrent] Logging in with current password..."
  container_curl qbittorrent -sk -c /tmp/qbt_cookies.txt \
    -d "username=qbittorrent&password=${current_password}" \
    "https://${GLUETUN_SERVICES_IP}:${QBITTORRENT_HTTPS_PORT}/api/v2/auth/login" \
    >/dev/null

  echo "[qBittorrent] Setting new WebUI password..."
  container_curl qbittorrent -sk -b /tmp/qbt_cookies.txt \
    --data-urlencode "json={\"web_ui_password\":\"${new_password}\"}" \
    "https://${GLUETUN_SERVICES_IP}:${QBITTORRENT_HTTPS_PORT}/api/v2/app/setPreferences" \
    >/dev/null

  # The cookie file lives inside the container (curl ran via podman exec),
  # so it must be removed there, not on the host.
  podman exec qbittorrent rm -f /tmp/qbt_cookies.txt

  echo "[Sonarr DB] Updating qBittorrent password in DownloadClients..."
  update_arr_qbt_password "$SONARR_DB" "$new_password"

  echo "[Radarr DB] Updating qBittorrent password in DownloadClients..."
  update_arr_qbt_password "$RADARR_DB" "$new_password"

  echo "[Lidarr DB] Updating qBittorrent password in DownloadClients..."
  update_arr_qbt_password "$LIDARR_DB" "$new_password"

  echo "[Readarr DB] Updating qBittorrent password in DownloadClients..."
  update_arr_qbt_password "$READARR_DB" "$new_password"

  echo "[Whisparr DB] Updating qBittorrent password in DownloadClients..."
  update_arr_qbt_password "$WHISPARR_DB" "$new_password"

  echo "[Config] Updating qBittorrent password in .env.secrets files..."
  python3 - <<PYEOF
from pathlib import Path

new_password = '$new_password'

def set_env(path, key, value):
    p = Path(path)
    lines = p.read_text().splitlines() if p.exists() else []
    needle = f"{key}="
    for i, line in enumerate(lines):
        if line.startswith(needle):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    p.write_text("\\n".join(lines) + "\\n")

set_env('$QBITTORRENT_SECRETS', 'PASSWORD', new_password)
set_env('$QBITTORRENT_EXPORTER_SECRETS', 'QBITTORRENT_PASS', new_password)
PYEOF

  SUMMARY_QBITTORRENT_OLD="${current_password}"
  SUMMARY_QBITTORRENT_NEW="$new_password"
}

rotate_sabnzbd() {
  local new_password new_api_key new_nzb_key current_password
  new_password=$(gen_password)
  new_api_key=$(gen_apikey)
  new_nzb_key=$(gen_apikey)

  current_password=$(
    python3 - <<PYEOF
from pathlib import Path
for line in Path('$SABNZBD_CONFIG').read_text().splitlines():
    if line.strip().startswith('password ='):
        print(line.split('=', 1)[1].strip())
        break
else:
    print('sabnzbd')
PYEOF
  )

  echo "[SABnzbd] Updating config and root env credentials..."
  python3 - <<PYEOF
import re
import configparser
from pathlib import Path

new_password = '$new_password'
new_api_key = '$new_api_key'
new_nzb_key = '$new_nzb_key'

def set_env(path, key, value):
    p = Path(path)
    lines = p.read_text().splitlines() if p.exists() else []
    needle = f"{key}="
    for i, line in enumerate(lines):
        if line.startswith(needle):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    p.write_text("\\n".join(lines) + "\\n")

for path in ('.env', '$SABNZBD_ENV'):
    set_env(path, 'SABNZBD_USERNAME', 'sabnzbd')
    set_env(path, 'SABNZBD_PASSWORD', new_password)
    set_env(path, 'SABNZBD_API_KEY', new_api_key)
    set_env(path, 'SABNZBD_NZB_KEY', new_nzb_key)

def set_ini_key(path, key, value):
    p = Path(path)
    lines = p.read_text().splitlines()
    needle = f"{key} ="
    for i, line in enumerate(lines):
        if line.strip().startswith(needle):
            lines[i] = f"{key} = {value}"
            break
    else:
        insert_at = next(
            (i + 1 for i, line in enumerate(lines) if line.strip() == '[misc]'),
            len(lines),
        )
        lines.insert(insert_at, f"{key} = {value}")
    p.write_text("\\n".join(lines) + "\\n")

set_ini_key('$SABNZBD_CONFIG', 'username', 'sabnzbd')
set_ini_key('$SABNZBD_CONFIG', 'password', new_password)
set_ini_key('$SABNZBD_CONFIG', 'api_key', new_api_key)
set_ini_key('$SABNZBD_CONFIG', 'nzb_key', new_nzb_key)

if Path('$LAZYLIBRARIAN_CONFIG').exists():
    parser = configparser.ConfigParser()
    parser.read('$LAZYLIBRARIAN_CONFIG')
    if not parser.has_section('SABNZBD'):
        parser.add_section('SABNZBD')
    parser.set('SABNZBD', 'sabnzbd_user', 'sabnzbd')
    parser.set('SABNZBD', 'sabnzbd_pass', new_password)
    parser.set('SABNZBD', 'sabnzbd_apikey', new_api_key)
    if not parser.has_section('USENET'):
        parser.add_section('USENET')
    parser.set('USENET', 'nzb_downloader_sabnzbd', 'True')
    parser.set('USENET', 'nzb_downloader_nzbget', 'False')
    with open('$LAZYLIBRARIAN_CONFIG', 'w') as fh:
        parser.write(fh)

if Path('$MYLAR_CONFIG').exists():
    parser = configparser.ConfigParser()
    parser.read('$MYLAR_CONFIG')
    if not parser.has_section('SABnzbd'):
        parser.add_section('SABnzbd')
    parser.set('SABnzbd', 'sab_username', 'sabnzbd')
    parser.set('SABnzbd', 'sab_password', new_password)
    parser.set('SABnzbd', 'sab_apikey', new_api_key)
    parser.set('SABnzbd', 'sab_client_post_processing', 'True')
    if parser.has_section('NZBGet'):
        parser.set('NZBGet', 'nzbget_client_post_processing', 'False')
    with open('$MYLAR_CONFIG', 'w') as fh:
        parser.write(fh)

p = Path('$NOTIFIARR_CONFIG')
if p.exists():
    text = p.read_text()
    text = re.sub(r'api_key\\s*=\\s*"[^"]*"', f'api_key  = "{new_api_key}"', text, count=1)
    p.write_text(text)
PYEOF

  echo "[Sonarr DB] Updating SABnzbd credentials in DownloadClients..."
  update_arr_sabnzbd_credentials "$SONARR_DB" "$new_password" "$new_api_key"
  echo "[Radarr DB] Updating SABnzbd credentials in DownloadClients..."
  update_arr_sabnzbd_credentials "$RADARR_DB" "$new_password" "$new_api_key"
  echo "[Lidarr DB] Updating SABnzbd credentials in DownloadClients..."
  update_arr_sabnzbd_credentials "$LIDARR_DB" "$new_password" "$new_api_key"
  echo "[Readarr DB] Updating SABnzbd credentials in DownloadClients..."
  update_arr_sabnzbd_credentials "$READARR_DB" "$new_password" "$new_api_key"
  echo "[Whisparr DB] Updating SABnzbd credentials in DownloadClients..."
  update_arr_sabnzbd_credentials "$WHISPARR_DB" "$new_password" "$new_api_key"

  SUMMARY_SABNZBD_OLD="$current_password"
  SUMMARY_SABNZBD_NEW="$new_password"
}

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
qbittorrent) rotate_qbittorrent ;;
sabnzbd) rotate_sabnzbd ;;
all)
  rotate_sonarr
  rotate_radarr
  rotate_lidarr
  rotate_readarr
  rotate_whisparr
  rotate_prowlarr
  rotate_bazarr
  rotate_qbittorrent
  rotate_sabnzbd
  ;;
*)
  echo "Unknown target: $TARGET" >&2
  echo "$USAGE" >&2
  exit 1
  ;;
esac

# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

echo ""
echo "======================================================================"
echo " Password rotation summary  (shown as: first4****)"
echo "======================================================================"
printf "%-12s  %-12s  %-12s\n" "Service" "Old password" "New password"
echo "----------------------------------------------------------------------"

print_row() {
  local svc="$1" old="$2" new="$3"
  if [[ -n "$new" ]]; then
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
print_row "qbittorrent" "$SUMMARY_QBITTORRENT_OLD" "$SUMMARY_QBITTORRENT_NEW"
print_row "sabnzbd" "$SUMMARY_SABNZBD_OLD" "$SUMMARY_SABNZBD_NEW"

echo "======================================================================"
echo ""
echo "NOTE: Some apps cache credentials in memory. Restart containers if"
echo "      login fails after rotation:"
echo "        make restart"
echo "      or restart individual services as needed."
