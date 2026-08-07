# SABnzbd

SABnzbd is exposed directly on `SABNZBD_HTTP_PORT=8086` and
`SABNZBD_HTTPS_PORT=8087`, with `/sabnzbd` as its URL base. The bundled config
uses the shared certificate at `/certs/server.crt` and `/certs/server.key`.

Servarr, Mylar, LazyLibrarian, Notifiarr, and the SABnzbd exporter use the API
key from `configs/sabnzbd/config/sabnzbd.ini`. The exporter scrapes SABnzbd over
the internal HTTP listener to avoid self-signed certificate verification issues.
SABnzbd also has an NZB key (`SABNZBD_NZB_KEY`) that is rotated with the API key.

SABnzbd is configured to avoid IPv6 listener/server use and ships categories for
`tv`, `movies`, `music`, `books`, `audiobooks`, `comics`, and `mature` with
matching subfolders under `/data/usenet/complete`. Additional category folders
are managed by the permissions manifest when needed. Incomplete Usenet downloads
use `/data/usenet/incomplete`.

The SABnzbd defaults also apply the TRaSH Guides media-download recommendations
that fit this stack: a 5-minute propagation delay, a media-safe
unwanted-extension blacklist that fails matching jobs to history, disabled SAB
sorting, NZB backup history, and balanced post-processing for the Intel Celeron
N5095 class of host (`direct_unpack` enabled with two unpack threads).
