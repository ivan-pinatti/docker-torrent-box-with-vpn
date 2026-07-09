ARG BASE_VERSION=latest
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
