# Storage Layout and External Storage

Everything the apps read and write splits into two trees:

| Tree | Contents | Where it belongs |
| ---- | -------- | ---------------- |
| `configs/`, `certs/`, `logs/`, `storage/` | app databases, settings, certificates, observability data | local disk, always |
| `data/` | downloads, media libraries, cover art, app backups | local disk or external storage |

`DATA_FOLDER` in `.env` is the single knob that relocates the second tree.
Every other data path derives from it, so nothing else needs editing:

```shell
DATA_FOLDER=./data
TORRENTS_FOLDER="${DATA_FOLDER}/torrents"
USENET_FOLDER="${DATA_FOLDER}/usenet"
DOWNLOADS_FOLDER="${DATA_FOLDER}/downloads"
MEDIA_COVERS_FOLDER="${DATA_FOLDER}/media/covers"
APP_BACKUPS_FOLDER="${DATA_FOLDER}/backups"
```

## The One Share Rule

If `data/` moves onto a network share, it must be **one share, mounted once**.

The *arr apps import by hardlinking from the download directory into the
library, so the file exists in both places while occupying disk once. Hardlinks
cannot cross filesystems, and two mounts are two filesystems even when they
point at the same server, because the kernel compares superblocks rather than
paths. Split `data/torrents` and `data/media` across separate mounts and every
import silently falls back to a full copy.

The cost is not theoretical. On a seeding setup, most of the library is
hardlinked into the download tree, so `du` on either directory alone reports
close to the size of the whole tree. Lose the links and those bytes stop being
shared: the same content can approach twice the disk it occupied before.

To see how much is at stake on a given install, count what is currently
shared:

```shell
find data -type f -links +1 | wc -l
```

## Verifying a Share Before Committing to It

Mount the candidate share somewhere scratch and check four things:

```shell
mkdir -p /mnt/probe/{a,b}

# 1. hardlinks work across subdirectories
touch /mnt/probe/a/hl && ln /mnt/probe/a/hl /mnt/probe/b/hl
stat -c '%h %i %n' /mnt/probe/{a,b}/hl        # want link count 2, same inode

# 2. real server inode numbers, which rsync -H and the apps depend on
findmnt -no OPTIONS -T /mnt/probe | tr ',' '\n' | grep serverino

# 3. atomic rename, how every import finishes
mv /mnt/probe/a/hl /mnt/probe/a/hl2

# 4. SELinux xattr support, to confirm :z has to go
setfattr -n security.selinux -v system_u:object_r:container_file_t:s0 \
  /mnt/probe/a/hl2                            # expect Operation not supported
```

`EXDEV` on step 1 means the tree is split across mounts. `noserverino` on step
2 means the share cannot be used for a hardlinked library.

## CIFS Specifics

`.env` carries the mount settings under `### EXTERNAL STORAGE`. Two of the
options are load bearing and should not be "tidied up":

- **`noperm`** — under rootless Podman the host user maps to uid 0 inside the
  container namespace, so a service running as uid 1101 falls through to
  *other* permissions and gets read-only access to its own downloads. `noperm`
  skips the client-side check and makes the SMB credentials the access
  boundary.
- **`serverino`** — keeps the server's real inode numbers, which is the only
  reason hardlinks are visible to `rsync -H` and to the apps at all.

`nobrl` is deliberately **absent**. It disables byte-range locking, and both
Calibre and Calibre-Web write `data/media/calibre-library/metadata.db`, so
SQLite needs the server to arbitrate those locks. That database is in
`journal_mode=delete` rather than WAL, which is what makes it viable over a
network filesystem at all; WAL requires shared memory that CIFS cannot provide.

### SELinux

CIFS has no `security.selinux` xattr, so Podman's `:z` relabel fails against
it. The label comes from the mount instead, via `STORAGE_SELINUX_CONTEXT`, and
the compose files use `${DATA_VOLUME_FLAGS}` so the per-volume suffix can be
emptied:

```shell
DATA_VOLUME_FLAGS=:z   # local data/
DATA_VOLUME_FLAGS=     # data/ on CIFS
```

### Permissions

CIFS carries no per-file ownership or POSIX ACLs; the mount options fix uid,
gid and mode for the whole tree. `scripts/permissions.py` detects this and
skips `chown`, `chmod` and `setfacl` for any path on such a filesystem, while
still creating the directories and still running the hardlink smoke test. Paths
under `configs/`, `certs/`, `logs/` and `storage/` stay on local disk and keep
the full ownership model.

Without that detection `make start` would fail before starting anything, since
it depends on `permissions_repair`.

## NFS as an Alternative

NFSv4 preserves real uid/gid and ACLs, which would let `permissions.yml` apply
unchanged rather than being skipped. It also supports Kerberos authentication.
If the server offers it, it is worth comparing before committing to SMB.

---

See also: [PERMISSIONS.md](PERMISSIONS.md), [BACKUP.md](BACKUP.md),
[README.md](../README.md)
