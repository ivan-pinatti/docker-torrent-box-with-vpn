# jDownloader2

jDownloader2 is exposed on `JDOWNLOADER2_HTTP_PORT=5800` (VNC web interface) and
`JDOWNLOADER2_API_PORT=3128` (local REST API).

## Web GUI authentication

The `jlesage/jdownloader-2` image serves the web interface behind
its own nginx `auth_request` gate. `configs/jdownloader2/.env` sets `SECURE_CONNECTION=1`
(https with a self-signed certificate) and `WEB_AUTHENTICATION=1` to require a login; the
credentials come from `WEB_AUTHENTICATION_USERNAME`/`WEB_AUTHENTICATION_PASSWORD` in
`configs/jdownloader2/.env.secrets` (gitignored, copy from `.env.secrets.example`), following the
same committed-template-plus-gitignored-secrets pattern as `configs/grafana/`; see
[COMPOSE_CONVENTIONS.md](COMPOSE_CONVENTIONS.md). Both env files are only read at container
creation, so a password change needs a recreate, not a restart:
`podman-compose --file docker-compose.yml --profile enabled up -d --force-recreate --no-deps jdownloader2`.
The healthcheck and the nginx reverse-proxy upstream both target `https://` for this reason.
`make rotate_passwords SERVICE=jdownloader2` handles the password rotation and recreate; see
[ROTATION.md](ROTATION.md).

## Memory tuning

The `jlesage/jdownloader-2` image runs the JVM alongside an X11 server and
VNC web layer. Without explicit heap limits, the JVM applies an ergonomic default of roughly 25%
of the container memory ceiling, which on a 1 GB limit is ~250 MB; combined with the GUI layer the
container can reach ~1 GB at idle after opening the web GUI. The image reads the heap cap from
`configs/jdownloader2/.env` and additional JVM options from
`configs/jdownloader2/config/JDownloader2.vmoptions`:

```dotenv
JDOWNLOADER_MAX_MEM=384m
```

```text
-Xms64m
-XX:+UseG1GC
-XX:MaxGCPauseMillis=200
-XX:+UseStringDeduplication
-XX:MaxMetaspaceSize=128m
```

This caps the heap at 384 MB and keeps idle memory within the 1 GB container limit.

## Bandwidth scheduling

jDownloader2 uses the EventScripter extension to apply the same
100 Mbps day / 500 Mbps night schedule as the other downloaders. The script is configured in
`configs/jdownloader2/config/cfg/org.jdownloader.extensions.eventscripter.EventScripterExtension.scripts.json`
with an INTERVAL trigger. It tracks the last applied limit via `getProperty`/`setProperty` and
calls `setSpeedlimit()` once per hour. The EventScripter sandbox's `setSpeedlimit(int bps)` function
is a direct
`ScriptEnvironment` method available in all event contexts; `callAPI()` and Java package access
are not available in the INTERVAL context.
