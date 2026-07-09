ARG BASE_VERSION=latest
FROM docker.io/linuxserver/mylar3:${BASE_VERSION}

RUN /lsiopy/bin/python3 -m pip install --no-cache-dir \
    -f https://wheel-index.linuxserver.io/ubuntu/ \
    pyOpenSSL
