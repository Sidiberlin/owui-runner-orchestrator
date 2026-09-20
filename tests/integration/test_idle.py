"""C7: idle means no request AND no running work.

The briefed rule was a timestamp comparison alone, which would kill a runner
mid-build: POST /execute is fire-and-forget, so a user who kicks off a long
compile and closes the chat tab looks idle by request time. Getting this wrong
destroys real work and the user sees only a truncated job.
"""
import threading
import time

import pytest

from conftest import container_exists, inspect, runner_name_for

pytestmark = [pytest.mark.integration, pytest.mark.slow]

# env.test: IDLE_TIMEOUT=60s, IDLE_SWEEP_INTERVAL=5s
IDLE_TIMEOUT = 60
SWEEP = 5
SETTLE = IDLE_TIMEOUT + SWEEP * 3

# env.test: POLICY_HEAVY_IDLE_TIMEOUT=15s -- a profile-specific timeout much
# shorter than the global above, chosen so ticket 07's per-runner comparison
# can be proven within one settle window rather than the full global one.
HEAVY_IDLE_TIMEOUT = 15
HEAVY_SETTLE = HEAVY_IDLE_TIMEOUT + SWEEP * 3


def _gone_within(name: str, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not container_exists(name):
            return True
        time.sleep(2)
    return not container_exists(name)


def test_idle_runner_is_reclaimed(api, stack, uid, cleanup_runners):
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    assert container_exists(runner_name_for(uid))
    assert _gone_within(runner_name_for(uid), SETTLE), "idle runner was not reclaimed"


def test_runner_with_running_work_is_never_reclaimed(api, stack, uid, cleanup_runners):
    """The one that matters. This runner is idle by request time for well past
    IDLE_TIMEOUT, but it has a live process and must survive."""
    cleanup_runners.append(uid)
    h = stack.user_headers(uid)
    assert api.get("/system", headers=h).status_code == 200

    # POST /execute is synchronous (the `wait` parameter does not cap it), so a
    # long-running command must be left in flight — which is precisely the
    # scenario the idle rule exists to protect: a user kicks off a long build
    # and the tool call is still open.
    def _fire():
        try:
            with stack.client(timeout=SETTLE + 200) as c:
                c.post("/execute", headers=h,
                       json={"command": f"sleep {SETTLE + 90}"})
        except Exception:
            pass
    threading.Thread(target=_fire, daemon=True).start()
    time.sleep(5)

    time.sleep(SETTLE)
    assert container_exists(runner_name_for(uid)), (
        "a runner with a live process was torn down: this destroys a user's "
        "in-flight build"
    )
    # And once the work ends, it becomes reclaimable again.
    with stack.client() as c:
        procs = c.get("/execute", headers=h).json()
        if isinstance(procs, dict):
            procs = procs.get("processes") or procs.get("items") or []
        for p in procs:
            if isinstance(p, dict) and p.get("status") == "running":
                c.delete(f"/execute/{p['id']}", headers=h)
    assert _gone_within(runner_name_for(uid), SETTLE + 40), (
        "runner stayed alive after its work ended"
    )


def test_teardown_reason_is_recorded(api, stack, uid, cleanup_runners):
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    assert _gone_within(runner_name_for(uid), SETTLE)
    # Respawning surfaces why the previous one went away (C7).
    api.get("/system", headers=stack.user_headers(uid))
    rows = api.get("/_orch/runners", headers=stack.orch_headers()).json()
    row = next(x for x in rows if x["uid"] == uid)
    assert row["replaced_reason"] and "idle" in row["replaced_reason"].lower()


# ---------------------------------------------------------------------------
# Ticket 07 (v2.0 group policy profiles, docs/adr/0012): the sweeper compares
# each runner against the idle timeout it was created under, not one global
# value. env.test maps GROUP_MAP=ops:heavy (POLICY_HEAVY_IDLE_TIMEOUT=15s) to
# a group only a uid containing "opsgroup" ever carries -- see
# test_lifecycle.py's own ticket-05 section for why this cannot perturb any
# other test, including every test above in this same file (all use the
# plain `uid` fixture, which resolves to the default/global 60s).
# ---------------------------------------------------------------------------
def test_a_shorter_profile_timeout_reclaims_while_the_default_survives(
        api, stack, cleanup_runners):
    """Demoable exactly as the ticket describes: two runners on different
    timeouts, the shorter one reclaimed, the longer one still up at the same
    point in time (HEAVY_SETTLE=30s is well short of the default's 60s)."""
    default_uid = "u-plain-idle-check"
    heavy_uid = "u-opsgroup-idle"
    cleanup_runners.extend([default_uid, heavy_uid])
    assert api.get("/system", headers=stack.user_headers(default_uid)).status_code == 200
    assert api.get("/system", headers=stack.user_headers(heavy_uid)).status_code == 200

    assert _gone_within(runner_name_for(heavy_uid), HEAVY_SETTLE), \
        "the shorter-timeout profile's runner was not reclaimed"
    assert container_exists(runner_name_for(default_uid)), \
        "a runner on the longer default timeout was reclaimed early"


def test_a_mapped_profiles_idle_timeout_survives_restart_and_adoption(
        api, stack, cleanup_runners):
    """Mirrors the ticket-05 profile-label restart test, but proves the
    NUMERIC idle timeout specifically: if reconciliation lost it and fell
    back to the 60s global, this runner would still be alive at
    HEAVY_SETTLE."""
    heavy_uid = "u-opsgroup-idle-restart"
    cleanup_runners.append(heavy_uid)
    assert api.get("/system", headers=stack.user_headers(heavy_uid)).status_code == 200
    name = runner_name_for(heavy_uid)
    before = inspect(name, "{{.Id}}")

    stack.restart_orchestrator()

    assert inspect(name, "{{.Id}}") == before, "runner was respawned"
    assert _gone_within(name, HEAVY_SETTLE), \
        "reconciliation did not restore the profile's own idle timeout"
