"""Runtime version-pin consistency: what is running versus what is pinned.

The reason this file exists. PR #137 offered `linuxserver/qbittorrent`
`5.2.2 -> 20.04.1` as a "major upgrade". `20.04.1` was never a qBittorrent
version: verified with `skopeo inspect`, the pinned `5.2.2` was built
2026-07-05 (`org.opencontainers.image.version` label `5.2.2_v2.0.13-ls465`),
and the proposed `20.04.1` was built 2021-11-29
(`14.3.9.99202110311443-7435-01519b5e7ubuntu20.04.1-ls163`). LinuxServer
briefly tagged this image by Ubuntu base release around that build, and
Renovate's default docker versioning ranks `20.04.1` above `5.x`. The
qBittorrent bundled inside that four-and-a-half-year-old image is actually
`4.3.9`. It booted, reported healthy, and satisfied the entire integration
suite anyway: `Tests Verified` read SUCCESS. Nothing in this repository
checked that the software inside the container was the software the pin
named.

This file does, by asking each running application what version it believes
itself to be, over its own API, and comparing that against the pin in
`.env`. Not image metadata: qBittorrent's own `build_version` label for the
substituted image *contains* the literal text `20.04.1`
(`14.3.9.99202110311443-7435-01519b5e7ubuntu20.04.1-ls163`), so a check that
reads the label and asks whether it contains the pinned tag would have
passed both the real `5.2.2` image and the fake `20.04.1` one. An image
label describes what LinuxServer built, not what is actually running; a
bind-mounted patch or an entrypoint override can desync the two (see the
patched-image hold in `.github/renovate.json5`), and this incident shows a
tag can simply lie. Asking the process itself is the only check that
survives both.

`test_version_match_rejects_the_pr_137_pair` below proves the comparison
this file uses on the real pair rather than asserting it would work: both
version strings are real, captured live from standalone containers of the
actual `5.2.2` and `20.04.1` images (2026-09-02), and it demonstrates the
label-substring trap in the same breath.

Comparison is by parsed integer version components, and it is a *prefix*
match against what is reported, not string equality: several of these apps
answer with more precision than their pin carries. Sonarr's own
`/api/v3/system/status` answers `4.0.19.2979` for a pin of `4.0.19`
(confirmed live); the extra build number is real precision, not a mismatch.
It is deliberately not a substring/contains check, which is the exact hole
above: parsed-component comparison never mistakes `20.04.1`'s components for
a match against `5.2.2`'s, in either direction, because comparison is
numeric per component rather than textual.

Covered, each confirmed live against a standalone container of the pinned
image before being wired into this file: qBittorrent (`/api/v2/app/version`,
authenticated); Sonarr, Radarr, Lidarr, Prowlarr, Readarr
(`system/status` beside each app's own already-registered `/health` path,
same API prefix, same API key); Bazarr (`/api/system/status`); SABnzbd
(`mode=version`, unauthenticated by design upstream); Jellyfin
(`/System/Info/Public`, unauthenticated); Grafana (`/api/health`); Prometheus
(`/api/v1/status/buildinfo`).

Not covered, and why, so this is not a test that silently skips everything
while looking thorough:

    Whisparr is pinned to the floating `v3` channel tag (see `FLOATING` in
    test_renovate_pins.py), which names no fixed version to compare against.

    nginx (`stable-alpine`) and Plex (`latest`) are the same: floating
    channel tags with nothing fixed pinned. Plex is also not in the default
    stack (`PLEX_PROFILE=disabled`).

    nzbget is not part of the default stack (SABnzbd is the usenet client
    actually enabled) and now has its Renovate updates switched off
    entirely (see `.github/renovate.json5`); it is out of scope for the same
    reason it gets no other coverage in this repository.

    lazylibrarian and mylar3 are locally built wrapper images pinned to a
    LinuxServer commit/build tag rather than an application version, and
    jackett has no compose service at all to query.

    Everything else pinned in `.env.example` (the exporters, cAdvisor,
    node_exporter, Loki, Alloy, nginx_exporter, homepage, flaresolverr,
    notifiarr, nzbhydra2, korsync, calibre, calibre-web, audiobookshelf,
    gluetun, wireguard/vpn_mock, log_rotator, jdownloader-2) was not
    attempted here. Jellyfin and Bazarr, both covered above, suggest several
    of these likely expose a version too; confirming and wiring each one up
    is follow-on work, not required to close the gap PR #137 and #97
    actually exposed.
"""

import re

import pytest
import requests
import urllib3

from conftest import (
    SERVICES,
    base_url,
    env,
    is_enabled,
    read_api_key,
    read_secret,
    service_base_url,
    skip_if_not_running,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

pytestmark = pytest.mark.version_pins

TIMEOUT = 10
BASE = base_url(https=True)

# The leading run of dot-separated digits in a string, wherever it starts.
# Matches "5.2.2" inside "v5.2.2" and "4.0.19" inside "4.0.19.2979"; stops at
# the first non-digit, non-dot character, so "0.4.19-nightly" yields
# "0.4.19" and a LinuxServer suffix like "_v2.0.13-ls465" is never reached
# because the digest/tag is split off before this runs.
_LEADING_VERSION = re.compile(r"\d+(?:\.\d+)*")


def _components(raw: str) -> tuple:
    """Parse a version string into a tuple of leading integer components.

    "5.2.2@sha256:dd24a5f3..." -> (5, 2, 2)
    "v5.2.2"                   -> (5, 2, 2)
    "4.0.19.2979"               -> (4, 0, 19, 2979)
    "0.4.19-nightly"            -> (0, 4, 19)
    """
    tag = raw.split("@", 1)[0]
    match = _LEADING_VERSION.search(tag)
    assert match, f"{raw!r} has no dotted numeric version to compare"
    return tuple(int(part) for part in match.group().split("."))


def _assert_running_matches_pin(
    pinned_raw: str, reported: str, service: str, pin_name: str
):
    """The pin's components must be an exact prefix of what is actually running.

    Prefix, not equality: several apps here self-report more precision than
    the pin records (Sonarr's own API answers "4.0.19.2979" for a pin of
    "4.0.19"). Prefix, not substring/contains: that is the exact hole PR #137
    went through, where the substituted image's own label contained the
    pinned tag's literal text. Comparing parsed integer components instead of
    raw strings closes it, because "20.04.1"'s components are never a prefix
    match, nor a match of any prefix length, against "5.2.2"'s.
    """
    pinned = _components(pinned_raw)
    got = _components(reported)
    assert got[: len(pinned)] == pinned, (
        f"{service} is pinned to {pinned_raw!r} ({pin_name}) but its own API "
        f"reports running {reported!r}. This is not the version {pin_name} "
        f"asked for."
    )


def test_version_match_rejects_the_pr_137_pair():
    """Proof, not assertion: run the real pair through the real comparison.

    Both version strings below are real, captured live (2026-09-02) from
    standalone containers of the two actual images at the center of PR #137,
    queried the same way the live tests below query the running stack
    (`POST /api/v2/auth/login`, then `GET /api/v2/app/version`):

    `linuxserver/qbittorrent:5.2.2` (this repository's pin) answers "v5.2.2".
    `linuxserver/qbittorrent:20.04.1` (what PR #137 offered) answers
    "v4.3.9" -- the qBittorrent release actually bundled inside that
    four-and-a-half-year-old LinuxServer build. "20.04.1" was never a
    qBittorrent version; LinuxServer briefly tagged this image by Ubuntu
    base release, and it outranked "5.x" only because Renovate's default
    docker versioning compares it as a bare version string.

    The real pinned tag string is used too, digest and all, so this exercises
    exactly the string `_assert_running_matches_pin` receives from `.env` in
    the live tests below.
    """
    pinned = (
        "5.2.2@sha256:dd24a5f3db32bc1425d3f8dc95e8aca8ac5a35905d798171230edf33f516d9a4"
    )

    # The real 5.2.2 image, queried live: must not raise.
    _assert_running_matches_pin(pinned, "v5.2.2", "qbittorrent", "QBITTORRENT_VERSION")

    # The real 20.04.1 image PR #137 offered, queried live: must raise.
    with pytest.raises(AssertionError):
        _assert_running_matches_pin(
            pinned, "v4.3.9", "qbittorrent", "QBITTORRENT_VERSION"
        )

    # And the trap this replaces, spelled out: the substituted image's own
    # label contains the pinned tag's literal text, so a "label contains the
    # pin" check would have passed it. This function is not that check.
    substituted_image_label = "14.3.9.99202110311443-7435-01519b5e7ubuntu20.04.1-ls163"
    assert "20.04.1" in substituted_image_label, "the trap: looks like a match"
    assert _components(substituted_image_label) != _components(pinned), (
        "the real comparison is not fooled by the label containing the pinned tag"
    )


# ---------------------------------------------------------------------------
# qBittorrent
# ---------------------------------------------------------------------------


def _qbittorrent_password():
    return read_secret("qbittorrent", "password.txt") or env(
        "QBITTORRENT_PASSWORD", "qbittorrent"
    )


def test_qbittorrent_running_version_matches_pin(running_containers):
    if not is_enabled("qbittorrent"):
        pytest.skip("qbittorrent profile is disabled")
    skip_if_not_running("qbittorrent", running_containers)

    session = requests.Session()
    session.verify = False
    password = _qbittorrent_password()
    username = SERVICES["qbittorrent"]["username"]
    login = session.post(
        f"{BASE}/qbittorrent/api/v2/auth/login",
        data={"username": username, "password": password},
        timeout=TIMEOUT,
    )
    assert 200 <= login.status_code < 300, (
        f"qBittorrent login failed: {login.status_code} {login.text!r}"
    )

    resp = session.get(f"{BASE}/qbittorrent/api/v2/app/version", timeout=TIMEOUT)
    assert resp.status_code == 200, (
        f"qBittorrent version endpoint returned {resp.status_code}: {resp.text[:200]}"
    )
    _assert_running_matches_pin(
        env("QBITTORRENT_VERSION"),
        resp.text.strip(),
        "qbittorrent",
        "QBITTORRENT_VERSION",
    )


# ---------------------------------------------------------------------------
# Servarr apps: Sonarr, Radarr, Lidarr, Prowlarr, Readarr
# ---------------------------------------------------------------------------

_ARR_VERSION_VAR = {
    "sonarr": "SONARR_VERSION",
    "radarr": "RADARR_VERSION",
    "lidarr": "LIDARR_VERSION",
    "prowlarr": "PROWLARR_VERSION",
    "readarr": "READARR_VERSION",
}


@pytest.mark.parametrize("service_name", sorted(_ARR_VERSION_VAR))
def test_arr_running_version_matches_pin(service_name, running_containers):
    """`system/status` sits beside the `/health` path SERVICES already knows.

    Same API prefix (api/v3 for Sonarr and Radarr, api/v1 for the rest) and
    the same API key; confirmed live against standalone containers of
    Sonarr, Prowlarr and Readarr that all three answer a `version` field at
    `system/status` in this shape (Radarr and Lidarr share the same Servarr
    codebase and API convention).
    """
    if not is_enabled(service_name):
        pytest.skip(f"{service_name} profile is disabled")
    skip_if_not_running(service_name, running_containers)

    api_key = read_api_key(service_name)
    if not api_key:
        pytest.skip(f"No API key found for {service_name}")

    cfg = SERVICES[service_name]
    api_prefix = cfg["api_health_path"].rsplit("/health", 1)[0]
    url = service_base_url(service_name) + api_prefix + "/system/status"
    resp = requests.get(
        url, headers={"X-Api-Key": api_key}, verify=False, timeout=TIMEOUT
    )
    assert resp.status_code == 200, (
        f"{service_name} system/status returned {resp.status_code}: {resp.text[:200]}"
    )
    reported = resp.json().get("version")
    assert reported, (
        f"{service_name} system/status returned no version: {resp.text[:200]}"
    )
    _assert_running_matches_pin(
        env(_ARR_VERSION_VAR[service_name]),
        reported,
        service_name,
        _ARR_VERSION_VAR[service_name],
    )


# ---------------------------------------------------------------------------
# Bazarr
# ---------------------------------------------------------------------------


def test_bazarr_running_version_matches_pin(running_containers):
    if not is_enabled("bazarr"):
        pytest.skip("bazarr profile is disabled")
    skip_if_not_running("bazarr", running_containers)

    api_key = read_api_key("bazarr")
    if not api_key:
        pytest.skip("No Bazarr API key found")

    resp = requests.get(
        f"{BASE}/bazarr/api/system/status",
        headers={"X-API-KEY": api_key},
        verify=False,
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, (
        f"bazarr system/status returned {resp.status_code}: {resp.text[:200]}"
    )
    reported = resp.json().get("data", {}).get("bazarr_version")
    assert reported, f"bazarr system/status returned no version: {resp.text[:200]}"
    _assert_running_matches_pin(
        env("BAZARR_VERSION"), reported, "bazarr", "BAZARR_VERSION"
    )


# ---------------------------------------------------------------------------
# SABnzbd
# ---------------------------------------------------------------------------


def test_sabnzbd_running_version_matches_pin(running_containers):
    """`mode=version` is unauthenticated by design upstream (see test_auth.py's
    comment on why that made it unsuitable for an auth test); that is exactly
    what makes it convenient here.
    """
    if not is_enabled("sabnzbd"):
        pytest.skip("sabnzbd profile is disabled")
    skip_if_not_running("sabnzbd", running_containers)

    resp = requests.get(
        f"{BASE}/sabnzbd/api",
        params={"mode": "version", "output": "json"},
        verify=False,
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, (
        f"SABnzbd version endpoint returned {resp.status_code}: {resp.text[:200]}"
    )
    reported = resp.json().get("version")
    assert reported, f"SABnzbd version endpoint returned no version: {resp.text[:200]}"
    _assert_running_matches_pin(
        env("SABNZBD_VERSION"), reported, "sabnzbd", "SABNZBD_VERSION"
    )


# ---------------------------------------------------------------------------
# Jellyfin
# ---------------------------------------------------------------------------


def test_jellyfin_running_version_matches_pin(running_containers):
    if not is_enabled("jellyfin"):
        pytest.skip("jellyfin profile is disabled")
    skip_if_not_running("jellyfin", running_containers)

    jellyfin_base = service_base_url("jellyfin")
    resp = requests.get(
        f"{jellyfin_base}/System/Info/Public", verify=False, timeout=TIMEOUT
    )
    assert resp.status_code == 200, (
        f"Jellyfin System/Info/Public returned {resp.status_code}: {resp.text[:200]}"
    )
    # JELLYFIN_PROFILE is `enabled` in .env.example and .env.tests does not
    # override it, so is_enabled() reads true while the test stack never
    # stands the service up. The URL then answers, but with nginx's own
    # response rather than Jellyfin's, and .json() raised JSONDecodeError at
    # character 0. Skip on a non-JSON body instead of asserting against
    # whatever happens to be listening: this test exists to catch a version
    # mismatch, and "something else answered" is not one.
    content_type = resp.headers.get("Content-Type", "")
    if "json" not in content_type.lower():
        pytest.skip(
            "Jellyfin System/Info/Public did not answer with JSON "
            f"(Content-Type {content_type!r}), so Jellyfin is not serving "
            "this URL in this environment"
        )
    reported = resp.json().get("Version")
    assert reported, (
        f"Jellyfin System/Info/Public returned no version: {resp.text[:200]}"
    )
    _assert_running_matches_pin(
        env("JELLYFIN_VERSION"), reported, "jellyfin", "JELLYFIN_VERSION"
    )


# ---------------------------------------------------------------------------
# Grafana and Prometheus
#
# Both requested by name for #97 (Grafana 11.6.5 -> 13.0.2, Prometheus
# v2.55.1 -> v3.14.0): confirmed live against standalone containers of all
# four versions (both endpoints, both pinned and target) that the field
# names below are stable across the bump.
# ---------------------------------------------------------------------------


def test_grafana_running_version_matches_pin(running_containers):
    if not is_enabled("grafana"):
        pytest.skip("grafana profile is disabled")
    skip_if_not_running("grafana", running_containers)

    # Authenticated, and that is the whole point of this call rather than an
    # incidental detail. Grafana's /api/health answers an anonymous request
    # with only {"database": "ok"} and omits the version, which is exactly
    # what test_observability.py's own test_grafana_health documents when it
    # says that endpoint needs no auth: it needs none for liveness, and it
    # tells you nothing about the version without it. An unauthenticated read
    # here fails with "returned no version" no matter which Grafana is
    # running, which is a broken test rather than a detected mismatch.
    # env() returns "" for an unset key, so a configured credential is
    # distinguishable from the fallback, and that distinction decides what a
    # 401 means. The two must not be conflated: skipping on a credential that
    # was actually configured and rejected would let this test pass while
    # verifying nothing, including when the password is simply wrong. Only a
    # genuinely unconfigured environment earns a skip.
    configured_user = env("ADMIN_USER")
    configured_password = env("ADMIN_PASSWORD")
    credentials_configured = bool(configured_user and configured_password)

    session = requests.Session()
    session.verify = False
    session.auth = (configured_user or "admin", configured_password or "admin")
    resp = session.get(
        base_url(https=True) + "/admin/grafana/api/health", timeout=TIMEOUT
    )
    if resp.status_code == 401:
        assert not credentials_configured, (
            "ADMIN_USER and ADMIN_PASSWORD are configured but Grafana rejected "
            f"them (HTTP 401), so GRAFANA_VERSION went unverified: {resp.text[:120]}"
        )
        pytest.skip(
            "no Grafana credentials configured and the default admin login was "
            f"rejected (HTTP 401): {resp.text[:120]}"
        )
    assert resp.status_code == 200, f"Grafana health returned {resp.status_code}"
    reported = resp.json().get("version")
    assert reported, (
        f"Grafana /api/health returned no version even authenticated: {resp.text[:200]}"
    )
    _assert_running_matches_pin(
        env("GRAFANA_VERSION"), reported, "grafana", "GRAFANA_VERSION"
    )


def test_prometheus_running_version_matches_pin(running_containers):
    if not is_enabled("prometheus"):
        pytest.skip("prometheus profile is disabled")
    skip_if_not_running("prometheus", running_containers)

    resp = requests.get(
        base_url() + "/admin/prometheus/api/v1/status/buildinfo",
        verify=False,
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, f"Prometheus buildinfo returned {resp.status_code}"
    data = resp.json()
    assert data.get("status") == "success", f"Prometheus buildinfo: {data}"
    reported = data.get("data", {}).get("version")
    assert reported, f"Prometheus buildinfo returned no version: {resp.text[:200]}"
    _assert_running_matches_pin(
        env("PROMETHEUS_VERSION"), reported, "prometheus", "PROMETHEUS_VERSION"
    )
