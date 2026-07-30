# linuxserver.io images run their s6-overlay init as root and drop to the
# PUID/PGID identity themselves, so a USER instruction here would break startup
# before the app ever runs. Health is defined per service in the compose files,
# where it can probe the real HTTP endpoint and port rather than guess.
# Trivy reports the same two findings as DS-0002 and DS-0026; its inline
# ignores do not apply to whole-file checks, so those live in .trivyignore.yaml.
#checkov:skip=CKV_DOCKER_3:s6-overlay must init as root; the app runs as PUID/PGID
#checkov:skip=CKV_DOCKER_2:healthcheck is defined on the service in docker-compose-servarr.yml

# No default: compose always passes BASE_VERSION from ${MYLAR_VERSION}, and a
# bare `docker build` should fail loudly rather than quietly produce an image
# built on :latest that no longer matches the pinned version.
ARG BASE_VERSION
FROM docker.io/linuxserver/mylar3:${BASE_VERSION}

RUN /lsiopy/bin/python3 -m pip install --no-cache-dir \
    -f https://wheel-index.linuxserver.io/ubuntu/ \
    pyOpenSSL
