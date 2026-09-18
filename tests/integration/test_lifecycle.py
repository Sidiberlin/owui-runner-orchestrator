"""Spawn, adopt, race, budget, teardown (Lane B)."""
import concurrent.futures as cf

import pytest

from conftest import (container_exists, inspect, purge_runners, runner_name_for,
                      sh)

pytestmark = pytest.mark.integration


def test_first_request_lazily_spawns_a_runner(api, stack, uid, cleanup_runners):
    cleanup_runners.append(uid)
    assert not container_exists(runner_name_for(uid))
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    assert container_exists(runner_name_for(uid))


def test_runner_is_created_with_the_configured_limits(api, stack, uid, cleanup_runners):
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    n = runner_name_for(uid)
    assert inspect(n, "{{.HostConfig.Memory}}") == str(320 * 1024**2)
    assert inspect(n, "{{.HostConfig.PidsLimit}}") == "256"
    assert inspect(n, "{{.HostConfig.RestartPolicy.Name}}") == "no"
    assert inspect(n, "{{.HostConfig.CapDrop}}") == "[ALL]"
    caps = inspect(n, "{{.HostConfig.CapAdd}}")
    for c in ("CHOWN", "SETUID", "SETGID"):
        assert c in caps, f"{c} missing: the entrypoint cannot chown or drop privs"
    assert "no-new-privileges" in inspect(n, "{{.HostConfig.SecurityOpt}}")


def test_admin_role_gets_its_own_resource_profile(api, stack, admin_uid, cleanup_runners):
    cleanup_runners.append(admin_uid)
    assert api.get("/system", headers=stack.user_headers(admin_uid)).status_code == 200
    assert inspect(runner_name_for(admin_uid),
                   "{{.HostConfig.Memory}}") == str(384 * 1024**2)


def test_concurrent_first_requests_create_exactly_one_runner(
        stack, uid, cleanup_runners):
    """A5. OWUI can fire parallel tool calls; two containers mounting one
    volume is corruption, and it silently overruns the container budget."""
    cleanup_runners.append(uid)

    def hit():
        with stack.client() as c:
            return c.get("/system", headers=stack.user_headers(uid)).status_code

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        codes = [f.result() for f in [ex.submit(hit) for _ in range(8)]]

    assert all(c == 200 for c in codes), codes
    ids = sh("docker", "ps", "-aq", "-f",
             f"label=io.owui.runner.uid={uid}", check=False).split()
    assert len(ids) == 1, f"spawn race produced {len(ids)} containers"
    vols = sh("docker", "volume", "ls", "-q", "-f",
              f"label=io.owui.runner.uid={uid}", check=False).split()
    assert len(vols) == 1


def test_orchestrator_restart_adopts_runners_and_re_derives_keys(
        api, stack, uid, cleanup_runners):
    """A4 x N1 together. Adoption is worthless if the key cannot be recovered,
    and the key is never stored — only the nonce label is."""
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    before = inspect(runner_name_for(uid), "{{.Id}}")

    stack.restart_orchestrator()

    assert inspect(runner_name_for(uid), "{{.Id}}") == before, "runner was respawned"
    r = api.get("/_orch/runners", headers=stack.orch_headers())
    assert any(x["uid"] == uid for x in r.json()), "runner was not adopted"
    # The adopted runner must still be drivable, which proves the re-derivation.
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    ids = sh("docker", "ps", "-aq", "-f",
             f"label=io.owui.runner.uid={uid}", check=False).split()
    assert len(ids) == 1, "restart created a duplicate"


def test_budget_exhaustion_returns_a_relayable_429(api, stack, cleanup_runners):
    """R3. The agent has to explain this to a human, so it must not be a
    stack trace."""
    purge_runners()
    uids = [f"u-budget{i}" for i in range(4)]
    cleanup_runners.extend(uids)
    codes = [api.get("/system", headers=stack.user_headers(u)).status_code
             for u in uids]
    assert codes[:3] == [200, 200, 200], codes
    assert codes[3] == 429, codes
    body = api.get("/system", headers=stack.user_headers(uids[3])).text.lower()
    assert "slot" in body or "idle" in body
    assert "traceback" not in body


def test_teardown_removes_the_container_but_keeps_the_volume(
        api, stack, uid, cleanup_runners):
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    api.delete(f"/_orch/runners/{uid}", headers=stack.orch_headers())
    assert not container_exists(runner_name_for(uid))
    vols = sh("docker", "volume", "ls", "-q", "-f",
              f"label=io.owui.runner.uid={uid}", check=False).split()
    assert len(vols) == 1, "the user's workspace was destroyed with the container"


def test_a_container_lost_out_of_band_frees_its_budget_slot(
        api, stack, cleanup_runners):
    """Regression for the phantom-slot bug this suite found.

    A runner can die without the orchestrator being asked: an OOM kill, a
    crash, an operator `docker rm`. If its slot is not reclaimed, MAX_CONTAINERS
    silently shrinks and users are refused while no containers exist.

    The assertion is about RECOVERY, not about the budget being full first —
    whether three runners all stay up for the duration depends on host load,
    and `test_budget_exhaustion_returns_a_relayable_429` already covers refusal.
    """
    purge_runners()
    uids = [f"u-phantom{i}" for i in range(3)]
    cleanup_runners.extend(uids)
    for u in uids:
        assert api.get("/system", headers=stack.user_headers(u)).status_code == 200

    status = api.get("/_orch/status", headers=stack.orch_headers()).json()
    if status["runners_live"] < 3:
        pytest.skip("host could not hold a full budget; nothing to reclaim")

    # Kill one behind the orchestrator's back.
    sh("docker", "rm", "-f", runner_name_for(uids[0]), check=False)

    extra = "u-phantom-extra"
    cleanup_runners.append(extra)
    assert api.get("/system", headers=stack.user_headers(extra)).status_code == 200, \
        "the dead runner's slot was never reclaimed"

    rows = api.get("/_orch/runners", headers=stack.orch_headers()).json()
    assert uids[0] not in [r["uid"] for r in rows], \
        "the orchestrator still counts a container that no longer exists"
