#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/seed-secrets.sh <config-dir>
# Seeds <config-dir>/.env.secrets from .env.secrets.example, and any
# <config-dir>/secrets/<name> from secrets/<name>.example, on first bootstrap.
# If .env.secrets already exists, prompts interactively instead of silently
# overwriting or silently skipping.

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <config-dir>" >&2
  exit 1
fi

readonly DIR="$1"
readonly EXAMPLE="$DIR/.env.secrets.example"
readonly SECRETS="$DIR/.env.secrets"

# Files delivered to containers via compose `secrets:`. Mode 644 is required,
# not laxness: rootless podman maps these host files to uid 0 inside the
# container while the app runs as another UID, so 600 and 640 are unreadable
# to it. Existing files are never overwritten, so live credentials survive.
shopt -s nullglob
for example in "$DIR"/secrets/*.example; do
  name="$(basename "$example" .example)"
  target="$DIR/secrets/$name"
  if [[ ! -f "$target" ]]; then
    # Strip trailing newlines rather than cp'ing verbatim: consumers read the
    # contents as-is (homepage substitutes them straight into its config), and
    # end-of-file-fixer will happily append a newline to the committed
    # .example, which would otherwise be copied into the live secret.
    printf '%s' "$(cat "$example")" >"$target"
    chmod 644 "$target"
    echo "[$DIR] Seeded secrets/$name from secrets/$name.example."
  fi
done
shopt -u nullglob

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
