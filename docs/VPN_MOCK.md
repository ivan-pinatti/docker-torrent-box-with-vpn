# Local mock VPN endpoint

`qbittorrent` and `sabnzbd` both declare `depends_on: gluetun: condition:
service_healthy`, and gluetun's healthcheck only passes once a VPN tunnel
is actually established. Without real VPN provider credentials, gluetun
never reports healthy, so those two containers, and everything wired
through them (Prowlarr's own download clients, every arr app's download
client), never start. That's true today in CI without a VPN key, and for
any contributor without a paid VPN account.

`make bootstrap_tests` (see the README's "Full test coverage" section)
closes that gap with a local, credential-free WireGuard
endpoint: `docker-compose-vpn.yml`'s `vpn_mock` service, a
`linuxserver/wireguard` container running in server mode on the same host.
Gluetun connects to it for real (`VPN_SERVICE_PROVIDER=custom`), so
gluetun's own connection, health, and killswitch logic all run completely
unmodified against it. It is not a privacy feature: it's a same-host
WireGuard hop that exists purely to make gluetun's own logic exercisable
without a real provider account.

## How it gets wired

1. `scripts/enable-test-profiles.sh` applies `.env.tests`, which sets
   `VPN_MOCK_PROFILE=enabled`.
2. It then runs `scripts/seed-vpn-mock.sh`, which:
   - Skips entirely if `configs/gluetun/.secret` already holds a real key
     (the same check `scripts/seed-gluetun-secret.sh` uses) — an existing
     real credential is never touched.
   - Starts just the `vpn_mock` container and waits for
     `configs/vpn_mock/config/peer1/peer1.conf`, which
     `linuxserver/wireguard` generates on first boot along with a server
     keypair.
   - Parses that peer file's `PrivateKey`, `Address`, and the `[Peer]`
     block's `PublicKey`.
   - Writes the private key into `configs/gluetun/.secret`, the same file
     a real credential would live in.
   - Updates `configs/gluetun/.env`: `VPN_SERVICE_PROVIDER=custom`,
     `VPN_TYPE=wireguard`, `VPN_ENDPOINT_IP` (`vpn_mock`'s static IP,
     `VPN_MOCK_IP` in `.env`), `VPN_ENDPOINT_PORT=51820`,
     `WIREGUARD_PUBLIC_KEY`, `WIREGUARD_ADDRESSES`, and
     `VPN_PORT_FORWARDING=off` (port forwarding is a provider-specific
     API with no self-hosted equivalent).
3. `make bootstrap` proceeds as normal from there. Its own
   `seed-gluetun-secret.sh` step sees a populated secret and no-ops
   through its existing check, so nothing about plain `bootstrap`'s
   behavior changes for a real user pasting in a real key.

## What this unlocks

Every test that currently skips without a real VPN key becomes
exercisable, most notably `tests/test_vpn_killswitch.py`, which only
requires gluetun and the probe container to be genuinely healthy — it has
no idea whether the tunnel behind that health state is a real provider or
a local mock.

## Never for a real deployment

`VPN_MOCK_PROFILE` defaults to `disabled` in `.env.example` and stays that
way unless `.env.tests` is applied. Running `make bootstrap_tests` rewrites
`configs/gluetun/.secret` and `.env` the same way plain `make bootstrap`
rewrites every other credential, so it's meant for a disposable clone, not
a deployment you care about. If you want your own real VPN, follow
README.md section 3.1 or `docs/VPN_PROVIDERS.md` instead.
