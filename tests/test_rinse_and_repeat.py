"""Rinse and Repeat: lifecycle stability test.

Exercises stop→start and down→start cycles to detect stateful bugs such as network
recreation regressions under rootless Podman. Each cycle is repeated twice and
container state is verified after every start.
"""

import subprocess
import time
from pathlib import Path

import pytest

from conftest import SERVICES, is_enabled

pytestmark = pytest.mark.rinse_and_repeat

REPO_ROOT = Path(__file__).parent.parent
# seconds; make start waits up to 120s for gluetun alone. 300 wasn't enough
# for the first stop-then-start cycle specifically against the full
# `make bootstrap_tests` stack (~35 containers instead of the ~19 default):
# confirmed live, that one `make start` call alone hit a 300s
# subprocess.TimeoutExpired while every other cycle immediately after it,
# same stack, finished in under half that. Looks like first-restart-after-
# bootstrap settling (matching other apps' documented slower first restart
# elsewhere in this stack), not a real hang.
MAKE_TIMEOUT = 600
SETTLE_DELAY = 10  # seconds to let containers settle before health checks


def _run_make(target: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["make", target],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=MAKE_TIMEOUT,
    )


def _assert_all_enabled_running(docker_client):
    containers = {c.name: c for c in docker_client.containers.list()}
    failures = []
    for name in SERVICES:
        if not is_enabled(name):
            continue
        c = containers.get(name)
        if c is None:
            failures.append(f"  {name}: not found (not running)")
            continue
        if c.status != "running":
            failures.append(f"  {name}: status={c.status!r}")
    assert not failures, "Containers not running after start:\n" + "\n".join(failures)


@pytest.mark.parametrize("cycle", [1, 2])
def test_stop_then_start(cycle, docker_client):
    """stop → start must bring all enabled containers back up (no container removal)."""
    result = _run_make("stop")
    assert result.returncode == 0, (
        f"make stop failed (cycle {cycle}):\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    result = _run_make("start")
    assert result.returncode == 0, (
        f"make start failed after stop (cycle {cycle}):\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    time.sleep(SETTLE_DELAY)
    _assert_all_enabled_running(docker_client)


@pytest.mark.parametrize("cycle", [1, 2])
def test_down_then_start(cycle, docker_client):
    """down → start must recreate networks and bring all enabled containers back up."""
    result = _run_make("down")
    assert result.returncode == 0, (
        f"make down failed (cycle {cycle}):\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    result = _run_make("start")
    assert result.returncode == 0, (
        f"make start failed after down (cycle {cycle}):\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    time.sleep(SETTLE_DELAY)
    _assert_all_enabled_running(docker_client)
