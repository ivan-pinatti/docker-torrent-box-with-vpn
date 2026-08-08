"""Homepage widget integration checks.

Homepage resolves HOMEPAGE_VAR_* credentials from its env files only at
container creation, which makes it the canary for stale secrets: if a
credential was rotated without recreating the container, its widget breaks.
Each probe goes through homepage's own /api/services/proxy, exercising the
full chain the dashboard uses (env resolution, credential, upstream API).

The rotation tests reuse the same helpers after each rotation and restore, so
a rotation that leaves Homepage broken fails the suite.
"""

import time

import pytest

from conftest import (
    homepage_widget_failures,
    skip_if_not_running,
    wait_for_homepage_ready,
)

pytestmark = pytest.mark.services


def test_homepage_widget_integrations(running_containers):
    """Every configured homepage widget proxy returns data with its stored credential."""
    skip_if_not_running("homepage", running_containers)
    assert wait_for_homepage_ready(), "homepage API did not respond"

    # Homepage itself responding is not proof every upstream app it proxies
    # to has also finished settling after bootstrap's own credential
    # rotation restarts; confirmed live, several apps still 401 a few
    # seconds after their own container reports healthy on a slower
    # runner. Retry before treating this as a real integration break.
    failures = homepage_widget_failures()
    attempts = 1
    while failures and attempts < 4:
        time.sleep(10)
        failures = homepage_widget_failures()
        attempts += 1
    assert not failures, "Homepage widget integrations broken:\n" + "\n".join(failures)
