"""Thin HTTP client for a runner's embedded Open Terminal server.

Used by Lane B for two lifecycle decisions, NOT for proxying user traffic
(that is Lane C):

  · idle detection (C7)  — a runner with a live process is not idle, no matter
                           how long since the last request
  · quota polling (N4)   — measure workspace usage from inside the container,
                           so the orchestrator never mounts users' files
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class RunnerUnreachable(RuntimeError):
    pass


def _headers(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def list_processes(base_url: str, key: str, timeout: float = 5.0) -> list[dict]:
    """GET /execute — the process list. This endpoint is why the proxy posture
    had to become a denylist (C3/Q5); without it 'idle' cannot be answered."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(f"{base_url}/execute", headers=_headers(key))
            r.raise_for_status()
            body = r.json()
    except Exception as exc:  # noqa: BLE001 - caller decides what a failure means
        raise RunnerUnreachable(str(exc)) from exc
    if isinstance(body, dict):
        for field in ("processes", "items", "data"):
            if isinstance(body.get(field), list):
                return body[field]
        return []
    return body if isinstance(body, list) else []


def has_running_process(processes: list[dict]) -> bool:
    """Anything not in a terminal state counts as busy. Unknown shapes are
    treated as busy: refusing to tear down is the safe failure direction."""
    terminal = {"done", "exited", "finished", "killed", "failed", "error", "terminated"}
    for p in processes:
        if not isinstance(p, dict):
            return True
        status = str(p.get("status", "")).lower()
        if status and status not in terminal:
            return True
        if not status and p.get("exit_code") is None:
            return True
    return False


async def exec_sync(
    base_url: str, key: str, command: str, wait: int = 15, timeout: float = 30.0
) -> dict[str, Any]:
    """POST /execute with a bounded wait, for short introspection commands."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(
                f"{base_url}/execute",
                headers=_headers(key),
                json={"command": command, "wait": wait},
            )
            r.raise_for_status()
            return r.json()
    except Exception as exc:  # noqa: BLE001
        raise RunnerUnreachable(str(exc)) from exc


def output_text(result: dict[str, Any]) -> str:
    chunks = result.get("output") or []
    return "".join(
        c.get("data", "") for c in chunks if isinstance(c, dict)
    ).strip()
