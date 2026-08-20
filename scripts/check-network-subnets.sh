#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2022 Ivan Pinatti
set -euo pipefail

# Usage: ./scripts/check-network-subnets.sh
#
# Refuses to start when a network already exists on a different subnet than .env
# now asks for. `make start`'s own "ensure required networks exist" step is
# `network exists X || network create --subnet ...`, so an existing network is
# reused whatever subnet it carries, and a podman network outlives the stack it
# belongs to: stopping does not remove it. Change SERVICES_SUBNET and the network
# keeps the old range, while the compose files hand containers an
# `ipv4_address:` from the new one. The container then fails to attach, or
# attaches somewhere nothing can reach it, and neither message mentions the
# subnet.
#
# Removing the network automatically is deliberately not what happens here. It
# would disconnect whatever else is attached, including another checkout's
# running stack, which is precisely the situation these variables exist to keep
# apart. Naming the mismatch and stopping is the useful behavior.

readonly ENV_FILE=".env"

[[ -f "$ENV_FILE" ]] || exit 0

if command -v podman >/dev/null 2>&1; then
  RUNTIME=podman
else
  RUNTIME=docker
fi

env_value() {
  grep -m1 "^${1}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"' || true
}

project="$(env_value COMPOSE_PROJECT_NAME)"
[[ -n "$project" ]] || project="$(basename "$PWD")"

problems=0

# Only the three that declare a subnet. apps, wan and edge are created without
# one, so podman picks a free range and there is nothing to disagree about.
check() {
  local suffix="$1" var="$2"
  local name="${project}_${suffix}"
  local want actual
  want="$(env_value "$var")"
  [[ -n "$want" ]] || return 0
  "$RUNTIME" network exists "$name" 2>/dev/null || return 0
  actual="$("$RUNTIME" network inspect "$name" --format '{{range .Subnets}}{{.Subnet}}{{end}}' 2>/dev/null || true)"
  [[ -n "$actual" ]] || return 0
  if [[ "$actual" != "$want" ]]; then
    echo "ERROR: network ${name} is on ${actual}, but ${var} in ${ENV_FILE} asks for ${want}." >&2
    problems=$((problems + 1))
  fi
}

check services SERVICES_SUBNET
check observability OBSERVABILITY_SUBNET
check media MEDIA_SUBNET

if [[ "$problems" -gt 0 ]]; then
  cat >&2 <<EOF

Containers would be given an ipv4_address outside the network they attach to.
Stop this stack and remove the networks above so they are recreated on the
subnets ${ENV_FILE} now declares:

  make stop_all
  ${RUNTIME} network rm ${project}_services ${project}_observability ${project}_media

Check nothing else is attached first: another checkout sharing these subnets is
why they are worth changing in the first place.
EOF
  exit 1
fi
