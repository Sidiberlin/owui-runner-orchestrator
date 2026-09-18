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
                if idle_for < mgr.cfg.idle_timeout:
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
