# Readarr

Readarr manages ebooks and audiobooks. This stack also uses it for comics
stored under `data/media/comics`, alongside Mylar (see `docs/MYLAR.md`).

## Comic quality profile

Readarr has no built-in quality definitions for CBZ or CBR files, so the stack
ships a setup script that adds them directly to the Readarr database:

```sh
python3 scripts/readarr-add-comic-profile.py
```

The script is idempotent. It inserts:

- A `Comic` quality profile that allows Unknown Text (where CBZ and CBR
  releases land) and PDF, and disallows the audio and ebook qualities.
- `CBZ` and `CBR` custom formats matching release titles on file extension.
- A default profile assignment for the `/data/media/comics/` root folder.

If the profile, formats, or root folder already exist, the script reports that
and skips them.

### Safe usage

The script writes to `configs/readarr/config/readarr.db` directly, so the
usual SQLite rules apply (see the repository instructions):

1. Stop Readarr first: `podman stop readarr`.
2. Run the script.
3. Repair sidecar file ownership with `make permissions_repair` (or run
   `./scripts/permissions.py repair --runtime podman --recursive` directly).
4. Start Readarr again: `podman start readarr`.

For testing, the database path can be overridden with the `READARR_DB`
environment variable so the script runs against a copy instead of the live
database.
