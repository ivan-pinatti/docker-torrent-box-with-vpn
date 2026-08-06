#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/enable-test-profiles.sh
# Applies .env.tests' profile overrides onto .env, then seeds the local
# mock VPN endpoint if one is needed (scripts/seed-vpn-mock.sh decides
# that for itself). Called by `make bootstrap_tests`, never by plain
# `make bootstrap` or `make start`. Never run this against a real
# deployment: it changes which profiles are enabled in .env, the same way
# bootstrap's own credential rotation permanently changes every password.

readonly ENV_FILE=".env"
readonly OVERRIDES_FILE=".env.tests"

[[ -f "$ENV_FILE" ]] || {
  echo "ERROR: ${ENV_FILE} does not exist. Run 'make bootstrap' at least" >&2
  echo "once first, or 'cp .env.example ${ENV_FILE}'." >&2
  exit 1
}

while IFS= read -r line; do
  # Skip blank lines and comments, same idiom .env itself uses.
  [[ -z "$line" || "$line" == \#* ]] && continue
  key="${line%%=*}"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${line}|" "$ENV_FILE"
  else
    printf '%s\n' "$line" >>"$ENV_FILE"
  fi
  echo "[${ENV_FILE}] ${line}"
done <"$OVERRIDES_FILE"

./scripts/seed-vpn-mock.sh
