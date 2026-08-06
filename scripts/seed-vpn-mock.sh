#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/seed-vpn-mock.sh
# Brings up the local mock WireGuard endpoint (docker-compose-vpn.yml's
# vpn_mock service; see docs/VPN_MOCK.md) and points gluetun at it, but
# only when there's no real VPN key to protect: mirrors
# seed-gluetun-secret.sh's own needs_setup() check exactly, so a real key
# already in place is never touched or overwritten. Only ever called from
# scripts/enable-test-profiles.sh (make bootstrap_tests), never from plain
# make bootstrap.

readonly ENV_FILE=".env"
readonly GLUETUN_SECRET="configs/gluetun/.secret" # pragma: allowlist secret
readonly GLUETUN_ENV="configs/gluetun/.env"
readonly PLACEHOLDER="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=" # pragma: allowlist secret
readonly PEER_CONF="configs/vpn_mock/config/peer1/peer1.conf"

env_value() {
  grep -m1 "^$1=" "$ENV_FILE" | cut -d= -f2-
}

needs_setup() {
  [[ ! -s "$GLUETUN_SECRET" ]] || grep -qx "$PLACEHOLDER" "$GLUETUN_SECRET"
}

if [[ "$(env_value VPN_MOCK_PROFILE)" != "enabled" ]]; then
  exit 0
fi

if ! needs_setup; then
  echo "[vpn_mock] ${GLUETUN_SECRET} already has a real key; leaving it alone."
  exit 0
fi

if command -v podman >/dev/null 2>&1; then
  if command -v podman-compose >/dev/null 2>&1; then
    COMPOSE=(podman-compose)
  else
    COMPOSE=(podman compose)
  fi
else
  COMPOSE=(docker compose)
fi

echo "[vpn_mock] No real VPN key found; starting the local mock WireGuard endpoint..."
# gluetun's own .env is normally seeded later, inside bootstrap's own
# recipe; this runs before that, so it must exist first (same ordering
# fix seed-gluetun-secret.sh already applies to itself, for the same
# reason: both edit it before bootstrap otherwise would).
./scripts/seed-configs.sh "$GLUETUN_ENV" >/dev/null
"${COMPOSE[@]}" --file docker-compose.yml --profile enabled up -d vpn_mock >/dev/null

echo "[vpn_mock] Waiting for peer keys to generate..."
elapsed=0
until [[ -s "$PEER_CONF" ]]; do
  sleep 2
  elapsed=$((elapsed + 2))
  if [[ $elapsed -ge 60 ]]; then
    echo "ERROR: ${PEER_CONF} was not generated after 60s." >&2
    echo "Check 'podman logs vpn_mock' for details." >&2
    exit 1
  fi
done

private_key=$(awk -F' = ' '/^PrivateKey/ {print $2; exit}' "$PEER_CONF")
address=$(awk -F' = ' '/^Address/ {print $2; exit}' "$PEER_CONF")
public_key=$(awk -F' = ' '/^PublicKey/ {print $2; exit}' "$PEER_CONF")
preshared_key=$(awk -F' = ' '/^PresharedKey/ {print $2; exit}' "$PEER_CONF")

if [[ -z "$private_key" || -z "$address" || -z "$public_key" || -z "$preshared_key" ]]; then
  echo "ERROR: Could not parse ${PEER_CONF}." >&2
  exit 1
fi

printf '%s' "$private_key" >"$GLUETUN_SECRET"
echo "[${GLUETUN_SECRET}] Saved the mock's peer private key."

vpn_mock_ip="$(env_value VPN_MOCK_IP)"
sed -i \
  -e "s|^VPN_SERVICE_PROVIDER=.*|VPN_SERVICE_PROVIDER=custom|" \
  -e "s|^VPN_TYPE=.*|VPN_TYPE=wireguard|" \
  -e "s|^VPN_PORT_FORWARDING=.*|VPN_PORT_FORWARDING=off|" \
  -e "s|^SERVER_COUNTRIES=.*|SERVER_COUNTRIES=|" \
  "$GLUETUN_ENV"

# SERVER_COUNTRIES is blanked, not removed, above: gluetun's "custom"
# provider has no server list to validate a country against and hard
# rejects the config outright if it's still set to protonvpn's default
# ("the country specified is not valid: one or more values is set but
# there is no possible value available"), confirmed live. Also using
# WIREGUARD_ENDPOINT_IP/_PORT here, not the generic VPN_ENDPOINT_IP/_PORT:
# gluetun accepts the latter only as a deprecated alias (it logs a WARN
# pointing at the same rename).
for var_line in \
  "WIREGUARD_ENDPOINT_IP=${vpn_mock_ip}" \
  "WIREGUARD_ENDPOINT_PORT=51820" \
  "WIREGUARD_PUBLIC_KEY=${public_key}" \
  "WIREGUARD_PRESHARED_KEY=${preshared_key}" \
  "WIREGUARD_ADDRESSES=${address}"; do
  key="${var_line%%=*}"
  if grep -q "^${key}=" "$GLUETUN_ENV"; then
    sed -i "s|^${key}=.*|${var_line}|" "$GLUETUN_ENV"
  else
    printf '%s\n' "$var_line" >>"$GLUETUN_ENV"
  fi
done

echo "[${GLUETUN_ENV}] Pointed gluetun at the local mock (custom WireGuard provider)."
