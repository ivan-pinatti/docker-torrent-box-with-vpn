#!/bin/sh

set -e # Exit immediately if a command exits with a non-zero status.
set -u # Treat unset variables as an error.

PASSWORD_FILE="/config/webauth-htpasswd"

# Nothing to do if web authentication is disabled.
if is-bool-val-false "${WEB_AUTHENTICATION:-0}"; then
    exit 0
fi

# Verify that secure connection is enabled.
if is-bool-val-false "${SECURE_CONNECTION:-0}"; then
    echo "ERROR: web authentication requires secure web access to be enabled."
    echo "       make sure to set SECURE_CONNECTION=1 environment variable."
    exit 1
fi

# Make sure the password db exists.
[ -f "${PASSWORD_FILE}" ] || touch "${PASSWORD_FILE}"

# Set permissions of the password db.
chmod 600 "${PASSWORD_FILE}"

# Patched: read credentials from the mounted compose secrets directly,
# rather than trusting WEB_AUTHENTICATION_USERNAME/PASSWORD. The baseimage's
# own CONT_ENV_<VAR> Docker-secrets loader (/init, stage cont-secrets) only
# sets a variable if it is currently *unset*, but this image's Dockerfile
# pre-declares both as empty-string env vars, so the loader always finds
# them already "set" (to "") and silently skips loading the secret. This is
# a confirmed upstream bug (same root cause as
# https://github.com/htpcBeginner/docker-traefik/issues/69, closed "not
# planned"), not something fixable via env_file or FILE__/CONT_ENV_
# conventions. See docs/COMPOSE_CONVENTIONS.md and docs/ROTATION.md.
if [ -f /run/secrets/jdownloader2_username ] && [ -f /run/secrets/jdownloader2_password ]; then
    WEB_AUTHENTICATION_USERNAME="$(cat /run/secrets/jdownloader2_username)"
    WEB_AUTHENTICATION_PASSWORD="$(cat /run/secrets/jdownloader2_password)"
fi

if [ -z "${WEB_AUTHENTICATION_USERNAME:-}" ] && [ -z "${WEB_AUTHENTICATION_PASSWORD:-}" ]; then
    if [ "$(stat -c "%s" "${PASSWORD_FILE}")" -eq 0 ]; then
        echo "WARNING: no user configured for web authentication"
    fi
elif [ -z "${WEB_AUTHENTICATION_USERNAME:-}" ] || [ -z "${WEB_AUTHENTICATION_PASSWORD:-}" ]; then
    echo "ERROR: missing username or password for web authentication user"
    echo "       make sure that both WEB_AUTHENTICATION_USERNAME and WEB_AUTHENTICATION_PASSWORD"
    echo "       environment variables are set."
    exit 1
else
    # Add password to database.
    echo "${WEB_AUTHENTICATION_PASSWORD}" | htpasswd -i "${PASSWORD_FILE}" "${WEB_AUTHENTICATION_USERNAME}"
fi

# vim:ft=sh:ts=4:sw=4:et:sts=4
