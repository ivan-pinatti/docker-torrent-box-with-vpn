#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/rotate-passwords.sh [audiobookshelf|bazarr|calibre|calibre-web|grafana|jdownloader2|jellyfin|lazylibrarian|lidarr|mylar|nzbhydra2|prowlarr|qbittorrent|radarr|readarr|sabnzbd|sonarr|whisparr|all]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly REPO_ROOT
cd "$REPO_ROOT"

readonly USAGE="Usage: $0 [audiobookshelf|bazarr|calibre|calibre-web|grafana|jdownloader2|jellyfin|lazylibrarian|lidarr|mylar|nzbhydra2|prowlarr|qbittorrent|radarr|readarr|sabnzbd|sonarr|whisparr|all]"

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

# Generated password length and whether to include special characters, both
# configurable via .env (ROTATE_PASSWORD_LENGTH, ROTATE_PASSWORD_SPECIAL_CHARS).
ROTATE_PASSWORD_LENGTH="$(env_value ROTATE_PASSWORD_LENGTH)"
ROTATE_PASSWORD_LENGTH="${ROTATE_PASSWORD_LENGTH:-16}"
if ! [[ "$ROTATE_PASSWORD_LENGTH" =~ ^[0-9]+$ ]] || [[ "$ROTATE_PASSWORD_LENGTH" -lt 8 ]]; then
  echo "ERROR: ROTATE_PASSWORD_LENGTH must be an integer >= 8 (got '${ROTATE_PASSWORD_LENGTH}')" >&2
  exit 1
fi
ROTATE_PASSWORD_SPECIAL_CHARS="$(env_value ROTATE_PASSWORD_SPECIAL_CHARS)"
ROTATE_PASSWORD_SPECIAL_CHARS="${ROTATE_PASSWORD_SPECIAL_CHARS,,}"
ROTATE_PASSWORD_SPECIAL_CHARS="${ROTATE_PASSWORD_SPECIAL_CHARS:-false}"
readonly ROTATE_PASSWORD_LENGTH ROTATE_PASSWORD_SPECIAL_CHARS

# A service is enabled when its compose profile flag in .env is literally
# "enabled" (the Makefile starts the stack with --profile enabled).
# Args: profile_var_prefix (e.g. SONARR for SONARR_PROFILE)
profile_enabled() {
  [[ "$(env_value "${1}_PROFILE")" == "enabled" ]]
}

AUDIOBOOKSHELF_HTTP_PORT="$(env_value AUDIOBOOKSHELF_HTTP_PORT)"
BAZARR_HTTP_PORT="$(env_value BAZARR_HTTP_PORT)"
CALIBRE_GUI_WEB_HTTP_PORT="$(env_value CALIBRE_GUI_WEB_HTTP_PORT)"
CALIBRE_DESKTOP_HTTPS_PORT="$(env_value CALIBRE_DESKTOP_HTTPS_PORT)"
CALIBRE_WEB_CONTAINER_HTTPS_PORT="$(env_value CALIBRE_WEB_CONTAINER_HTTPS_PORT)"
JDOWNLOADER2_HTTP_PORT="$(env_value JDOWNLOADER2_HTTP_PORT)"
JELLYFIN_HTTP_PORT="$(env_value JELLYFIN_HTTP_PORT)"
LAZYLIBRARIAN_HTTP_PORT="$(env_value LAZYLIBRARIAN_HTTP_PORT)"
LIDARR_HTTPS_PORT="$(env_value LIDARR_HTTPS_PORT)"
MYLAR_HTTPS_PORT="$(env_value MYLAR_HTTPS_PORT)"
NZBHYDRA2_HTTPS_PORT="$(env_value NZBHYDRA2_HTTPS_PORT)"
PROWLARR_HTTPS_PORT="$(env_value PROWLARR_HTTPS_PORT)"
QBITTORRENT_HTTPS_PORT="$(env_value QBITTORRENT_HTTPS_PORT)"
# qBittorrent's WebUI binds to the Gluetun services IP (WebUI\Address in
# qBittorrent.conf), not loopback, so in-container curl must target it.
GLUETUN_SERVICES_IP="$(env_value GLUETUN_SERVICES_IP)"
RADARR_HTTPS_PORT="$(env_value RADARR_HTTPS_PORT)"
READARR_HTTPS_PORT="$(env_value READARR_HTTPS_PORT)"
SABNZBD_HTTPS_PORT="$(env_value SABNZBD_HTTPS_PORT)"
SONARR_HTTP_PORT="$(env_value SONARR_HTTP_PORT)"
WHISPARR_HTTPS_PORT="$(env_value WHISPARR_HTTPS_PORT)"
readonly AUDIOBOOKSHELF_HTTP_PORT BAZARR_HTTP_PORT CALIBRE_GUI_WEB_HTTP_PORT \
  CALIBRE_DESKTOP_HTTPS_PORT CALIBRE_WEB_CONTAINER_HTTPS_PORT JDOWNLOADER2_HTTP_PORT \
  JELLYFIN_HTTP_PORT LAZYLIBRARIAN_HTTP_PORT \
  LIDARR_HTTPS_PORT MYLAR_HTTPS_PORT NZBHYDRA2_HTTPS_PORT PROWLARR_HTTPS_PORT \
  QBITTORRENT_HTTPS_PORT GLUETUN_SERVICES_IP RADARR_HTTPS_PORT \
  READARR_HTTPS_PORT SABNZBD_HTTPS_PORT SONARR_HTTP_PORT WHISPARR_HTTPS_PORT

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
readonly HOMEPAGE_SECRETS="configs/homepage/.env.secrets"                         # pragma: allowlist secret
readonly LAZYLIBRARIAN_CONFIG="configs/lazylibrarian/config/config.ini"
readonly MYLAR_CONFIG="configs/mylar/config/mylar/config.ini"
readonly NOTIFIARR_CONFIG="configs/notifiarr/config/notifiarr.conf"
readonly GRAFANA_INI="configs/grafana/config/grafana.ini"
readonly CALIBREWEB_DB="configs/calibre-web/config/app.db"
readonly CALIBREWEB_USER="calibre"
readonly CALIBRE_USERS_DB="configs/calibre/config/.config/calibre/server-users.sqlite"
readonly CALIBRE_USER="calibre"
readonly CALIBRE_SECRETS="configs/calibre/.env.secrets" # pragma: allowlist secret
readonly NZBHYDRA_YML="configs/nzbhydra2/config/nzbhydra.yml"
readonly AUDIOBOOKSHELF_DB="configs/audiobookshelf/config/absdatabase.sqlite"
readonly AUDIOBOOKSHELF_USER="root"
readonly JELLYFIN_USERNAME="jellyfin"
readonly JDOWNLOADER2_SECRETS="configs/jdownloader2/.env.secrets" # pragma: allowlist secret
readonly JDOWNLOADER2_USERNAME="jdownloader2"

# Containers that must restart at the end so rewritten config files take
# effect (populated by the rotation functions).
RESTART_NEEDED=()

readonly SONARR_DB="configs/sonarr/config/sonarr.db"
readonly RADARR_DB="configs/radarr/config/radarr.db"
readonly LIDARR_DB="configs/lidarr/config/lidarr.db"
readonly READARR_DB="configs/readarr/config/readarr.db"
readonly WHISPARR_DB="configs/whisparr/config/whisparr3.db"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Length and character set come from ROTATE_PASSWORD_LENGTH and
# ROTATE_PASSWORD_SPECIAL_CHARS (see .env). The special-character subset is
# deliberately narrow: the password gets embedded raw (no escaping) into sed
# replacement text using | as the delimiter, curl's -d form-urlencoded
# bodies, and single-quoted Python string literals in several rotate
# functions, so it excludes anything with special meaning in any of those:
# quotes/backslash/backtick/dollar (shell and Python string delimiters),
# | and & (sed delimiter and "whole match" in replacement text), & = % +
# (form-urlencoded field/kv separators and escape marker), and # / ;
# (ini/yaml comment markers some apps' own config parsers may honor).
gen_password() {
  local charset='A-Za-z0-9'
  if [[ "$ROTATE_PASSWORD_SPECIAL_CHARS" == "true" ]]; then # pragma: allowlist secret
    charset='A-Za-z0-9!@^*()_~-'
  fi
  local pw
  pw=$(tr -dc "$charset" </dev/urandom 2>/dev/null | head -c "$ROTATE_PASSWORD_LENGTH" || true)
  # Never let the password start with '-': some consumers pass it as a bare
  # CLI argument, and a leading '-' gets parsed as a flag rather than data.
  # Confirmed directly: the calibre image's own init does
  # `passwd ... "$PASSWORD"`, and a password of "-csgvg13)j0ejd8U" produced
  # "passwd: Unknown option: -csgvg13)j0ejd8U", silently leaving the old
  # password in place while the rotation reported success.
  while [[ "$pw" == -* ]]; do
    pw=$(tr -dc "$charset" </dev/urandom 2>/dev/null | head -c "$ROTATE_PASSWORD_LENGTH" || true)
  done
  printf '%s' "$pw"
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

# Stop the listed containers if they exist, remembering which ones were
# stopped so start_stopped() can bring exactly those back. Stopped in one
# batched call (podman stops them concurrently) rather than one at a time,
# so one slow-to-stop container doesn't serialize behind the others.
STOPPED_CONTAINERS=()
stop_existing() {
  STOPPED_CONTAINERS=()
  local c
  for c in "$@"; do
    if podman container exists "$c" 2>/dev/null; then
      STOPPED_CONTAINERS+=("$c")
    fi
  done
  if [[ ${#STOPPED_CONTAINERS[@]} -gt 0 ]]; then
    podman stop "${STOPPED_CONTAINERS[@]}" >/dev/null
  fi
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
# Summary variables (alphabetical by service)
# ---------------------------------------------------------------------------

SUMMARY_AUDIOBOOKSHELF_USER=""
SUMMARY_AUDIOBOOKSHELF_NEW=""
SUMMARY_BAZARR_USER=""
SUMMARY_BAZARR_NEW=""
SUMMARY_CALIBRE_USER=""
SUMMARY_CALIBRE_NEW=""
SUMMARY_CALIBRE_WEB_USER=""
SUMMARY_CALIBRE_WEB_NEW=""
SUMMARY_GRAFANA_USER=""
SUMMARY_GRAFANA_NEW=""
SUMMARY_JDOWNLOADER2_USER=""
SUMMARY_JDOWNLOADER2_NEW=""
SUMMARY_JELLYFIN_USER=""
SUMMARY_JELLYFIN_NEW=""
SUMMARY_LAZYLIBRARIAN_USER=""
SUMMARY_LAZYLIBRARIAN_NEW=""
SUMMARY_LIDARR_USER=""
SUMMARY_LIDARR_NEW=""
SUMMARY_MYLAR_USER=""
SUMMARY_MYLAR_NEW=""
SUMMARY_NZBHYDRA2_USER=""
SUMMARY_NZBHYDRA2_NEW=""
SUMMARY_PROWLARR_USER=""
SUMMARY_PROWLARR_NEW=""
SUMMARY_QBITTORRENT_USER=""
SUMMARY_QBITTORRENT_NEW=""
SUMMARY_RADARR_USER=""
SUMMARY_RADARR_NEW=""
SUMMARY_READARR_USER=""
SUMMARY_READARR_NEW=""
SUMMARY_SABNZBD_USER=""
SUMMARY_SABNZBD_NEW=""
SUMMARY_SONARR_USER=""
SUMMARY_SONARR_NEW=""
SUMMARY_WHISPARR_USER=""
SUMMARY_WHISPARR_NEW=""
VERIFY_SABNZBD_KEY=""

# ---------------------------------------------------------------------------
# Per-app rotation functions (alphabetical by service)
# ---------------------------------------------------------------------------

rotate_audiobookshelf() {
  # Audiobookshelf has no password rotation API without the current password;
  # the bcrypt hash is written directly to the users table in absdatabase.sqlite
  # while the app is stopped. Homepage talks to it with a JWT API token, not
  # the password, so no consumer cascade is needed.
  local new_password new_hash
  new_password=$(gen_password)
  new_hash=$(
    python3 - <<PYEOF
import bcrypt

print(bcrypt.hashpw('$new_password'.encode(), bcrypt.gensalt()).decode())
PYEOF
  )

  echo "[Audiobookshelf] Stopping container to update absdatabase.sqlite..."
  podman stop audiobookshelf >/dev/null

  echo "[Audiobookshelf] Writing new password hash for user '${AUDIOBOOKSHELF_USER}'..."
  python3 - <<PYEOF
import sqlite3

conn = sqlite3.connect('$AUDIOBOOKSHELF_DB')
conn.execute("UPDATE users SET pash = ? WHERE username = ?", ('$new_hash', '$AUDIOBOOKSHELF_USER'))
conn.commit()
conn.close()
PYEOF

  podman start audiobookshelf >/dev/null

  SUMMARY_AUDIOBOOKSHELF_USER="$AUDIOBOOKSHELF_USER"
  SUMMARY_AUDIOBOOKSHELF_NEW="$new_password"
}

rotate_bazarr() {
  local new_password
  new_password=$(gen_password)
  # Bazarr stores its login password as an MD5 hash (no salt, by design).
  local new_md5
  new_md5=$(echo -n "$new_password" | md5sum | cut -d' ' -f1)
  # Bazarr reads config.yaml at startup and can rewrite it; edit stopped.
  echo "[Bazarr] Stopping container and writing MD5-hashed password to config.yaml..."
  podman stop bazarr >/dev/null
  yq -i ".auth.password = \"$new_md5\"" "$BAZARR_CONFIG"
  podman start bazarr >/dev/null
  SUMMARY_BAZARR_USER="bazarr"
  SUMMARY_BAZARR_NEW="$new_password"
}

rotate_calibre() {
  # Calibre has two independent logins that share the same password here for
  # simplicity: the content server (users in server-users.sqlite, read at
  # startup) and the desktop GUI/noVNC session (basic auth via CUSTOM_USER
  # and PASSWORD in .env.secrets, read only at container creation). Both
  # need the container down for the edit; the GUI container is left stopped
  # here and picked up by the env-secret consumer recreate at the end of the
  # script instead of a plain restart, so the new PASSWORD env var is loaded.
  # LazyLibrarian holds the same credential in its config.ini, which it
  # persists on shutdown, so it is stopped too.
  local new_password
  new_password=$(gen_password)

  echo "[Calibre] Stopping calibre and lazylibrarian to update credentials..."
  stop_existing lazylibrarian
  if podman container exists calibre 2>/dev/null; then
    podman stop calibre >/dev/null
  fi

  echo "[Calibre] Writing new password for content server user '${CALIBRE_USER}' to server-users.sqlite..."
  python3 - <<PYEOF
import sqlite3

conn = sqlite3.connect('$CALIBRE_USERS_DB')
conn.execute("UPDATE users SET pw = ? WHERE name = ?", ('$new_password', '$CALIBRE_USER'))
conn.commit()
conn.close()
PYEOF

  echo "[Calibre] Writing new password for desktop GUI user '${CALIBRE_USER}' to .env.secrets..."
  python3 - <<PYEOF
from pathlib import Path

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

set_env('$CALIBRE_SECRETS', 'PASSWORD', '$new_password')
PYEOF

  echo "[LazyLibrarian] Updating calibre_pass in config.ini..."
  sed -i "s|^calibre_pass = .*|calibre_pass = ${new_password}|" "$LAZYLIBRARIAN_CONFIG"

  start_stopped

  SUMMARY_CALIBRE_USER="$CALIBRE_USER"
  SUMMARY_CALIBRE_NEW="$new_password"
}

rotate_calibre_web() {
  # Calibre-Web has no password API; the hash is written directly to app.db
  # (werkzeug pbkdf2 format) while the app is stopped, then Homepage's
  # credential is updated.
  local new_password
  new_password=$(gen_password)

  echo "[Calibre-Web] Stopping container to update app.db..."
  podman stop calibre-web >/dev/null

  echo "[Calibre-Web] Writing new password hash for user '${CALIBREWEB_USER}'..."
  python3 - <<PYEOF
import hashlib
import secrets
import sqlite3

new_password = '$new_password'
salt = secrets.token_hex(8)
iterations = 600000
digest = hashlib.pbkdf2_hmac("sha256", new_password.encode(), salt.encode(), iterations).hex()
pw_hash = f"pbkdf2:sha256:{iterations}\${salt}\${digest}"

conn = sqlite3.connect('$CALIBREWEB_DB')
conn.execute("UPDATE user SET password = ? WHERE name = ?", (pw_hash, '$CALIBREWEB_USER'))
conn.commit()
conn.close()
PYEOF

  podman start calibre-web >/dev/null

  python3 - <<PYEOF
from pathlib import Path

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

set_env('$HOMEPAGE_SECRETS', 'HOMEPAGE_VAR_CALIBREWEB_PASS', '$new_password')
PYEOF

  SUMMARY_CALIBRE_WEB_USER="$CALIBREWEB_USER"
  SUMMARY_CALIBRE_WEB_NEW="$new_password"
}

rotate_grafana() {
  # Grafana's admin password lives in its own database; it is changed through
  # the self-service API using the current credentials from grafana.ini, then
  # grafana.ini and Homepage's Basic auth header are kept in sync.
  local user old_password new_password
  user=$(grep -oPm1 '(?<=^admin_user = ).*' "$GRAFANA_INI")
  old_password=$(grep -oPm1 '(?<=^admin_password = ).*' "$GRAFANA_INI")
  new_password=$(gen_password)

  echo "[Grafana] Changing the admin password via the API..."
  container_curl grafana -s --fail -u "${user}:${old_password}" -X PUT \
    -H "Content-Type: application/json" \
    -d "{\"oldPassword\":\"${old_password}\",\"newPassword\":\"${new_password}\",\"confirmNew\":\"${new_password}\"}" \
    "http://127.0.0.1:3000/api/user/password" >/dev/null

  echo "[Grafana] Updating admin_password in grafana.ini..."
  sed -i "s|^admin_password = .*|admin_password = ${new_password}|" "$GRAFANA_INI"

  echo "[Homepage] Updating HOMEPAGE_VAR_GRAFANA_AUTH..."
  local auth
  auth=$(printf '%s:%s' "$user" "$new_password" | base64 -w0)
  sed -i "s|^HOMEPAGE_VAR_GRAFANA_AUTH=.*|HOMEPAGE_VAR_GRAFANA_AUTH=Basic ${auth}|" "$HOMEPAGE_SECRETS"

  SUMMARY_GRAFANA_USER="$user"
  SUMMARY_GRAFANA_NEW="$new_password"
}

rotate_jdownloader2() {
  # jDownloader2's web UI (jlesage image) authenticates via WEB_AUTHENTICATION_*
  # env vars, read only at container creation, so the container is recreated
  # by the env-secret consumer step at the end of the script rather than
  # restarted here.
  local new_password
  new_password=$(gen_password)

  echo "[jDownloader2] Writing new password to .env.secrets..."
  python3 - <<PYEOF
from pathlib import Path

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

set_env('$JDOWNLOADER2_SECRETS', 'WEB_AUTHENTICATION_PASSWORD', '$new_password')
PYEOF

  SUMMARY_JDOWNLOADER2_USER="$JDOWNLOADER2_USERNAME"
  SUMMARY_JDOWNLOADER2_NEW="$new_password"
}

rotate_jellyfin() {
  # Jellyfin's login password is changed through its API with the admin API
  # key that Homepage holds. No other consumer stores the password (Homepage
  # authenticates with the API key).
  local new_password api_key user_id
  new_password=$(gen_password)
  api_key=$(grep -oPm1 '(?<=^HOMEPAGE_VAR_JELLYFIN_KEY=).*' "$HOMEPAGE_SECRETS")
  if [[ -z "$api_key" ]]; then
    echo "[Jellyfin] Could not read HOMEPAGE_VAR_JELLYFIN_KEY from ${HOMEPAGE_SECRETS}. Aborting Jellyfin rotation." >&2
    exit 1
  fi

  echo "[Jellyfin] Looking up the '${JELLYFIN_USERNAME}' user id..."
  user_id=$(container_curl jellyfin -s --fail \
    -H "Authorization: MediaBrowser Token=\"${api_key}\"" \
    "http://127.0.0.1:${JELLYFIN_HTTP_PORT}/jellyfin/Users" |
    jq -r --arg name "$JELLYFIN_USERNAME" '.[] | select(.Name == $name) | .Id')
  if [[ -z "$user_id" ]]; then
    echo "[Jellyfin] User '${JELLYFIN_USERNAME}' not found. Aborting Jellyfin rotation." >&2
    exit 1
  fi

  echo "[Jellyfin] Setting new password..."
  container_curl jellyfin -s --fail -X POST \
    -H "Authorization: MediaBrowser Token=\"${api_key}\"" \
    -H "Content-Type: application/json" \
    -d "{\"NewPw\":\"${new_password}\"}" \
    "http://127.0.0.1:${JELLYFIN_HTTP_PORT}/jellyfin/Users/${user_id}/Password"

  SUMMARY_JELLYFIN_USER="$JELLYFIN_USERNAME"
  SUMMARY_JELLYFIN_NEW="$new_password"
}

rotate_lazylibrarian() {
  # LazyLibrarian stores its WebUI password in plain text in config.ini and
  # reads it only at startup.
  local new_password
  new_password=$(gen_password)
  # LazyLibrarian persists its config on shutdown; stop, edit, start.
  echo "[LazyLibrarian] Stopping container and writing new http_pass..."
  podman stop lazylibrarian >/dev/null
  sed -i "s|^http_pass = .*|http_pass = ${new_password}|" "$LAZYLIBRARIAN_CONFIG"
  podman start lazylibrarian >/dev/null
  SUMMARY_LAZYLIBRARIAN_USER="lazylibrarian"
  SUMMARY_LAZYLIBRARIAN_NEW="$new_password"
}

rotate_lidarr() {
  local new_password
  new_password=$(gen_password)
  local api_key
  api_key=$(get_xml_apikey "$LIDARR_XML")
  rotate_arr_password "Lidarr" "lidarr" "$api_key" "$LIDARR_HTTPS_PORT" "lidarr" "v1" "$new_password"
  SUMMARY_LIDARR_USER="lidarr"
  SUMMARY_LIDARR_NEW="$new_password"
}

rotate_mylar() {
  # Mylar stores its WebUI password in plain text in config.ini and reads it
  # only at startup.
  local new_password
  new_password=$(gen_password)
  # Mylar persists its config on shutdown; stop, edit, start.
  echo "[Mylar] Stopping container and writing new http_password..."
  podman stop mylar >/dev/null
  sed -i "s|^http_password = .*|http_password = ${new_password}|" "$MYLAR_CONFIG"
  podman start mylar >/dev/null
  SUMMARY_MYLAR_USER="mylar"
  SUMMARY_MYLAR_NEW="$new_password"
}

rotate_nzbhydra2() {
  # NZBHydra2 stores WebUI passwords bcrypt-hashed in nzbhydra.yml with a
  # {bcrypt} prefix and reads them at startup.
  local new_password new_hash
  new_password=$(gen_password)
  new_hash=$(
    python3 - <<PYEOF
import bcrypt

print(bcrypt.hashpw('$new_password'.encode(), bcrypt.gensalt()).decode())
PYEOF
  )

  # NZBHydra2 persists its config on shutdown; stop, edit, start.
  echo "[NZBHydra2] Stopping container and writing new bcrypt password hash..."
  podman stop nzbhydra2 >/dev/null
  pwHash="{bcrypt}${new_hash}" yq -i '(.auth.users[0].password) = strenv(pwHash)' "$NZBHYDRA_YML"
  podman start nzbhydra2 >/dev/null

  SUMMARY_NZBHYDRA2_USER="nzbhydra2"
  SUMMARY_NZBHYDRA2_NEW="$new_password"
}

rotate_prowlarr() {
  local new_password
  new_password=$(gen_password)
  local api_key
  api_key=$(get_xml_apikey "$PROWLARR_XML")
  rotate_arr_password "Prowlarr" "prowlarr" "$api_key" "$PROWLARR_HTTPS_PORT" "prowlarr" "v1" "$new_password"
  SUMMARY_PROWLARR_USER="prowlarr"
  SUMMARY_PROWLARR_NEW="$new_password"
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

  # The arr apps' DownloadClients tables, and LazyLibrarian's and Mylar's
  # config files, are edited on disk; stop everything in the blast radius so
  # nothing rewrites the files mid-edit or reloads stale state.
  echo "[qBittorrent] Stopping consumers for config and database edits..."
  stop_existing sonarr radarr lidarr readarr whisparr lazylibrarian mylar

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
set_env('$HOMEPAGE_SECRETS', 'HOMEPAGE_VAR_QBITTORRENT_PASS', new_password)

def set_ini_line(path, key, value):
    p = Path(path)
    if not p.exists():
        return
    lines = p.read_text().splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f'{key} = '):
            lines[i] = f'{key} = {value}'
    p.write_text('\n'.join(lines) + '\n')

set_ini_line('$LAZYLIBRARIAN_CONFIG', 'qbittorrent_pass', new_password)
set_ini_line('$MYLAR_CONFIG', 'qbittorrent_password', new_password)
PYEOF

  start_stopped

  SUMMARY_QBITTORRENT_USER="qbittorrent"
  SUMMARY_QBITTORRENT_NEW="$new_password"
}

rotate_radarr() {
  local new_password
  new_password=$(gen_password)
  local api_key
  api_key=$(get_xml_apikey "$RADARR_XML")
  rotate_arr_password "Radarr" "radarr" "$api_key" "$RADARR_HTTPS_PORT" "radarr" "v3" "$new_password"
  SUMMARY_RADARR_USER="radarr"
  SUMMARY_RADARR_NEW="$new_password"
}

rotate_readarr() {
  local new_password
  new_password=$(gen_password)
  local api_key
  api_key=$(get_xml_apikey "$READARR_XML")
  rotate_arr_password "Readarr" "readarr" "$api_key" "$READARR_HTTPS_PORT" "readarr" "v1" "$new_password"
  SUMMARY_READARR_USER="readarr"
  SUMMARY_READARR_NEW="$new_password"
}

rotate_sabnzbd() {
  local new_password new_api_key new_nzb_key
  new_password=$(gen_password)
  new_api_key=$(gen_apikey)
  new_nzb_key=$(gen_apikey)

  # SABnzbd, LazyLibrarian, and Mylar persist their configs on shutdown, and
  # the arr apps' DownloadClients tables are edited on disk; stop everything
  # in the blast radius for the duration of the edits.
  echo "[SABnzbd] Stopping consumers for config and database edits..."
  stop_existing sabnzbd lazylibrarian mylar sonarr radarr lidarr readarr whisparr

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

set_env('$HOMEPAGE_SECRETS', 'HOMEPAGE_VAR_SABNZBD_API_KEY', new_api_key)

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

  start_stopped

  SUMMARY_SABNZBD_USER="sabnzbd"
  SUMMARY_SABNZBD_NEW="$new_password"
  VERIFY_SABNZBD_KEY="$new_api_key"
}

rotate_sonarr() {
  local new_password
  new_password=$(gen_password)
  local api_key
  api_key=$(get_xml_apikey "$SONARR_XML")
  rotate_arr_password "Sonarr" "sonarr" "$api_key" "$SONARR_HTTP_PORT" "sonarr" "v3" "$new_password" "http"
  SUMMARY_SONARR_USER="sonarr"
  SUMMARY_SONARR_NEW="$new_password"
}

rotate_whisparr() {
  local new_password
  new_password=$(gen_password)
  local api_key
  api_key=$(get_xml_apikey "$WHISPARR_XML")
  rotate_arr_password "Whisparr" "whisparr" "$api_key" "$WHISPARR_HTTPS_PORT" "whisparr" "v3" "$new_password"
  SUMMARY_WHISPARR_USER="whisparr"
  SUMMARY_WHISPARR_NEW="$new_password"
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

# Compose profile flag prefix per rotation target (<prefix>_PROFILE in .env).
profile_var_for() {
  case "$1" in
  calibre-web) echo "CALIBREWEB" ;;
  *) echo "${1^^}" ;;
  esac
}

container_running() {
  podman container inspect -f '{{.State.Running}}' "$1" 2>/dev/null | grep -q '^true$'
}

container_ready() {
  local container="$1" status
  container_running "$container" || return 1
  status=$(podman inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container" 2>/dev/null)
  [[ "$status" == "healthy" || "$status" == "none" ]]
}

# Some rotations (Servarr apps, qBittorrent, Grafana, Jellyfin) log into the
# app's own live API rather than stopping the container to edit a file, so
# the container has to be up first. Start it if it isn't and wait for its
# healthcheck, instead of requiring the operator to have started the stack.
# Args: container_name
ensure_running() {
  local container="$1"
  container_ready "$container" && return 0
  if ! podman container exists "$container" 2>/dev/null; then
    echo "[$container] Container does not exist; run 'make start' to create it" >&2
    return 1
  fi
  if container_running "$container"; then
    echo "[$container] Waiting for it to become healthy..."
  else
    echo "[$container] Not running; starting it..."
    podman start "$container" >/dev/null
  fi
  retry 120 container_ready "$container"
}

# Rotate one service, but only when its compose profile is enabled. In "all"
# mode disabled services are skipped with a note; an explicitly requested
# disabled service is an error. If a container_required_running is given and
# it cannot be brought up, the same skip-or-error handling applies.
# Args: service_name rotate_function [container_required_running]
rotate_if_enabled() {
  local service="$1" func="$2" requires_running="${3:-}"
  local profile_var
  profile_var="$(profile_var_for "$service")"
  if ! profile_enabled "$profile_var"; then
    if [[ "$TARGET" == "all" ]]; then
      echo "[$service] Skipped, ${profile_var}_PROFILE is disabled"
      return
    fi
    echo "ERROR: ${profile_var}_PROFILE is disabled in .env; not rotating $service" >&2
    exit 1
  fi
  if [[ -n "$requires_running" ]] && ! ensure_running "$requires_running"; then
    if [[ "$TARGET" == "all" ]]; then
      echo "[$service] Skipped, $requires_running did not become healthy"
      return
    fi
    echo "ERROR: $requires_running did not become healthy; cannot rotate $service" >&2
    exit 1
  fi
  "$func"
}

# Start every stopped container that an API-based rotation in this run will
# need, in one batched call, and wait for them to become healthy together.
# Without this, rotate_if_enabled's own ensure_running would start and wait
# on each one in turn as its rotation happens to come up in the dispatch
# below, serializing waits that could otherwise happen concurrently.
prestart_api_containers() {
  local svc container to_start=() to_wait=()
  for svc in sonarr radarr lidarr readarr whisparr prowlarr qbittorrent grafana jellyfin; do
    if [[ "$TARGET" != "all" && "$TARGET" != "$svc" ]]; then
      continue
    fi
    if ! profile_enabled "$(profile_var_for "$svc")"; then
      continue
    fi
    if ! podman container exists "$svc" 2>/dev/null || container_ready "$svc"; then
      continue
    fi
    # A container can already be running but not yet healthy right after
    # `make start`, which fires everything up and returns without waiting
    # for each app's own healthcheck; distinguish that from actually
    # stopped so the message doesn't claim to be starting something that
    # is already up.
    if container_running "$svc"; then
      to_wait+=("$svc")
    else
      to_start+=("$svc")
    fi
  done
  if [[ ${#to_start[@]} -eq 0 && ${#to_wait[@]} -eq 0 ]]; then
    return
  fi
  if [[ ${#to_start[@]} -gt 0 ]]; then
    echo "Starting stopped containers needed for rotation: ${to_start[*]}"
    podman start "${to_start[@]}" >/dev/null
  fi
  if [[ ${#to_wait[@]} -gt 0 ]]; then
    echo "Waiting for already-running containers to become healthy: ${to_wait[*]}"
  fi

  local pending=("${to_start[@]}" "${to_wait[@]}") elapsed=0
  while [[ ${#pending[@]} -gt 0 && $elapsed -lt 120 ]]; do
    sleep 5
    elapsed=$((elapsed + 5))
    local still_pending=()
    for container in "${pending[@]}"; do
      container_ready "$container" || still_pending+=("$container")
    done
    pending=("${still_pending[@]}")
  done
}
prestart_api_containers

# ---------------------------------------------------------------------------
# Parallel rotation for services with no shared container or config file.
# Everything else (Calibre, LazyLibrarian, Mylar, qBittorrent, SABnzbd, and
# the Servarr apps) touches the same containers, config.ini files, or DB
# tables as one another, so it stays fully sequential below: concurrent
# writes to the same file/DB race and can corrupt it (see the "Editing
# runtime app state" note in CLAUDE.md), and qBittorrent/SABnzbd's rotation
# stops the very Servarr containers their own rotation needs running.
# ---------------------------------------------------------------------------

PARALLEL_ROTATION_FAILURES=()

# Args: service_name rotate_function [container_required_running]
# Buffers output to a per-service file instead of streaming it live through a
# "sed" filter fed by process substitution (`> >(sed ...)`). That used to
# stream output live, but any rotate_* function that runs `podman start` (most
# of them do, per the "Editing runtime app state" stop/edit/start pattern in
# CLAUDE.md) spawns a conmon process that inherits the process substitution's
# pipe write-end and holds it open for the container's entire lifetime. The
# sed filter then never sees EOF and blocks forever, and since sed's own
# stdout is inherited from this script's stdout, that dangling filter also
# keeps the *whole script's* output pipe from ever reaching EOF, even after
# every rotation has genuinely finished. Symptom: `make rotate_passwords`
# looks hung indefinitely and its final summary (with the actual new
# passwords) never prints, even though the rotations already succeeded.
run_parallel_service() {
  local service="$1" func="$2" requires_running="${3:-}"
  local upper user_var new_var status=0
  upper="$(echo "${service^^}" | tr '-' '_')"
  user_var="SUMMARY_${upper}_USER"
  new_var="SUMMARY_${upper}_NEW"
  rotate_if_enabled "$service" "$func" "$requires_running" \
    >"$PARALLEL_TMPDIR/$service.log" 2>&1 || status=$?
  printf '%s\n%s\n%s\n' "${!user_var}" "${!new_var}" "$status" \
    >"$PARALLEL_TMPDIR/$service.result"
}

run_parallel_group() {
  PARALLEL_TMPDIR="$(mktemp -d)"
  local services=(audiobookshelf bazarr calibre-web grafana jdownloader2 jellyfin nzbhydra2 prowlarr)
  run_parallel_service audiobookshelf rotate_audiobookshelf &
  run_parallel_service bazarr rotate_bazarr &
  run_parallel_service calibre-web rotate_calibre_web &
  run_parallel_service grafana rotate_grafana grafana &
  run_parallel_service jdownloader2 rotate_jdownloader2 &
  run_parallel_service jellyfin rotate_jellyfin jellyfin &
  run_parallel_service nzbhydra2 rotate_nzbhydra2 &
  run_parallel_service prowlarr rotate_prowlarr prowlarr &
  wait

  local service upper user_var new_var result lines
  for service in "${services[@]}"; do
    if [[ -s "$PARALLEL_TMPDIR/$service.log" ]]; then
      sed "s/^/[$service] /" "$PARALLEL_TMPDIR/$service.log"
    fi
  done
  for service in "${services[@]}"; do
    upper="$(echo "${service^^}" | tr '-' '_')"
    user_var="SUMMARY_${upper}_USER"
    new_var="SUMMARY_${upper}_NEW"
    result="$PARALLEL_TMPDIR/$service.result"
    if [[ -s "$result" ]]; then
      mapfile -t lines <"$result"
      printf -v "$user_var" '%s' "${lines[0]}"
      printf -v "$new_var" '%s' "${lines[1]}"
      if [[ "${lines[2]}" != "0" ]]; then
        PARALLEL_ROTATION_FAILURES+=("$service")
      fi
    fi
  done
  rm -rf "$PARALLEL_TMPDIR"
}

case "$TARGET" in
audiobookshelf) rotate_if_enabled audiobookshelf rotate_audiobookshelf ;;
bazarr) rotate_if_enabled bazarr rotate_bazarr ;;
calibre) rotate_if_enabled calibre rotate_calibre ;;
calibre-web) rotate_if_enabled calibre-web rotate_calibre_web ;;
grafana) rotate_if_enabled grafana rotate_grafana grafana ;;
jdownloader2) rotate_if_enabled jdownloader2 rotate_jdownloader2 ;;
jellyfin) rotate_if_enabled jellyfin rotate_jellyfin jellyfin ;;
lazylibrarian) rotate_if_enabled lazylibrarian rotate_lazylibrarian ;;
lidarr) rotate_if_enabled lidarr rotate_lidarr lidarr ;;
mylar) rotate_if_enabled mylar rotate_mylar ;;
nzbhydra2) rotate_if_enabled nzbhydra2 rotate_nzbhydra2 ;;
prowlarr) rotate_if_enabled prowlarr rotate_prowlarr prowlarr ;;
qbittorrent) rotate_if_enabled qbittorrent rotate_qbittorrent qbittorrent ;;
radarr) rotate_if_enabled radarr rotate_radarr radarr ;;
readarr) rotate_if_enabled readarr rotate_readarr readarr ;;
sabnzbd) rotate_if_enabled sabnzbd rotate_sabnzbd ;;
sonarr) rotate_if_enabled sonarr rotate_sonarr sonarr ;;
whisparr) rotate_if_enabled whisparr rotate_whisparr whisparr ;;
all)
  run_parallel_group
  rotate_if_enabled calibre rotate_calibre
  rotate_if_enabled lazylibrarian rotate_lazylibrarian
  rotate_if_enabled lidarr rotate_lidarr lidarr
  rotate_if_enabled mylar rotate_mylar
  rotate_if_enabled qbittorrent rotate_qbittorrent qbittorrent
  rotate_if_enabled radarr rotate_radarr radarr
  rotate_if_enabled readarr rotate_readarr readarr
  rotate_if_enabled sabnzbd rotate_sabnzbd
  rotate_if_enabled sonarr rotate_sonarr sonarr
  rotate_if_enabled whisparr rotate_whisparr whisparr
  ;;
*)
  echo "Unknown target: $TARGET" >&2
  echo "$USAGE" >&2
  exit 1
  ;;
esac

# ---------------------------------------------------------------------------
# Restart apps whose config files were rewritten on disk
# ---------------------------------------------------------------------------

if [[ ${#RESTART_NEEDED[@]} -gt 0 ]]; then
  echo ""
  echo "Restarting apps to load rewritten configs: ${RESTART_NEEDED[*]}"
  podman restart "${RESTART_NEEDED[@]}" >/dev/null
fi

# ---------------------------------------------------------------------------
# Recreate containers that consume rotated secrets from env files. They read
# those values only at container creation, so without a recreate they keep
# authenticating with the old credentials.
# ---------------------------------------------------------------------------

RECREATE_CONSUMERS=()
case "$TARGET" in
qbittorrent) RECREATE_CONSUMERS=(qbittorrent_exporter homepage) ;;
sabnzbd) RECREATE_CONSUMERS=(sabnzbd_exporter homepage) ;;
calibre) RECREATE_CONSUMERS=(calibre) ;;
calibre-web | grafana) RECREATE_CONSUMERS=(homepage) ;;
jdownloader2) RECREATE_CONSUMERS=(jdownloader2) ;;
all) RECREATE_CONSUMERS=(qbittorrent_exporter sabnzbd_exporter homepage calibre jdownloader2) ;;
esac

if [[ ${#RECREATE_CONSUMERS[@]} -gt 0 ]]; then
  existing_consumers=()
  for consumer in "${RECREATE_CONSUMERS[@]}"; do
    if podman container exists "$consumer" 2>/dev/null; then
      existing_consumers+=("$consumer")
    fi
  done
  if [[ ${#existing_consumers[@]} -gt 0 ]]; then
    echo ""
    echo "Recreating secret consumers: ${existing_consumers[*]}"
    # --no-deps is required: jdownloader2 (and anything else on
    # network_mode: container:gluetun) declares gluetun as a dependency, and
    # without --no-deps podman-compose recreates gluetun too, which drops the
    # network namespace out from under qbittorrent and sabnzbd.
    podman-compose --file docker-compose.yml --profile enabled up -d --force-recreate --no-deps \
      "${existing_consumers[@]}"
  fi
fi

# ---------------------------------------------------------------------------
# Host-side SQLite writes above can leave -wal/-shm files owned by the host
# user, which the app user inside the container cannot open after a restart;
# normalize ownership before finishing.
# ---------------------------------------------------------------------------

"$SCRIPT_DIR/permissions.py" repair --runtime podman --recursive >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
# Summary table (alphabetical by service)
# ---------------------------------------------------------------------------

# The new passwords are printed in full: the apps store only hashes, so this
# summary is the single chance to record them. Save them in your password
# manager right away.
echo ""
echo "======================================================================"
echo " Password rotation summary"
echo "======================================================================"
printf "%-14s  %-14s  %-20s\n" "Service" "User" "New password"
echo "----------------------------------------------------------------------"

print_row() {
  local svc="$1" user="$2" new="$3"
  if [[ -n "$new" ]]; then
    printf "%-14s  %-14s  %-20s\n" "$svc" "$user" "$new"
  fi
}

print_row "audiobookshelf" "$SUMMARY_AUDIOBOOKSHELF_USER" "$SUMMARY_AUDIOBOOKSHELF_NEW"
print_row "bazarr" "$SUMMARY_BAZARR_USER" "$SUMMARY_BAZARR_NEW"
print_row "calibre" "$SUMMARY_CALIBRE_USER" "$SUMMARY_CALIBRE_NEW"
print_row "calibre-web" "$SUMMARY_CALIBRE_WEB_USER" "$SUMMARY_CALIBRE_WEB_NEW"
print_row "grafana" "$SUMMARY_GRAFANA_USER" "$SUMMARY_GRAFANA_NEW"
print_row "jdownloader2" "$SUMMARY_JDOWNLOADER2_USER" "$SUMMARY_JDOWNLOADER2_NEW"
print_row "jellyfin" "$SUMMARY_JELLYFIN_USER" "$SUMMARY_JELLYFIN_NEW"
print_row "lazylibrarian" "$SUMMARY_LAZYLIBRARIAN_USER" "$SUMMARY_LAZYLIBRARIAN_NEW"
print_row "lidarr" "$SUMMARY_LIDARR_USER" "$SUMMARY_LIDARR_NEW"
print_row "mylar" "$SUMMARY_MYLAR_USER" "$SUMMARY_MYLAR_NEW"
print_row "nzbhydra2" "$SUMMARY_NZBHYDRA2_USER" "$SUMMARY_NZBHYDRA2_NEW"
print_row "prowlarr" "$SUMMARY_PROWLARR_USER" "$SUMMARY_PROWLARR_NEW"
print_row "qbittorrent" "$SUMMARY_QBITTORRENT_USER" "$SUMMARY_QBITTORRENT_NEW"
print_row "radarr" "$SUMMARY_RADARR_USER" "$SUMMARY_RADARR_NEW"
print_row "readarr" "$SUMMARY_READARR_USER" "$SUMMARY_READARR_NEW"
print_row "sabnzbd" "$SUMMARY_SABNZBD_USER" "$SUMMARY_SABNZBD_NEW"
print_row "sonarr" "$SUMMARY_SONARR_USER" "$SUMMARY_SONARR_NEW"
print_row "whisparr" "$SUMMARY_WHISPARR_USER" "$SUMMARY_WHISPARR_NEW"

echo "======================================================================"
echo ""
echo "IMPORTANT: Save these passwords in your password manager now. The apps"
echo "           store only hashes; the passwords cannot be recovered later."
echo ""
echo "NOTE: Some apps cache credentials in memory. Restart containers if"
echo "      login fails after rotation:"
echo "        make restart"
echo "      or restart individual services as needed."
# ---------------------------------------------------------------------------
# Validation: prove each rotated credential is accepted by its service. Each
# check retries while the restarted container comes back up. Checks are
# listed alphabetically by service.
# ---------------------------------------------------------------------------

arr_login_ok() {
  local app="$1" scheme="$2" port="$3" base="$4" password="$5"
  local location
  # These apps always redirect (302/303) on a /login POST, whether the
  # credentials are right or wrong; only the redirect target differs
  # (back to /login?...loginFailed=true on failure). Checking the status
  # code alone always reports success, so check the Location header instead.
  location=$(container_curl "$app" -sk -D - -o /dev/null \
    -d "username=${app}&password=${password}" \
    "${scheme}://127.0.0.1:${port}/${base}/login" | tr -d '\r' | grep -i '^location:')
  [[ -n "$location" && "$location" != *"loginFailed=true"* ]]
}

# The audiobookshelf image ships no curl, but it is a node image with global
# fetch; the login check runs node inside the container instead.
audiobookshelf_login_ok() {
  podman exec audiobookshelf node -e '
    const [port, username, password] = process.argv.slice(1);
    fetch(`http://127.0.0.1:${port}/audiobookshelf/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    }).then((res) => process.exit(res.status === 200 ? 0 : 1),
            () => process.exit(1));
  ' "$AUDIOBOOKSHELF_HTTP_PORT" "$AUDIOBOOKSHELF_USER" "$1"
}

# Bazarr's /bazarr/login route only accepts GET (POST returns 405); the real
# credential check is the account API, which returns 204 on success and 403
# on a wrong password.
bazarr_login_ok() {
  local code
  code=$(container_curl bazarr -s -o /dev/null -w '%{http_code}' \
    -X POST -d "username=bazarr&password=$1" \
    "http://127.0.0.1:${BAZARR_HTTP_PORT}/bazarr/api/system/account?action=login")
  [[ "$code" == "204" ]]
}

# Checks both of Calibre's independent logins that share this password: the
# content server (plain HTTP basic auth) and the desktop GUI/noVNC session
# (basic auth over HTTPS with a self-signed certificate).
calibre_login_ok() {
  local code
  code=$(container_curl calibre -s -o /dev/null -w '%{http_code}' \
    -u "${CALIBRE_USER}:$1" \
    "http://127.0.0.1:${CALIBRE_GUI_WEB_HTTP_PORT}/ajax/library-info")
  [[ "$code" == "200" ]] || return 1
  code=$(container_curl calibre -sk -o /dev/null -w '%{http_code}' \
    -u "${CALIBRE_USER}:$1" \
    "https://127.0.0.1:${CALIBRE_DESKTOP_HTTPS_PORT}/")
  [[ "$code" == "200" ]]
}

calibre_web_login_ok() {
  local code
  code=$(container_curl calibre-web -sk -o /dev/null -w '%{http_code}' \
    -u "${CALIBREWEB_USER}:$1" \
    "https://127.0.0.1:${CALIBRE_WEB_CONTAINER_HTTPS_PORT}/opds/stats")
  [[ "$code" == "200" ]]
}

grafana_login_ok() {
  container_curl grafana -s --fail -o /dev/null -u "admin:$1" \
    http://127.0.0.1:3000/api/user
}

# jDownloader2's login flow (jlesage webauth) needs a cookie jar across three
# requests: prime cookies, POST the login form, then confirm the root page
# no longer redirects to /login/. Runs as a single in-container shell script
# since container_curl only wraps one curl call.
jdownloader2_login_ok() {
  podman exec jdownloader2 sh -c '
    jar=$(mktemp)
    curl -sk -c "$jar" -o /dev/null "https://127.0.0.1:'"${JDOWNLOADER2_HTTP_PORT}"'/"
    curl -sk -b "$jar" -c "$jar" -o /dev/null \
      -d "username='"${JDOWNLOADER2_USERNAME}"'&password='"$1"'" \
      "https://127.0.0.1:'"${JDOWNLOADER2_HTTP_PORT}"'/login/login"
    code=$(curl -sk -b "$jar" -o /dev/null -w "%{http_code}" "https://127.0.0.1:'"${JDOWNLOADER2_HTTP_PORT}"'/")
    rm -f "$jar"
    [ "$code" = "200" ]
  '
}

jellyfin_login_ok() {
  local code
  code=$(container_curl jellyfin -s -o /dev/null -w '%{http_code}' -X POST \
    -H 'Authorization: MediaBrowser Client="rotate-passwords", Device="script", DeviceId="rotate-passwords", Version="1.0"' \
    -H "Content-Type: application/json" \
    -d "{\"Username\":\"${JELLYFIN_USERNAME}\",\"Pw\":\"$1\"}" \
    "http://127.0.0.1:${JELLYFIN_HTTP_PORT}/jellyfin/Users/AuthenticateByName")
  [[ "$code" == "200" ]]
}

nzbhydra_login_ok() {
  local out
  out=$(container_curl nzbhydra2 -sk -o /dev/null -w '%{http_code} %{redirect_url}' \
    -d "username=nzbhydra2&password=$1" \
    "https://127.0.0.1:${NZBHYDRA2_HTTPS_PORT}/nzbhydra2/login")
  [[ "$out" == 302* && "$out" != *"login?error"* ]]
}

qbittorrent_api_ok() {
  local code
  code=$(container_curl qbittorrent -sk -o /dev/null -w '%{http_code}' \
    "https://${GLUETUN_SERVICES_IP}:${QBITTORRENT_HTTPS_PORT}/api/v2/auth/login" \
    -d "username=qbittorrent&password=$1")
  [[ "$code" == "200" ]]
}

sabnzbd_key_ok() {
  local body
  body=$(container_curl sabnzbd -sk \
    "https://127.0.0.1:${SABNZBD_HTTPS_PORT}/sabnzbd/api?mode=queue&output=json&apikey=$1")
  [[ "$body" == *'"queue"'* ]]
}

service_up_ok() {
  local container="$1" url="$2"
  local code
  code=$(container_curl "$container" -sk -o /dev/null -w '%{http_code}' "$url")
  [[ "$code" == "200" ]]
}

# Unlike rotation, validation is read-only (login attempts against each
# service's own container) with no shared file or DB writes, so every
# service validates concurrently, not just the services rotation itself
# can safely parallelize. Each one records pass/fail to a result file since
# it runs as a background job and can't hand VALIDATION_FAILURES back to
# the parent shell directly.
VALIDATION_FAILURES=()
validate() {
  local name="$1" timeout="$2"
  shift 2
  local status=0
  if retry "$timeout" "$@"; then
    printf "%-14s  OK\n" "$name"
  else
    printf "%-14s  FAILED\n" "$name"
    status=1
  fi
  echo "$status" >"$VALIDATE_TMPDIR/$name.result"
}

# Calibre's desktop GUI (and its content server, which only starts once the
# GUI is up) can wedge on its single-instance lock after a stop/start or
# recreate cycle. Give it a normal boot window first, then self-heal once by
# restarting the desktop service before giving it a second window, instead of
# requiring an operator to notice and run the recovery command by hand.
validate_calibre() {
  local password="$1"
  local status=0
  if retry 90 calibre_login_ok "$password"; then
    printf "%-14s  OK\n" "calibre"
    echo "$status" >"$VALIDATE_TMPDIR/calibre.result"
    return
  fi
  echo "[Calibre] Not responding after 90s; restarting the desktop service..."
  podman exec calibre s6-svc -r /run/service/svc-de >/dev/null 2>&1 || true
  if retry 300 calibre_login_ok "$password"; then
    printf "%-14s  OK\n" "calibre"
  else
    printf "%-14s  FAILED\n" "calibre"
    status=1
  fi
  echo "$status" >"$VALIDATE_TMPDIR/calibre.result"
}

# Args: service_name validate_command...
# Backgrounds the validation call and remembers its name so results can be
# collected from VALIDATE_TMPDIR after "wait". Lines print in whatever order
# each check finishes, not the order queued, which is expected for
# concurrent jobs.
VALIDATION_SERVICES=()
queue_validation() {
  local name="$1"
  shift
  VALIDATION_SERVICES+=("$name")
  "$@" &
}

echo ""
echo "======================================================================"
echo " Validating rotated credentials"
echo "======================================================================"
VALIDATE_TMPDIR="$(mktemp -d)"
# LazyLibrarian and Mylar serve their login page at /auth/login; /login is a
# 404 (LazyLibrarian) or a redirect (Mylar), so probe the real page.
[[ -n "$SUMMARY_AUDIOBOOKSHELF_NEW" ]] && queue_validation audiobookshelf validate audiobookshelf 180 audiobookshelf_login_ok "$SUMMARY_AUDIOBOOKSHELF_NEW"
[[ -n "$SUMMARY_BAZARR_NEW" ]] && queue_validation bazarr validate bazarr 180 bazarr_login_ok "$SUMMARY_BAZARR_NEW"
[[ -n "$SUMMARY_CALIBRE_NEW" ]] && queue_validation calibre validate_calibre "$SUMMARY_CALIBRE_NEW"
[[ -n "$SUMMARY_CALIBRE_WEB_NEW" ]] && queue_validation calibre-web validate calibre-web 180 calibre_web_login_ok "$SUMMARY_CALIBRE_WEB_NEW"
[[ -n "$SUMMARY_GRAFANA_NEW" ]] && queue_validation grafana validate grafana 180 grafana_login_ok "$SUMMARY_GRAFANA_NEW"
[[ -n "$SUMMARY_JDOWNLOADER2_NEW" ]] && queue_validation jdownloader2 validate jdownloader2 180 jdownloader2_login_ok "$SUMMARY_JDOWNLOADER2_NEW"
[[ -n "$SUMMARY_JELLYFIN_NEW" ]] && queue_validation jellyfin validate jellyfin 180 jellyfin_login_ok "$SUMMARY_JELLYFIN_NEW"
[[ -n "$SUMMARY_LAZYLIBRARIAN_NEW" ]] && queue_validation lazylibrarian validate lazylibrarian 180 service_up_ok lazylibrarian "https://127.0.0.1:${LAZYLIBRARIAN_HTTP_PORT}/lazylibrarian/auth/login"
[[ -n "$SUMMARY_LIDARR_NEW" ]] && queue_validation lidarr validate lidarr 180 arr_login_ok lidarr https "$LIDARR_HTTPS_PORT" lidarr "$SUMMARY_LIDARR_NEW"
[[ -n "$SUMMARY_MYLAR_NEW" ]] && queue_validation mylar validate mylar 180 service_up_ok mylar "https://127.0.0.1:${MYLAR_HTTPS_PORT}/mylar/auth/login"
[[ -n "$SUMMARY_NZBHYDRA2_NEW" ]] && queue_validation nzbhydra2 validate nzbhydra2 180 nzbhydra_login_ok "$SUMMARY_NZBHYDRA2_NEW"
[[ -n "$SUMMARY_PROWLARR_NEW" ]] && queue_validation prowlarr validate prowlarr 180 arr_login_ok prowlarr https "$PROWLARR_HTTPS_PORT" prowlarr "$SUMMARY_PROWLARR_NEW"
[[ -n "$SUMMARY_QBITTORRENT_NEW" ]] && queue_validation qbittorrent validate qbittorrent 180 qbittorrent_api_ok "$SUMMARY_QBITTORRENT_NEW"
[[ -n "$SUMMARY_RADARR_NEW" ]] && queue_validation radarr validate radarr 180 arr_login_ok radarr https "$RADARR_HTTPS_PORT" radarr "$SUMMARY_RADARR_NEW"
[[ -n "$SUMMARY_READARR_NEW" ]] && queue_validation readarr validate readarr 180 arr_login_ok readarr https "$READARR_HTTPS_PORT" readarr "$SUMMARY_READARR_NEW"
[[ -n "$VERIFY_SABNZBD_KEY" ]] && queue_validation sabnzbd validate sabnzbd 180 sabnzbd_key_ok "$VERIFY_SABNZBD_KEY"
[[ -n "$SUMMARY_SONARR_NEW" ]] && queue_validation sonarr validate sonarr 180 arr_login_ok sonarr http "$SONARR_HTTP_PORT" sonarr "$SUMMARY_SONARR_NEW"
[[ -n "$SUMMARY_WHISPARR_NEW" ]] && queue_validation whisparr validate whisparr 180 arr_login_ok whisparr https "$WHISPARR_HTTPS_PORT" whisparr "$SUMMARY_WHISPARR_NEW"
wait

for name in "${VALIDATION_SERVICES[@]}"; do
  result="$VALIDATE_TMPDIR/$name.result"
  if [[ -s "$result" ]] && [[ "$(cat "$result")" == "1" ]]; then
    VALIDATION_FAILURES+=("$name")
  fi
done
rm -rf "$VALIDATE_TMPDIR"
echo "======================================================================"

if [[ ${#PARALLEL_ROTATION_FAILURES[@]} -gt 0 ]]; then
  echo ""
  echo "ERROR: rotation failed for: ${PARALLEL_ROTATION_FAILURES[*]}" >&2
  exit 1
fi

if [[ ${#VALIDATION_FAILURES[@]} -gt 0 ]]; then
  echo ""
  echo "ERROR: validation failed for: ${VALIDATION_FAILURES[*]}" >&2
  exit 1
fi
