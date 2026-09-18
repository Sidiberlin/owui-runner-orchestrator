"""A8: the role cache fails CLOSED.

A role we cannot verify is not a role. The failure that matters is the quiet
one: falling open to "probably a user" would let a deleted or demoted account
keep driving a runner indefinitely while OWUI is down.
"""
import time

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]

# env.test: ROLE_CACHE_TTL=5, ROLE_CACHE_GRACE=30
TTL = 5
GRACE = 30


def _warm(api, stack, uid):
    """Spawn the runner and then take a FRESH cache entry.

    Spawning takes ~11s, which would otherwise be charged against the grace
    window and make these assertions race the clock. The runner must already
    exist before the cache timing starts mattering.
    """
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    time.sleep(TTL + 1)          # force the next call to re-resolve
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200


@pytest.fixture
def owui_restored(stack):
    yield
    stack.start_owui()
    time.sleep(2)


def test_cached_role_survives_a_brief_owui_outage(
        api, stack, uid, cleanup_runners, owui_restored):
    cleanup_runners.append(uid)
    _warm(api, stack, uid)

    stack.stop_owui()
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200, \
        "fresh cache should still serve"

    time.sleep(TTL + 3)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200, \
        "stale-but-within-grace should still serve"


def test_access_is_refused_once_the_grace_window_expires(
        api, stack, uid, cleanup_runners, owui_restored):
    cleanup_runners.append(uid)
    _warm(api, stack, uid)
    stack.stop_owui()
    time.sleep(GRACE + TTL + 5)
    r = api.get("/system", headers=stack.user_headers(uid))
    assert r.status_code == 503, f"expected fail-closed 503, got {r.status_code}"


def test_an_unknown_user_never_gets_in_during_an_outage(api, stack, owui_restored):
    """No cache entry exists, so there is nothing to fall back on. The only
    safe answer is refusal — never a hopeful 200."""
    unseen = "u-never-seen-before"
    stack.stop_owui()
    r = api.get("/system", headers=stack.user_headers(unseen))
    assert r.status_code == 503
    assert r.status_code != 200


def test_recovery_is_automatic(api, stack, uid, cleanup_runners, owui_restored):
    cleanup_runners.append(uid)
    api.get("/system", headers=stack.user_headers(uid))
    stack.stop_owui()
    time.sleep(GRACE + TTL + 5)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 503
    stack.start_owui()
    time.sleep(3)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
