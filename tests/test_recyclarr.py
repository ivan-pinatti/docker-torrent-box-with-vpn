"""Recyclarr sync integration test: exec into the container and run a full sync."""

import pytest

from conftest import is_enabled, skip_if_not_running

pytestmark = pytest.mark.recyclarr

TIMEOUT = 120  # recyclarr clones TRaSH-Guides; allow time for the network round-trip


def test_recyclarr_sync(docker_client, running_containers):
    """recyclarr sync must exit 0 and not report any errors."""
    if not is_enabled("recyclarr"):
        pytest.skip("recyclarr profile is disabled")
    skip_if_not_running("recyclarr", running_containers)

    container = docker_client.containers.get("recyclarr")
    exit_code, output = container.exec_run(
        ["recyclarr", "sync"],
        stdout=True,
        stderr=True,
        demux=False,
    )
    decoded = output.decode("utf-8", errors="replace") if output else ""

    assert exit_code == 0, f"recyclarr sync failed (exit {exit_code}):\n{decoded}"
