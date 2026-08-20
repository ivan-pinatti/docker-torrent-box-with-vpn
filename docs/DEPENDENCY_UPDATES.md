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
| Friday | Renovate | The observability stack group (ten images) and the library and reading tools group |
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

The observability stack is the group where that reasoning is load-bearing, because it went from
three images to ten when the exporters were annotated, and because the integration suite never
touches any of them. `make pull_docker_images` pulls `--profile enabled` only, and
`integration-tests.yml` flips nothing but `VPN_MOCK_PROFILE`, so those ten images are never
pulled, never started, and every test carrying the `observability` marker skips. A bump in that
group merges on `Prerequisite Checks` and `Security Reports` alone. That is accepted on the
grounds that the profile ships disabled, so a bad image there breaks nothing until someone turns
it on, and the alternative on offer was the frozen pins in the table below.

`docker.io/library/alpine`, which `log_rotator` runs, is the one observability image left out of
that group. `LOG_ROTATOR_PROFILE` ships enabled, so CI does pull and start it, which is coverage
no other image in the stack gets, and grouping it in would trade that away for nothing.

The download clients (qbittorrent, sabnzbd, nzbget, nzbhydra2, jdownloader-2), jellyfin,
homepage, flaresolverr, wireguard, and gluetun are deliberately left out of every group, so each
arrives as its own pull request on the Saturday default instead. sabnzbd and jdownloader-2 arrive
with nothing at all while the hold described under "Images pinned to a patch" stands; the
isolation still describes where they land the day it is lifted. A group is only as mergeable as
its worst member, and this week supplied two examples, both download clients: SABnzbd 5.0.4
rewrote its own bind address in a way that broke a test (see `docs/TODO.md`), and qBittorrent
5.2.2 changed its login response to `204 No Content`, which is still holding pull request #83.
Had either of those shipped inside a group, it would have blocked every other image bundled with
it rather than only itself. gluetun is isolated for the same reason: it is what the download
clients' kill switch depends on, so a bad gluetun bump is exactly the kind of failure a group
should not be allowed to spread.

Four more pins are ungrouped without that argument applying to them, simply because there is no
group they belong in: `docker.io/library/alpine` for the reason above,
`docker.io/linuxserver/mylar3` because it is the base of a wrapper this repository builds rather
than an image it pulls, `ghcr.io/notifiarr/notifiarr` because its service is commented out, and
`docker.io/linuxserver/jackett` because it has no service at all. The last two are watched
anyway. An unwatched pin is the thing this arrangement exists to prevent, and a year stale image
is a worse starting point than a current one for whoever turns either service back on.

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

## What was frozen, and for how long

Twelve image pins carried no `# renovate:` annotation, so Renovate could not see them and they
sat at whatever version was committed. Their build dates, measured with `skopeo inspect` on
2026-08-20 alongside the newest tag available on the same day:

| Pin | Image | Pinned build | Newest available |
| --- | --- | --- | --- |
| `QBITTORRENT_EXPORTER_VERSION` | `ghcr.io/esanchezm/prometheus-qbittorrent-exporter` | 2024-10-25 | `v1.7.0` |
| `NGINX_EXPORTER_VERSION` | `docker.io/nginx/nginx-prometheus-exporter` | 2024-12-04 | `1.5.3` |
| `CADVISOR_VERSION` | `gcr.io/cadvisor/cadvisor` | 2025-03-20 | `v0.55.1` |
| `SABNZBD_EXPORTER_VERSION` | `docker.io/msroest/sabnzbd_exporter` | 2025-11-07 | already current |
| `PODMAN_EXPORTER_VERSION` | `quay.io/navidys/prometheus-podman-exporter` | 2025-12-22 | `v1.21.2` |
| `NODE_EXPORTER_VERSION` | `docker.io/prom/node-exporter` | 2026-04-07 | `v1.12.1` |
| `PODMAN_LIMITS_EXPORTER_VERSION` | `docker.io/library/python` | 2026-04-17 | held, see below |
| `ALLOY_VERSION` | `docker.io/grafana/alloy` | 2026-04-23 | `v1.18.1` |
| `JACKETT_VERSION` | `docker.io/linuxserver/jackett` | 2026-04-23 | `0.24.2424` |
| `MYLAR_VERSION` | `docker.io/linuxserver/mylar3` | 2026-05-01 | `v0.11.0-ls268` |
| `LOG_ROTATOR_VERSION` | `docker.io/library/alpine` | 2026-06-22 | `3.24` |
| `NOTIFIARR_VERSION` | `ghcr.io/notifiarr/notifiarr` | the tag did not exist | `v0.9.5` |

The three oldest are between 17 and 22 months behind. All twelve are annotated now, and
`tests/test_renovate_pins.py` fails the suite if a pin is ever added without an annotation
again.

`NOTIFIARR_VERSION` deserves its own line, because the pin was not merely stale. It read
`v0.9.5-alpine`, and that tag does not exist: Notifiarr stopped publishing the `-alpine`
variant after `v0.9.1-alpine` when Alpine became the default flavour, so the plain
`v0.9.5` tag is the same image. Nothing noticed because the `notifiarr` service block is commented
out in `docker-compose-servarr.yml`, so nothing ever tried to pull it. `docker` versioning would
also have refused to update it forever, since the compatibility suffix `alpine` has to match
exactly and no `-alpine` tag above `0.9.1` exists.

`KORSYNC_VERSION` was a thirteenth case, and the one worth understanding, because it looked
watched. Its annotation read `# renovate: datasource=docker depName=...`, and the custom manager
in `.github/renovate.json5` matches `# renovate: depName=` only, so that one extra word made the
whole pin invisible while reading exactly like every other line in the file. `datasource` was
redundant anyway, because the manager sets `datasourceTemplate: "docker"` for every pin it reads.
That is the case the new test's fourth check exists for: it runs the manager's own regex against
`.env.example` and fails when the annotations present in the file and the ones Renovate can
actually parse are not the same set.

## Images held at a fixed version

Four containers run a file bind mounted out of `patches/`: sabnzbd, lazylibrarian, mylar, and
jdownloader-2. Their images are held at a fixed version in `.github/renovate.json5`, with
`enabled: false`, until the patch that made each one special is gone.

The reason is that a patch shadows one file inside an image, and nothing in this repository can
tell whether the shadowing copy still matches the file it replaces. An unattended bump pairs
patched old source with new upstream code, and the result starts, reports healthy, and passes the
suite while being subtly wrong. mylar shows the scale of it: its first offered bump is
`v0.9.0-ls252` to `v0.11.0-ls268`, which `loose` versioning calls a minor because both share
major `0`, so it would have merged unattended across two upstream minor releases with five
patched files mounted over it. The alternative to holding the pin is re-deriving each patch
against each release, which is work with no end date and no test that would catch getting it
wrong.

The hold covers digest refreshes too, not only version bumps. Two of the four patches shadow a
file belonging to the image rather than to the application: `patches/sabnzbd/svc-sabnzbd/run` is
an s6 service script and `patches/jdownloader2/10-webauth.sh` is a `baseimage-gui` init script,
and a rebuild of the same tag is exactly how either changes underneath the patch. `docs/TODO.md`
already frames the jdownloader-2 case that way, since the fix it waits on arrives as a
`baseimage-gui` bump inside an image whose tag need not move.

Worth being explicit about the cost: sabnzbd and jdownloader-2 were both flowing, and merging
unattended, before this. It costs less than it looks like, because, as the section above says,
GitHub raises no vulnerability alert for a container image at all, so neither pin had a security
path that this closes. What is given up is routine version updates on two download clients, and a deliberate
hand bump is what replaces them.

`docker.io/library/python` is held too, for a different reason, and it is the only pin in
`.env.example` where the image is not the application. `podman_limits_exporter` runs a bare
interpreter over `scripts/podman-limits-exporter.py`, this repository's own code, bind mounted in
as `/exporter.py`, so a Python minor bump swaps the interpreter out from under code written here
rather than shipping a new version of somebody else's program. Nothing tests that:
`PODMAN_LIMITS_EXPORTER_PROFILE` ships disabled and `integration-tests.yml` never enables it, so
automating the bump safely means enabling the observability profile in CI, which is a piece of
work of its own rather than a config line. Holding it costs little, because `3.13-alpine3.22` only
ever moved in one dimension anyway: `docker` versioning requires the compatibility suffix to match
exactly, so Renovate could offer `3.14-alpine3.22` and would never offer `3.13-alpine3.24`, which
exists.

`docker.io/library/alpine` has the same shape and is deliberately left flowing. `log_rotator` runs
`scripts/rotate-nginx-logs.sh` over a bare Alpine image, so that is our code too, but
`LOG_ROTATOR_PROFILE` ships enabled so CI does pull and start it, and a shell script against a new
BusyBox is a far smaller surface than our Python against a new interpreter.

`tests/test_renovate_pins.py` closes the loop in the other direction: it derives the patched set
from the `./patches/` volumes in the compose files rather than from a list, so a service that
grows a patch mount whose image is not held fails the suite. Each of the four has an open item in
`docs/TODO.md` for dropping its patch, and dropping one is what unfreezes its pin. That is the
distinction this whole page turns on: these pins are deliberately fixed, not accidentally frozen.

## Remaining gaps

Three tags are deliberately left floating rather than pinned to a version at all:
`NGINX_VERSION=stable-alpine`, `PLEX_VERSION=latest`, and `WHISPARR_VERSION=v3`.
`tests/test_renovate_pins.py` carries them in an explicit allowlist, so the exemption is a
decision on the record rather than an omission.

`LAZYLIBRARIAN_VERSION` and `MYLAR_VERSION` carry no digest, and cannot. Each is read twice out
of one variable: as the base image the wrapper in `build/` is built on, and as the tag of the
locally built result. A digest is legal in the first position and not in the second, because an
image being built can only be given a tag, so `pinDigests` is turned off for both in
`.github/renovate.json5` and the test exempts them by name. `docs/TODO.md` previously recorded
this the other way round, asking for a digest to be added to lazylibrarian; adding one would have
stopped the wrapper building.

One pin is watched and still cannot be ordered. `LAZYLIBRARIAN_VERSION=40a389ea-ls310` holds no
version number at all, so `loose` versioning parses the tag rather than refusing it and then
orders it wrongly: it reads the leading `40` as the version and ranks the current pin above
`9a2c0d5e-ls334`, comparing a commit hash fragment as a number. Renovate reports nothing to do
rather than reporting that it cannot tell, which is the worse of the two failures. The hold above
switches the pin off entirely today, so this matters on the day `patches/lazylibrarian/` is
dropped and not before, which is why `docs/TODO.md` asks for the versioning scheme to be settled
before the hold lifts rather than after.

`KORSYNC_VERSION` used to be the other case, pinned to `sha-7bcefd34...`, a commit tag nothing can
order. Upstream publishes plain semantic tags and has since well before that pin landed here on
2026-07-03, so the commit tag was never necessary. It now reads `0.2.3`, which is both a move
forward, since the release is dated 2026-07-15 against the pinned build's 2026-04-29, and a tag
Renovate can maintain by itself. `0.2.3`, `0.2` and `latest` all resolve to the same digest.

The distinction that matters is that a pin with no annotation is invisible, while a pin that
cannot be ordered is visible and merely stuck: Renovate looks it up every run, and the dependency
dashboard is where a lookup that resolves to nothing shows up.

---

See also: [README.md](../README.md), [docs/HARDENING.md](HARDENING.md),
[docs/CONTRIBUTING.md](CONTRIBUTING.md), [docs/TESTING.md](TESTING.md),
[docs/TODO.md](TODO.md)
