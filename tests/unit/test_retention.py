"""R2: workspace retention sweep and the aggregate ceiling.

The sweep deletes user data, so every guard gets an explicit test. A bug here
is not a 500 — it is someone's work gone.
"""
import asyncio
import time
import types

import pytest

from app import workers
from app.quota import MonitorQuota, QuotaExceeded

DAY = 86400.0


def _quota(tmp_path, **kw):
    return MonitorQuota(str(tmp_path), kw.get("soft", 0), kw.get("hard", 0),
                        kw.get("ceiling", 0))


def _mgr(tmp_path, *, vols, live=(), days=30.0, network="net-a"):
    q = _quota(tmp_path)
    cfg = types.SimpleNamespace(retention_days=days, runners_network=network,
                                retention_sweep_interval=1)

    async def _list(client, net=""):
        return [v for v in vols if not net or (v.get("Labels") or {}).get(
            "io.owui.runner.network") == net]

    removed = []

    async def _remove(client, name):
        removed.append(name)

    workers_v = types.SimpleNamespace(
        list_workspace_volumes=_list, remove_volume=_remove,
        volume_uid=lambda v: (v.get("Labels") or {}).get("io.owui.runner.uid"))
    m = types.SimpleNamespace(cfg=cfg, quota=q, client=None,
                              get=lambda uid: object() if uid in live else None)
    m._removed = removed
    m._volmod = workers_v
    return m


def _run(mgr, **kw):
    import sys
    sys.modules['app.volumes_stub'] = mgr._volmod
    real = workers.retention_sweep.__globals__
    # retention_sweep imports `volumes` lazily inside the function
    import app.volumes as realv
    saved = (realv.list_workspace_volumes, realv.remove_volume, realv.volume_uid)
    realv.list_workspace_volumes = mgr._volmod.list_workspace_volumes
    realv.remove_volume = mgr._volmod.remove_volume
    realv.volume_uid = mgr._volmod.volume_uid
    try:
        return asyncio.run(workers.retention_sweep(mgr, **kw))
    finally:
        (realv.list_workspace_volumes, realv.remove_volume,
         realv.volume_uid) = saved


def _vol(uid, network="net-a"):
    return {"Name": f"runner-ws-{uid}",
            "Labels": {"io.owui.runner.uid": uid,
                       "io.owui.runner.network": network}}


def test_disabled_policy_deletes_nothing(tmp_path):
    """days=0 is the default. Nothing is deleted, however stale the record."""
    m = _mgr(tmp_path, vols=[_vol("u1")], days=0)
    m.quota.note_activity("u1")
    m.quota._samples["u1"].seen = time.time() - 9999 * DAY
    assert _run(m) == []
    assert m._removed == []


def test_unknown_uid_is_never_deleted_on_first_sight(tmp_path):
    """A fresh orchestrator must not delete workspaces it has never seen."""
    m = _mgr(tmp_path, vols=[_vol("u1")], days=1)
    assert _run(m) == []
    assert m._removed == []
    assert m.quota.last_activity("u1") > 0, "its clock should now be started"


def test_inactive_beyond_policy_is_deleted(tmp_path):
    m = _mgr(tmp_path, vols=[_vol("u1")], days=30)
    m.quota.note_activity("u1")
    m.quota._samples["u1"].seen = time.time() - 31 * DAY
    out = _run(m)
    assert [e["uid"] for e in out] == ["u1"]
    assert m._removed == ["runner-ws-u1"]


def test_recent_activity_is_kept(tmp_path):
    m = _mgr(tmp_path, vols=[_vol("u1")], days=30)
    m.quota.note_activity("u1")
    m.quota._samples["u1"].seen = time.time() - 29 * DAY
    assert _run(m) == []
    assert m._removed == []


def test_live_runner_volume_is_never_deleted(tmp_path):
    """Guard 2: in use right now, however stale the activity record looks."""
    m = _mgr(tmp_path, vols=[_vol("u1")], days=1, live={"u1"})
    m.quota.note_activity("u1")
    m.quota._samples["u1"].seen = time.time() - 999 * DAY
    assert _run(m) == []
    assert m._removed == []


def test_another_orchestrators_volumes_are_invisible(tmp_path):
    """Guard 1 — the N27 lesson applied to data instead of containers."""
    m = _mgr(tmp_path, vols=[_vol("theirs", network="net-b")], days=1)
    m.quota.note_activity("theirs")
    m.quota._samples["theirs"].seen = time.time() - 99 * DAY
    assert _run(m) == []
    assert m._removed == []


def test_dry_run_reports_without_deleting(tmp_path):
    m = _mgr(tmp_path, vols=[_vol("u1")], days=30)
    m.quota.note_activity("u1")
    m.quota._samples["u1"].seen = time.time() - 40 * DAY
    out = _run(m, dry_run=True)
    assert [e["uid"] for e in out] == ["u1"]
    assert m._removed == [], "dry run must not delete"


# --- activity tracking -----------------------------------------------------
def test_activity_survives_a_restart(tmp_path):
    q = _quota(tmp_path)
    q.note_activity("u1")
    q.record("u1", 4096)
    q.flush()
    again = _quota(tmp_path)
    assert again.last_activity("u1") > 0
    assert again.last_known("u1") == 4096


def test_measuring_does_not_reset_activity(tmp_path):
    """`at` is when we measured; `seen` is when the user was active. Conflating
    them would keep dead workspaces alive forever, since the quota worker
    measures constantly."""
    q = _quota(tmp_path)
    q.note_activity("u1")
    old = q.last_activity("u1")
    time.sleep(0.01)
    q.record("u1", 123)
    assert q.last_activity("u1") == old


def test_legacy_state_without_seen_still_loads(tmp_path):
    (tmp_path / "usage.json").write_text('{"u1": {"bytes_used": 10, "at": 1.0}}')
    q = _quota(tmp_path)
    assert q.last_known("u1") == 10
    assert q.last_activity("u1") == 0.0


# --- aggregate ceiling -----------------------------------------------------
def test_ceiling_refuses_once_total_is_reached(tmp_path):
    q = _quota(tmp_path, ceiling=100)
    q.record("a", 60)
    q.record("b", 50)
    with pytest.raises(QuotaExceeded) as e:
        q.admit("c")
    assert e.value.scope == "aggregate"


def test_ceiling_allows_below_the_limit(tmp_path):
    q = _quota(tmp_path, ceiling=1000)
    q.record("a", 10)
    q.admit("c")


def test_zero_ceiling_disables_the_check(tmp_path):
    q = _quota(tmp_path, ceiling=0)
    q.record("a", 10**12)
    q.admit("c")
