#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/seed-secrets.sh <config-dir>
# Seeds <config-dir>/.env.secrets from .env.secrets.example on first
# bootstrap. If .env.secrets already exists, prompts interactively instead
# of silently overwriting or silently skipping.

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <config-dir>" >&2
  exit 1
fi

readonly DIR="$1"
readonly EXAMPLE="$DIR/.env.secrets.example"
readonly SECRETS="$DIR/.env.secrets"

[[ -f "$EXAMPLE" ]] || exit 0

if [[ ! -f "$SECRETS" ]]; then
  cp "$EXAMPLE" "$SECRETS"
  echo "[$DIR] Seeded .env.secrets from .env.secrets.example."
  exit 0
fi

# Non-interactive (CI, scripted runs) — never touch existing secrets.
[[ -t 0 ]] || exit 0

echo ""
echo "[$DIR] .env.secrets already exists."
select choice in "Skip (keep existing)" "Review diff" "Replace with .env.secrets.example"; do
  case "$choice" in
  "Skip (keep existing)") break ;;
  "Review diff") diff -u "$SECRETS" "$EXAMPLE" || true ;;
  "Replace with .env.secrets.example")
    cp "$EXAMPLE" "$SECRETS"
    echo "[$DIR] Replaced .env.secrets."
    break
    ;;
  *) echo "Invalid choice." ;;
  esac
done
