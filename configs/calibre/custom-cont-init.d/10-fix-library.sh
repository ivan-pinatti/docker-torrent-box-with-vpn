#!/bin/sh
if [ ! -d /data/media/calibre-library ]; then
  echo "ERROR: /data/media/calibre-library not found — data volume not mounted?" >&2
  exit 1
fi
chown -R abc:abc /data/media/calibre-library
exit 0
