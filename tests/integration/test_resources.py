"""Brief test (b): limits actually cap, verified in the cgroup and by effect."""
import pytest

from conftest import runner_name_for, sh

pytestmark = pytest.mark.integration

# Ticket 16: this was a zero-margin timing race. The client's own httpx
# timeout used to equal the server-side `wait` exactly, so ANY overhead -
# network, the orchestrator's proxy hop, GC, a loaded host - made the
# client give up a moment before the server would have answered: a false
# failure, not a real one (confirmed: passed cleanly on every retry). The
# margin gives the client real slack without changing what the test
# proves (the runner is OOM-killed inside its cgroup, not the host).
WAIT_SECONDS = 60
TIMEOUT_MARGIN_SECONDS = 30


@pytest.fixture
def runner(api, stack, uid, cleanup_runners):
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    return uid


def _cgroup(uid, filename):
    return sh("docker", "exec", runner_name_for(uid), "sh", "-c",
              f"cat /sys/fs/cgroup/{filename} 2>/dev/null || echo MISSING",
              check=False)


def test_memory_limit_reaches_the_cgroup(runner):
    val = _cgroup(runner, "memory.max")
    if val == "MISSING":
        pytest.skip("cgroup v2 memory.max not exposed")
    assert int(val) == 320 * 1024**2


def test_pids_limit_reaches_the_cgroup(runner):
    val = _cgroup(runner, "pids.max")
    if val == "MISSING":
        pytest.skip("cgroup v2 pids.max not exposed")
    assert int(val) == 256


def test_cpu_quota_reaches_the_cgroup(runner):
    val = _cgroup(runner, "cpu.max")
    if val == "MISSING":
        pytest.skip("cgroup v2 cpu.max not exposed")
    quota, period = val.split()
    assert quota != "max", "no CPU ceiling is applied"
    assert abs((int(quota) / int(period)) - 0.5) < 0.05


def test_over_allocating_memory_is_killed_not_swapped_onto_the_host(
        api, stack, runner):
    """The point of the limit is that the HOST survives. An over-allocating
    agent must die inside its own cgroup."""
    r = api.post("/execute", headers=stack.user_headers(runner), json={
        "command": "python3 -c \"b=bytearray(600*1024*1024); print(len(b))\"",
        "wait": WAIT_SECONDS}, timeout=WAIT_SECONDS + TIMEOUT_MARGIN_SECONDS)
    body = r.json()
    assert body.get("exit_code") not in (0, None), (
        f"600 MiB allocation succeeded inside a 320 MiB runner: {body}")


def test_host_is_not_starved_with_the_budget_full(api, stack, cleanup_runners):
    """An in-container stress test proves nothing about the host. This asserts
    the host still has memory headroom with every slot occupied."""
    uids = [f"u-load{i}" for i in range(3)]
    cleanup_runners.extend(uids)
    for u in uids:
        assert api.get("/system", headers=stack.user_headers(u)).status_code == 200
    status = api.get("/_orch/status", headers=stack.orch_headers()).json()
    assert status["runners_live"] <= status["max_containers"]
    avail = status["host_memory_available_mb"]
    if avail is not None:
        assert avail > 100, f"host down to {avail} MiB with the budget full"
