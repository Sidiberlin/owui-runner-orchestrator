"""Background workers: idle teardown (C7) and quota polling (N4).

THE IDLE RULE — why this is not just a timestamp comparison

    The brief's original "tear down after IDLE_TIMEOUT" would kill a container
    mid-build: POST /execute is fire-and-forget, so a user who starts a
    45-minute compile and closes the chat tab looks idle by request time alone.

        idle  ==  no request for IDLE_TIMEOUT
                  AND GET /execute reports no running process

    The second clause is why the proxy had to become a denylist (Q5): the
    allowlist in the original spec omitted GET /execute, so this question was
    unanswerable.

    Consequence worth knowing: a genuinely runaway process keeps its runner
    alive indefinitely. RUNNER_CPUS caps the damage, and DELETE /execute/{id}
    (also restored by Q5) is the operator's kill switch. We log it loudly
    rather than silently killing work that may be real.
"""
from __future__ import annotations

import asyncio
import logging
import time

from . import runner_client as rc
from .runners import RunnerManager

log = logging.getLogger(__name__)

async def idle_worker(mgr: RunnerManager) -> None:
    busy_past_idle: dict[str, int] = {}
    while True:
        try:
            await asyncio.sleep(mgr.cfg.idle_sweep_interval)
            # Reclaim phantom slots promptly rather than waiting for the
            # unlucky user who happens to request next.
            await mgr.prune_dead()
            now = time.time()
            for runner in mgr.all():
                if runner.in_flight:
                    # A request is being served right now. Never tear this down;
                    # doing so hands the user a 502 mid-call.
                    continue
                idle_for = now - runner.last_seen
                # v2 (ADR-0012, ticket 07): the timeout THIS runner was
                # created under, not a single global -- survives restart via
                # the durable label (runners.py's _label_idle_timeout).
                if idle_for < runner.idle_timeout:
                    busy_past_idle.pop(runner.uid, None)
                    continue
                try:
                    procs = await rc.list_processes(runner.base_url, runner.key)
                except rc.RunnerUnreachable as exc:
                    # Past idle AND not answering: it is serving nobody and
                    # holding a budget slot. Reclaim it.
                    log.warning(
                        "idle sweep: %s unreachable after %.0fs idle (%s); reclaiming",
                        runner.name, idle_for, exc,
                    )
                    await mgr.teardown(runner.uid, "idle and unreachable")
                    continue
                if rc.has_running_process(procs):
                    n = busy_past_idle.get(runner.uid, 0) + 1
                    busy_past_idle[runner.uid] = n
                    if n in (1, 10) or n % 60 == 0:
                        log.info(
                            "idle sweep: %s idle %.0fs but has running work; "
                            "keeping (sweep #%d)", runner.name, idle_for, n,
                        )
                    continue
                busy_past_idle.pop(runner.uid, None)
                await mgr.teardown(runner.uid, f"idle {idle_for:.0f}s, no running work")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a worker must never die silently
            log.exception("idle worker iteration failed; continuing")


async def quota_worker(mgr: RunnerManager) -> None:
    """Poll workspace usage and stop anything over the hard cap.

    Detection, not prevention — see quota.py. A writer faster than the poll
    interval wins the race; this bounds the steady state, not the worst case.
    """
    while True:
        try:
            await asyncio.sleep(mgr.cfg.disk_poll_interval)
            for runner in mgr.all():
                used = await mgr.quota.measure(runner.uid, runner.base_url, runner.key)
                if used is None:
                    continue
                if mgr.quota.over_hard(runner.uid):
                    log.warning(
                        "quota: %s at %d bytes, over hard cap %d; stopping",
                        runner.name, used, mgr.cfg.disk_hard,
                    )
                    await mgr.teardown(
                        runner.uid,
                        f"workspace over hard cap ({used // 1024**2} MiB)",
                    )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("quota worker iteration failed; continuing")


async def retention_sweep(mgr: RunnerManager, dry_run: bool = False) -> list[dict]:
    """One retention pass. Returns what was (or would be) deleted.

    Split out of the worker so it can be driven deterministically by tests and
    by `POST /_orch/retention/sweep?dry_run=true`, which is the safe way to see
    what a policy would do before enabling it.

    Three guards, in order of how badly each would hurt if missing:

    1. **Scoped to this orchestrator's network.** N27 proved two stacks on one
       host act on each other's resources when the filter is the managed label
       alone. There it cost a live session; here it would cost data.
    2. **Never a live runner.**
    3. **Never a uid with no activity record** — its clock is started instead,
       so a fresh orchestrator or a restored state file cannot delete on first
       sight. Worst case that grants one extra retention period, which is the
       right direction to be wrong in.
    """
    from . import volumes as V

    days = mgr.cfg.retention_days
    if days <= 0:
        return []
    cutoff, now, out = days * 86400.0, time.time(), []

    for vol in await V.list_workspace_volumes(mgr.client, mgr.cfg.runners_network):
        uid, name = V.volume_uid(vol), vol.get("Name") or ""
        if not uid or not name:
            continue
        if mgr.get(uid) is not None:
            continue
        seen = mgr.quota.last_activity(uid)
        if not seen:
            mgr.quota.note_activity(uid)
            log.info("retention: first sight of %s, starting its clock", name)
            continue
        idle = now - seen
        if idle < cutoff:
            continue
        entry = {
            "volume": name, "uid": uid,
            "idle_days": round(idle / 86400.0, 2),
            "size_mb": mgr.quota.last_known(uid) // 1024**2,
        }
        out.append(entry)
        if dry_run:
            continue
        log.warning(
            "retention: deleting %s (uid=%s, inactive %.1f days, policy %.1f)",
            name, uid, idle / 86400.0, days,
        )
        await V.remove_volume(mgr.client, name)
        mgr.quota.forget(uid)
    if out and not dry_run:
        mgr.quota.flush()
        log.warning("retention: deleted %d workspace volume(s)", len(out))
    return out


async def retention_worker(mgr: RunnerManager) -> None:
    """Periodic R2 sweep. Disabled unless VOLUME_RETENTION_DAYS > 0 — this
    deletes user data, so it is opt-in rather than something an operator
    discovers after the fact."""
    while True:
        try:
            await asyncio.sleep(mgr.cfg.retention_sweep_interval)
            await retention_sweep(mgr)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("retention worker iteration failed; continuing")
