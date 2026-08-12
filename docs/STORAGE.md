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

## Keep DATA_FOLDER Repository Relative

External storage is mounted **at** `data/` rather than pointed at from
elsewhere: `STORAGE_MOUNTPOINT` defaults to `${DATA_FOLDER}`, and
`scripts/permissions.py` resolves every path in `permissions.yml` against the
repository root, refusing anything that escapes it. That containment check is
deliberate, since the manifest drives recursive `chown` and `setfacl` under
`podman unshare`.

A mount at `data/` keeps those paths inside the repository, so ownership
handling and the external-filesystem detection below both work normally.
Pointing `DATA_FOLDER` at an absolute path outside the repository instead
would leave compose reading from one tree while the permissions manifest
managed another. Symlinking `data/` elsewhere does not work either: the
symlink resolves outside the repository and the manifest run stops with
`refusing path outside repository`.

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

### Never Mount External Storage Directly Under /config

LinuxServer images run `lsiown -R abc:abc /config` on **every** container start.
Mount a share at a path inside `/config` and that walk crosses the network, once
per start, forever. It cannot even converge: the CIFS mount forces a single
`uid=`, so those files always report an owner that is not `abc`, and the filter
`! -user abc` matches the whole set again on the next start.

Confirmed live: Lidarr with its artwork bind mounted at `/config/MediaCover`
never finished starting. The chown sat in uninterruptible sleep against
thousands of files over SMB, and the container went unhealthy.

Mount outside `/config` and put a symlink where the app expects the directory:

```yaml
- ${MEDIA_COVERS_FOLDER}/lidarr:/mediacover${DATA_VOLUME_FLAGS}
- ${APP_BACKUPS_FOLDER}/lidarr:/appbackups${DATA_VOLUME_FLAGS}
```

with `configs/lidarr/config/MediaCover -> /mediacover` and
`configs/lidarr/config/Backups -> /appbackups`. `lsiown`'s `find` runs without
`-L`, so it does not descend into a symlinked directory: it touches one link
instead of the tree behind it. Measured on a test tree, the same walk visited 2
entries via a symlink against 9 for a real directory, and the real case is
thousands. The apps follow the symlink and neither knows the difference.

### Cold Reads and Proxy Timeouts

The first listing of a large library has to stat every item across the network,
and that can outrun nginx's 60s `proxy_read_timeout` while the app itself is
healthy. Lidarr's `/api/v1/artist` took over a minute cold and 2s once the
attribute cache had filled, surfacing in the browser as a 504 and the app's own
"Failed to load" page.

Two settings blunt this: `proxy_read_timeout 180s` on the app locations in
`configs/nginx/templates/default.conf.template`, and a longer `actimeo` in
`STORAGE_CIFS_EXTRA_OPTIONS` so cached metadata survives between visits. The
tradeoff on `actimeo` is that changes made directly on the server take that
long to become visible to the stack, which for a media library is not a
concern.

## Surviving a Reboot

`make storage_install_boot` appends one `/etc/fstab` entry, after printing the
exact line and requiring you to type `yes`. It backs the file up first and
verifies the result parses.

The options are `_netdev,nofail` plus everything from the `### EXTERNAL
STORAGE` block. `_netdev` orders the mount after the network. `nofail` means
the unit is only *wanted* by `remote-fs.target` and is not ordered before it,
so a NAS that is down cannot hold up boot.

**Not `x-systemd.automount`.** It sounds like the right tool and is the wrong
one here. It leaves an autofs mount at the path until something accesses it,
and autofs reports its source as `systemd-1` rather than the share:

```shell
findmnt -t autofs -o TARGET,SOURCE,FSTYPE
```

Every check in `storage-mount.sh` matches on `--source`, and `findmnt` reads
`/proc/self/mountinfo` without ever touching the path, so it cannot trigger the
automount it is asking about. The result is that `make storage_status` reports
`NOT MOUNTED` and `make start` refuses, on a healthy share, after every reboot
until something happens to touch `data/`. `nofail` already gives the
non-blocking boot that automount was wanted for.

Because the mount is not ordered before boot completes, the stack can still
reach `make start` before the share is up. That is what `storage_guard`
catches, and why it fails closed.

## NFS as an Alternative

NFS preserves real uid/gid and supports ACLs, so `permissions.yml` applies
there exactly as it does on local disk, rather than being skipped the way it is
on CIFS. NFSv4 also supports Kerberos authentication. If the server offers it,
it is worth comparing before committing to SMB.

That does depend on the export cooperating. An export that squashes root, or a
server without NFSACL/NFSv4 ACL support, will reject the `chown` or `setfacl`
and `make permissions_repair` will stop with that error rather than skip it.
That is deliberate: on storage chosen specifically to preserve ownership, a
silent skip would leave the tree with whatever the export decided and no
indication the model had stopped applying.

---

See also: [PERMISSIONS.md](PERMISSIONS.md), [BACKUP.md](BACKUP.md),
[README.md](../README.md)
