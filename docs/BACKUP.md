# Backup and Restore

This project has two backup modes:

- `make backup` or `make backup-configs`: lean backup for day-to-day recovery.
- `make backup-full`: larger backup that keeps application artwork and metadata.

Stop the containers before backing up or restoring if you need database-consistent
archives:

```shell
make stop
```

## Config Backup

Use the default backup for regular operational recovery:

```shell
make backup
```

This creates:

```text
backup/configs-YYYY-MM-DD-HHMMSS.tar.gz
```

The config backup includes `.env`, `certs/`, and `configs/`, but skips heavy or
regenerable runtime state such as media artwork, metadata caches, logs, Sentry
state, app-generated backup archives, transient SQLite WAL/SHM files, and cloned
Recyclarr resource repositories.

Audiobookshelf stores app backups under `/metadata/backups`, and those backups
can include state and images from `/metadata/items` and `/metadata/authors`.
The full `/metadata` tree is bind mounted on the host at
`configs/audiobookshelf/metadata` and included in the config backup.

Use this when you want the smallest practical backup that can restore service
settings, secrets, certificates, and primary app databases.

## Full Config Backup

Use the full mode when you also want application artwork and metadata state:

```shell
make backup-full
```

This creates:

```text
backup/full-YYYY-MM-DD-HHMMSS.tar.gz
```

The full backup includes `.env`, `certs/`, and all of `configs/`, including
artwork and metadata caches. It still does not include repository metadata,
tests, MegaLinter reports, media/download libraries, observability storage,
runtime cache folders, or dependencies.

## Restore

Restore requires an explicit archive path:

```shell
make restore-configs BACKUP=backup/configs-YYYY-MM-DD-HHMMSS.tar.gz
```

or:

```shell
make restore-full BACKUP=backup/full-YYYY-MM-DD-HHMMSS.tar.gz
```

Before replacing local state, restore creates a safety archive:

```text
backup/pre-restore-YYYY-MM-DD-HHMMSS.tar.gz
```

The restore command replaces `.env`, `certs/`, and `configs/` from the archive.
Stop containers first, restore the archive, then start the stack again.

```shell
make stop
make restore-configs BACKUP=backup/configs-YYYY-MM-DD-HHMMSS.tar.gz
make start
```

## What Is Not Backed Up

Neither backup mode includes media/download libraries or repository-only state:

- `.git/`
- `tests/`
- `megalinter-reports/`
- `data/`
- `media/`
- `storage/`
- `cache/`
- `logs/`
- `node_modules/`

Back up media libraries separately with a storage-level or filesystem backup
tool if you need disaster recovery for downloaded media.
