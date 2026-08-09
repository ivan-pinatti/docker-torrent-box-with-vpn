#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2022 Ivan Pinatti
set -euo pipefail

# Usage: ./scripts/rotate-all.sh [service|all]
# Rotates API keys then passwords. Defaults to "all" if no argument is given.
# See rotate-api-keys.sh and rotate-passwords.sh for the valid service names.

TARGET="${1:-all}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly REPO_ROOT
cd "$REPO_ROOT"

# qbittorrent and SABnzbd are handled by password rotation only here.
if [[ "$TARGET" != "qbittorrent" && "$TARGET" != "sabnzbd" ]]; then
  echo "======================================================================"
  echo " Starting API key rotation (target: $TARGET)"
  echo "======================================================================"
  "${SCRIPT_DIR}/rotate-api-keys.sh" "$TARGET"
  echo ""
fi

echo ""
echo "======================================================================"
echo " Starting password rotation (target: $TARGET)"
echo "======================================================================"
"${SCRIPT_DIR}/rotate-passwords.sh" "$TARGET"

echo ""
echo "All rotations complete."
