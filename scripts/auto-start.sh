#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

# Give the host's network and storage time to settle after boot.
sleep 120

runtime="$(command -v podman >/dev/null 2>&1 && echo podman || echo docker)"

until "$runtime" ps >/dev/null 2>&1; do
  echo "Waiting for $runtime to be ready..."
  sleep 2
done

echo "$runtime is ready!"

make start
