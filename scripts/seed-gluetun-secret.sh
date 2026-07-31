#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/seed-gluetun-secret.sh
# Ensures configs/gluetun/.secret holds a real WireGuard private key before
# bootstrap starts the stack, since every torrent/usenet app depends on
# Gluetun's network namespace. If it's missing, empty, or still README.md's
# example placeholder, and stdin is a real terminal, prompts to paste one in
# directly. In a non-interactive run (CI, scripted bootstrap) there's nowhere
# to prompt, so it fails with instructions instead.

readonly SECRET_FILE="configs/gluetun/.secret"                      # pragma: allowlist secret
readonly PLACEHOLDER="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=" # pragma: allowlist secret

needs_key() {
  [[ ! -s "$SECRET_FILE" ]] || grep -qx "$PLACEHOLDER" "$SECRET_FILE"
}

if ! needs_key; then
  exit 0
fi

if [[ ! -t 0 ]]; then
  echo "ERROR: $SECRET_FILE is missing or empty." >&2
  echo "Gluetun needs your own WireGuard private key before bootstrap can start" >&2
  echo "the stack. See README.md section 3.1 (Gluetun VPN Gateway) for how to get" >&2
  echo "one from your VPN provider and paste it in, then re-run 'make bootstrap'." >&2
  exit 1
fi

echo ""
echo "Gluetun needs your WireGuard private key (see README.md section 3.1 for"
echo "how to get one from your VPN provider)."
read -r -p "Paste the PrivateKey value, or press Enter to skip and edit ${SECRET_FILE} manually: " key

if [[ -z "$key" ]]; then
  echo "ERROR: No key entered. Paste your own WireGuard PrivateKey into" >&2
  echo "${SECRET_FILE} before running bootstrap." >&2
  exit 1
fi

printf '%s' "$key" >"$SECRET_FILE"
echo "[${SECRET_FILE}] Saved."
