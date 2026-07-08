# Compose file conventions

Every service block across the `docker-compose-*.yml` files follows the same
key order. This keeps services easy to scan and diffs easy to review: once you
know the order, you know where to look for any given setting, regardless of
which file or service you're reading.

## Canonical key order

```text
<<: *anchor(s)      # YAML merge key(s), always first line when present
deploy              # only when written explicitly (override, or no anchor)
image
build               # rare, only services with a local Dockerfile
container_name
depends_on          # only network_mode-based services with a hard dependency
profiles
networks / network_mode
ports
sysctls
restart
stop_grace_period
stop_signal
privileged
userns_mode
user
security_opt
cap_drop
cap_add
devices
entrypoint
command
env_file
environment
volumes
healthcheck
memswap_limit       # disabled services only, sits with deploy at the top
```

Reasoning for the less obvious placements:

- `environment`, `volumes`, and `healthcheck` come last because they're
  typically the longest blocks in a service definition; keeping them at the
  end means the shorter, more identity/security-relevant keys (`image`,
  `networks`, `security_opt`, etc.) are visible without scrolling.
- `command`/`entrypoint` sit with the other short "how the process starts"
  keys, right before `env_file`, rather than being grouped with the long tail.
- `deploy` and `memswap_limit` are resource-limit keys. When a service
  declares one explicitly instead of (or as an override on top of) a shared
  `x-limit-*` anchor, it stays at the very top, immediately after the merge
  key, since that's conceptually where the anchor's own `deploy` key would sit.
- Disabled/commented-out service blocks, and inline commented-out fragments
  (e.g. a `# ports:` block kept for reference), follow the same order as if
  they were active, so re-enabling a service later doesn't require another
  reorder pass.

## Example

```yaml
sonarr:
  <<: [*servarr-common, *limit-servarr]
  image: docker.io/linuxserver/sonarr:${SONARR_VERSION}
  container_name: sonarr
  profiles: ["${SONARR_PROFILE}"]
  networks:
    apps:
      aliases: [sonarr-http]
    services: {}
  env_file: ["${CONFIG_FOLDER}/sonarr/.env"]
  environment:
    <<: *servarr-env
    PGID: "${SONARR_GID}"
    PUID: "${SONARR_UID}"
  volumes:
    - /etc/localtime:/etc/localtime:ro
    - ${CERTIFICATES_FOLDER}:/certs:ro
    - ${CONFIG_FOLDER}/sonarr/config:/config:z
    - ${DATA_FOLDER}:/data:z
  healthcheck:
    <<: *healthcheck-defaults
    test: curl --fail http://127.0.0.1:${SONARR_HTTP_PORT}/sonarr/ || exit 1
```

## Secrets override pattern

Most services keep a single, committed `configs/<service>/.env` file (empty or
holding non-sensitive defaults). For a service whose `.env` needs to carry
real secrets (API keys, SMTP passwords, tokens), split it into two files
instead of committing the secret:

- `configs/<service>/.env`, a committed template with realistic but fake
  placeholder values, so the format stays self-documenting.
- `configs/<service>/.env.secrets`, real values, gitignored, never
  committed. Seeded on first `make bootstrap` from a committed
  `configs/<service>/.env.secrets.example` stub if it doesn't already exist,
  so `env_file` always resolves to a real path on a fresh clone.

Wire both into `env_file` as a two-item list, template first so the secrets
file overrides it (Compose merges `env_file` entries in order; later files
win on duplicate keys):

```yaml
env_file: ["${CONFIG_FOLDER}/grafana/.env", "${CONFIG_FOLDER}/grafana/.env.secrets"]
```

The service's `.gitignore` should except `.env` and `.env.secrets.example`,
but never `.env.secrets`. It stays caught by the blanket `*` rule (and the
root `.gitignore`'s `.env.*` pattern as a backstop). See `configs/grafana/`
for a working example.

## Shared anchors

`docker-compose-servarr.yml`'s `x-servarr-common` anchor bundles the keys
common to most servarr services (`networks`, `sysctls`, `restart`,
`security_opt`, `environment`, `volumes`) and follows this same key order
internally, so services that merge it in (`<<: [*servarr-common, ...]`) stay
consistent with services that don't use the shared anchor.
