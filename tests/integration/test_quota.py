"""N4 workspace accounting.

This is detection, not prevention: the host has no loop devices and no project
quotas, so there is no kernel-level cap. These tests assert the accounting
works and survives a restart, which is what the aggregate ceiling depends on.
"""
import time

import pytest

from conftest import purge_runners

pytestmark = pytest.mark.integration


def test_workspace_usage_is_measured(api, stack, uid, cleanup_runners):
    purge_runners()
    cleanup_runners.append(uid)
    h = stack.user_headers(uid)
    assert api.get("/system", headers=h).status_code == 200
    api.post("/execute", headers=h, json={
        "command": "head -c 5000000 /dev/urandom > filler.bin", "wait": 30})

    deadline = time.time() + 60
    measured = 0
    while time.time() < deadline:
        rows = api.get("/_orch/runners", headers=stack.orch_headers()).json()
        row = next((x for x in rows if x["uid"] == uid), None)
        if row and row["workspace_mb"] >= 4:
            measured = row["workspace_mb"]
            break
        time.sleep(3)
    assert measured >= 4, f"usage never reflected the 5 MB file (saw {measured} MB)"


def test_usage_cache_survives_an_orchestrator_restart(
        api, stack, uid, cleanup_runners):
    purge_runners()
    """Without this the aggregate ceiling silently resets to zero on every
    restart — the N14 bind-mount bug, which was invisible in normal use."""
    cleanup_runners.append(uid)
    h = stack.user_headers(uid)
    api.get("/system", headers=h)
    api.post("/execute", headers=h, json={
        "command": "head -c 5000000 /dev/urandom > filler.bin", "wait": 30})
    time.sleep(20)

    before = api.get("/_orch/status", headers=stack.orch_headers()).json()
    stack.restart_orchestrator()
    after = api.get("/_orch/status", headers=stack.orch_headers()).json()

    assert after["workspace_total_known_mb"] >= before["workspace_total_known_mb"], \
        "usage cache was lost on restart"


def test_status_reports_the_budget(api, stack):
    s = api.get("/_orch/status", headers=stack.orch_headers()).json()
    assert s["max_containers"] == 3
    assert s["runner_memory_mb"] == 320
    assert set(s["deny_prefixes"]) == {"/proxy", "/ports", "/api/terminals"}
