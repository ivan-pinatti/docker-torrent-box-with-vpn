# Dependency Updates

Two bots open dependency pull requests here, Dependabot and Renovate, and each owns a
different slice of the surface. This page is the reference for what runs when and why the
schedule is shaped the way it is. The mechanics of how a bump actually merges live in
[docs/CONTRIBUTING.md](CONTRIBUTING.md) step 8; this page does not repeat them.

## Which tool manages what

| Ecosystem | Tool | Where the pin lives |
| --- | --- | --- |
| pre-commit hook revisions | Dependabot | `.pre-commit-config.yaml`, the `rev:` of each hook repo |
| GitHub Actions | Dependabot | Workflow `uses:` versions under `.github/workflows/` |
| pip, test suite | Dependabot | `tests/requirements.txt` |
| Docker image versions | Renovate | `.env.example`, behind a `# renovate: depName=...` annotation |
| pip, inline in a workflow | Renovate | A `pip install pkg==x` line, behind a `# renovate:` annotation |
| Go module and pypi pins in pre-commit | Renovate | `additional_dependencies` in `.pre-commit-config.yaml` |
| Docker images pinned inside a hook `entry:` | Renovate | `.pre-commit-config.yaml` and the workflow SARIF job |

The split exists because Dependabot's pip ecosystem only reads requirements files. It would
never see `pip install podman-compose==1.6.0` sitting inside a workflow's `run:` step, so a pin
left unwatched there rots silently, which is exactly how CI once ended up installing whatever
version of `podman-compose` happened to be current. Renovate's `# renovate:` annotations are
the seam that covers those inline pins, and the reasoning is spelled out in the header comment
of [`.github/renovate.json5`](../.github/renovate.json5); this page reuses that reasoning rather
than restating it differently.

## The weekday layout

| Day | Tool | What opens |
| --- | --- | --- |
| Monday | Dependabot | pre-commit hook revisions |
| Tuesday | Dependabot | GitHub Actions |
| Wednesday | Dependabot | pip, `tests/requirements.txt` |
| Thursday | Renovate | The arr suite group (sonarr, radarr, lidarr, readarr, prowlarr, bazarr, recyclarr) |
| Friday | Renovate | The observability stack group and the library and reading tools group |
| Saturday | Renovate | Every ungrouped image, one pull request each (the root schedule, used as the default) |
| Sunday | Renovate | The lint and scanner tooling group and the container runtime tooling pin |

## Why the days are staggered

Required status checks are strict on `main`, which is the setting that makes the stagger worth
doing. Every merge puts every other open pull request behind, so each one needs a rebase and
another full run of the integration suite, roughly fifteen minutes a time. If every ecosystem
opened on the same day, the pull requests it produced would queue behind each other: the first
merge rebases the rest, which triggers another round of runs, which produces another merge that
rebases what is left again. Spreading the ecosystems and groups across the week keeps that churn
from compounding into one bad day. `docs/TODO.md` records a case where a single small change
needed three separate suite runs for this reason, before the schedule was spread out.

## The grouping rationale

Grouping in `.github/renovate.json5` is about pull request volume against blast radius, not a
shared release cadence, and it is worth being explicit that the cadence framing would be
fiction. Image creation dates measured with `skopeo inspect` on 2026-08-18:

| Image | Build date |
| --- | --- |
| nzbget | 2025-05-09 |
| readarr | 2025-06-27 |
| gluetun | 2026-02-11 |
| qbittorrent | 2026-05-03 |
| jellyfin | 2026-06-02 |
| bazarr | 2026-06-30 |
| radarr | 2026-08-02 |
| calibre-web | 2026-08-02 |
| loki | 2026-08-05 |
| prowlarr | 2026-08-05 |
| sabnzbd | 2026-08-06 |
| sonarr | 2026-08-07 |
| lidarr | 2026-08-12 |

Fifteen months separate the oldest and newest build in that list, so nothing here releases on a
shared schedule. The arr suite, the observability stack, and the library and reading tools are
grouped anyway, purely to keep the number of pull requests down, and grouping only makes sense
where a bad member costs little: those three groups hold images that have not caused a problem
recently, or, for the observability stack, sit behind a profile that is disabled by default.

The download clients (qbittorrent, sabnzbd, nzbget, nzbhydra2, jdownloader-2), jellyfin,
homepage, flaresolverr, wireguard, and gluetun are deliberately left out of every group, so each
arrives as its own pull request on the Saturday default instead. A group is only as mergeable as
its worst member, and this week supplied two examples, both download clients: SABnzbd 5.0.4
rewrote its own bind address in a way that broke a test (see `docs/TODO.md`), and qBittorrent
5.2.2 changed its login response to `204 No Content`, which is still holding pull request #83.
Had either of those shipped inside a group, it would have blocked every other image bundled with
it rather than only itself. gluetun is isolated for the same reason: it is what the download
clients' kill switch depends on, so a bad gluetun bump is exactly the kind of failure a group
should not be allowed to spread.

## Security updates

Both bots' security paths are alert driven and enabled on this repository, and neither reads the
schedules above at all. Dependabot's security updates open as soon as GitHub raises an alert.
Renovate's `vulnerabilityAlerts` setting clears the inherited `minimumReleaseAge` window, so a
fix for a known vulnerability is never held back by the cooling period described below.

That coverage has a real gap, and it is worth stating plainly rather than leaving it implicit.
The dependency graph GitHub builds for this repository holds 17 packages, all GitHub Actions and
pip, and zero container images: GitHub raises no vulnerability alert for a container image at
all, so the images in `.env.example` get no security signal from this mechanism, ever. Scanning
the images themselves was considered and deliberately declined, because they are third party and
not ours to patch: nothing here can fix a vulnerability inside a published image, only wait for
upstream to. The practical consequence is that the seven day `minimumReleaseAge` window in
`.github/renovate.json5` is pure latency for every image bump, with nothing available to bypass
it the way `vulnerabilityAlerts` bypasses it for Actions and pip. That is a conscious trade, not
a hedge: see [docs/HARDENING.md](HARDENING.md) for the full reasoning behind leaning on the
cooling window instead of a scanner for this class of dependency.

## Known gaps

Twelve image pins in `.env.example` carry no `# renovate:` annotation at all, so Renovate cannot
see them and they stay frozen at whatever version is committed: `CADVISOR_VERSION`,
`MYLAR_VERSION`, `NGINX_EXPORTER_VERSION`, `NODE_EXPORTER_VERSION`, `NOTIFIARR_VERSION`,
`PODMAN_LIMITS_EXPORTER_VERSION`, `PODMAN_EXPORTER_VERSION`, `ALLOY_VERSION`,
`LOG_ROTATOR_VERSION`, `QBITTORRENT_EXPORTER_VERSION`, `SABNZBD_EXPORTER_VERSION`, and
`JACKETT_VERSION`. Annotating them is a follow up, not part of this change.

Separately, three tags are deliberately left floating rather than pinned to a version at all:
`NGINX_VERSION=stable-alpine`, `PLEX_VERSION=latest`, and `WHISPARR_VERSION=v3`.

`LAZYLIBRARIAN_VERSION` is annotated and Renovate does see it, but unlike every other annotated
pin in the file it carries no digest, only a loose upstream tag. It is the one annotated pin
this change did not add a digest to, since inventing one would not be honest about what has
actually been verified.

---

See also: [README.md](../README.md), [docs/HARDENING.md](HARDENING.md),
[docs/CONTRIBUTING.md](CONTRIBUTING.md), [docs/TESTING.md](TESTING.md),
[docs/TODO.md](TODO.md)
