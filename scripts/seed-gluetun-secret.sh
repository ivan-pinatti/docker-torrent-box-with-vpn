#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/seed-gluetun-secret.sh
# Ensures Gluetun has a working VPN configuration before bootstrap starts the
# stack, since every torrent/usenet app depends on its network namespace.
# Checks configs/gluetun/.secret for a real WireGuard key; if it's missing,
# empty, or still README.md's example placeholder, and stdin is a real
# terminal, offers a guided setup. Proton VPN is the only provider walked
# through fully (WireGuard key plus server country), since it's this
# project's default and Gluetun's other supported providers use different
# auth models entirely (OpenVPN username/password, preshared keys, reserved
# ports) that would be wrong to guess at generically. Any other provider gets
# pointed at docs/VPN_PROVIDERS.md to configure configs/gluetun/.env and
# .secret by hand. In a non-interactive run (CI, scripted bootstrap) there's
# nowhere to prompt, so it always fails fast with instructions.

readonly SECRET_FILE="configs/gluetun/.secret" # pragma: allowlist secret
readonly ENV_FILE="configs/gluetun/.env"
readonly PLACEHOLDER="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=" # pragma: allowlist secret

# Reads one line from the terminal, printing '*' per character instead of
# the character itself, and supporting backspace. All the echoed prompt and
# asterisks go straight to /dev/tty so this function's own stdout stays
# clean for command substitution: callers do key="$(read_masked "prompt")".
read_masked() {
  local prompt="$1"
  local input="" char
  printf '%s' "$prompt" >/dev/tty
  while IFS= read -rsn1 char; do
    if [[ -z "$char" ]]; then
      break
    fi
    if [[ "$char" == $'\x7f' ]]; then
      if [[ -n "$input" ]]; then
        input="${input%?}"
        printf '\b \b' >/dev/tty
      fi
      continue
    fi
    input+="$char"
    printf '*' >/dev/tty
  done
  printf '\n' >/dev/tty
  printf '%s' "$input"
}

needs_setup() {
  [[ ! -s "$SECRET_FILE" ]] || grep -qx "$PLACEHOLDER" "$SECRET_FILE"
}

fail_with_instructions() {
  echo "ERROR: $SECRET_FILE is missing or empty." >&2
  echo "Gluetun needs your own VPN credentials before bootstrap can start the" >&2
  echo "stack. See README.md section 3.1 (Gluetun VPN Gateway) for Proton VPN," >&2
  echo "or docs/VPN_PROVIDERS.md for other providers, then re-run 'make bootstrap'." >&2
  exit 1
}

if ! needs_setup; then
  exit 0
fi

if [[ ! -t 0 ]]; then
  fail_with_instructions
fi

# .env is normally seeded later in bootstrap's seed-configs.sh pass, but a
# Proton setup below edits SERVER_COUNTRIES in it, so it must exist first.
./scripts/seed-configs.sh "$ENV_FILE" >/dev/null

echo ""
echo "Gluetun needs a VPN configuration before the stack can start."
echo "Which provider are you using?"
echo "  1) Proton VPN (guided WireGuard setup)"
echo "  2) Something else (NordVPN, ExpressVPN, PIA, AirVPN, TorGuard, ...)"
read -r -p "Choice [1/2]: " choice

case "$choice" in
1)
  echo ""
  echo "Paste the WireGuard PrivateKey from your Proton VPN config (see"
  echo "README.md section 3.1 for how to generate one), or press Enter to"
  echo "skip and edit ${SECRET_FILE} manually. Input is masked."
  key="$(read_masked "PrivateKey: ")"
  if [[ -z "$key" ]]; then
    echo "ERROR: No key entered. Paste your own WireGuard PrivateKey into" >&2
    echo "${SECRET_FILE} before running bootstrap." >&2
    exit 1
  fi
  printf '%s' "$key" >"$SECRET_FILE"
  echo "[${SECRET_FILE}] Saved."

  # A rotating suggestion instead of always defaulting to the same country,
  # so a fresh clone doesn't nudge every user onto the same Proton server.
  countries=(Netherlands Switzerland Germany Iceland Norway Romania Spain France Canada Japan)
  suggested_country="${countries[$((RANDOM % ${#countries[@]}))]}"
  echo ""
  echo "Which server country do you want to connect through? See"
  echo "https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/protonvpn.md"
  echo "for the full list, or press Enter to use the suggestion."
  read -r -p "SERVER_COUNTRIES [${suggested_country}]: " country
  country="${country:-$suggested_country}"
  sed -i "s/^SERVER_COUNTRIES=.*/SERVER_COUNTRIES=${country}/" "$ENV_FILE"
  echo "[${ENV_FILE}] Set SERVER_COUNTRIES=${country}."
  ;;
2)
  echo "" >&2
  echo "ERROR: Only Proton VPN can be configured interactively right now." >&2
  echo "See docs/VPN_PROVIDERS.md for NordVPN, ExpressVPN, PIA, AirVPN," >&2
  echo "TorGuard, and other providers, then edit ${ENV_FILE} and" >&2
  echo "${SECRET_FILE} by hand, and re-run 'make bootstrap'." >&2
  exit 1
  ;;
*)
  echo "ERROR: Invalid choice." >&2
  exit 1
  ;;
esac
