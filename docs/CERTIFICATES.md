# Certificate

At this moment the stack only supports self-signed certificates. `make bootstrap`
generates one automatically if `certs/server.pfx` doesn't already exist yet.

## Customize the subject fields

Certificate subject fields live in `certs/cert.conf`, not `.env`. Running any
`make` target seeds it from `certs/cert.conf.example` the first time, so edit
it after that first run if you want to change a parameter, then regenerate:

```dotenv
# Certificate details
CERT_COUNTRY=CS
CERT_STATE=Classified
CERT_CITY=Classified
CERT_ORGANIZATION=Classified
CERT_OU=Classified
CERT_FQDN=${DOMAIN} # it will use the previously declared DOMAIN variable from .env
```

```shell
make generate_certificate
```

This creates the `server.key`, `server.crt`, and `server.pfx` in the `/certs/` folder.

## Use your own certificate

If you have your own certificate, just copy them to the `/certs` folder using the exact names.

Remember, the `server.key`, `server.crt`, and `server.pfx` have to match the
`uid` and `gid`. The permissions have to be `644` for all three files: the
certificate is read by many services running as distinct non-root container
UIDs under rootless Podman, so the files must stay world-readable. The pfx
private key is protected by the PKCS#12 password.
