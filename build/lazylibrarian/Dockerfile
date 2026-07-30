# linuxserver.io images run their s6-overlay init as root and drop to the
# PUID/PGID identity themselves, so a USER instruction here would break startup
# before the app ever runs. Health is defined per service in the compose files,
# where it can probe the real HTTP endpoint and port rather than guess.
# Trivy reports the same two findings as DS-0002 and DS-0026; its inline
# ignores do not apply to whole-file checks, so those live in .trivyignore.yaml.
#checkov:skip=CKV_DOCKER_3:s6-overlay must init as root; the app runs as PUID/PGID
#checkov:skip=CKV_DOCKER_2:healthcheck is defined on the service in docker-compose-servarr.yml

# No default: compose always passes BASE_VERSION from ${LAZYLIBRARIAN_VERSION},
# and a bare `docker build` should fail loudly rather than quietly produce an
# image built on :latest that no longer matches the pinned version.
ARG BASE_VERSION
FROM ghcr.io/linuxserver/mods:universal-calibre AS calibre-mod

FROM docker.io/linuxserver/lazylibrarian:${BASE_VERSION}
COPY --from=calibre-mod /calibre.txz /calibre.txz
COPY --from=calibre-mod /CALIBRE_RELEASE /CALIBRE_RELEASE
COPY --from=calibre-mod /etc/s6-overlay/s6-rc.d/init-mod-universal-calibre-add-package/run /tmp/calibre-deps.sh
RUN apt-get update && \
    bash /tmp/calibre-deps.sh && \
    apt-get install -y --no-install-recommends $(cat /mod-repo-packages-to-install.list 2>/dev/null || true) && \
    rm -rf /var/lib/apt/lists/* /tmp/calibre-deps.sh /mod-repo-packages-to-install.list && \
    mkdir -p /app/calibre && \
    tar xf /calibre.txz -C /app/calibre && \
    /app/calibre/calibre_postinstall && \
    rm /calibre.txz
