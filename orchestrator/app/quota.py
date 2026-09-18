"""Workspace disk accounting (N4).

THIS IS DETECTION, NOT PREVENTION — READ BEFORE TRUSTING IT.

    Q6=A (loopback ext4 per user) was the agreed design. It is not
    implementable on this host: it is a Proxmox LXC container with no loop
    devices, an ext4 rootfs without prjquota, and no quota tooling. Measured,
    not assumed — `losetup -f` reports "cannot find an unused loop device".

    So this polls instead of enforcing at the kernel. A writer faster than
    DISK_POLL_INTERVAL can exceed the cap between samples. Accepted for v1 on
    the strength of the host's free-space margin.

    Everything behind this seam is swappable. When the host gains real quotas
    (remount with prjquota, or move the orch to a full VM), implement `measure`
    and `admit` against the kernel and delete the polling worker. Nothing
    outside this module knows how usage is obtained.

Usage is measured from INSIDE the runner via its own API, so the orchestrator
never bind-mounts other users' files. The cost is that a stopped runner cannot
be measured, hence the on-disk last-known cache used for the aggregate ceiling.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass

from . import runner_client as rc

log = logging.getLogger(__name__)


class QuotaExceeded(RuntimeError):
    def __init__(self, uid: str, used: int, limit: int, scope: str):
        self.uid, self.used, self.limit, self.scope = uid, used, limit, scope
        super().__init__(
            f"{scope} quota exceeded for {uid}: {used} bytes used, limit {limit}"
        )


@dataclass
class Sample:
    bytes_used: int
    at: float
    # Last time this uid actually used its runner. Distinct from `at`, which is
    # only when we last measured. Retention must key off real activity, or a
    # measurement sweep would keep dead workspaces alive forever.
    seen: float = 0.0


class MonitorQuota:
    """Poll-based workspace accounting. See the module docstring for why."""

    def __init__(self, state_dir: str, soft: int, hard: int, ceiling: int):
        self.soft, self.hard, self.ceiling = soft, hard, ceiling
        self._path = os.path.join(state_dir, "usage.json")
        self._samples: dict[str, Sample] = {}
        self._load()

    # --- persistence -----------------------------------------------------
    def _load(self) -> None:
        try:
            with open(self._path) as fh:
                raw = json.load(fh)
            self._samples = {
                k: Sample(int(v["bytes_used"]), float(v["at"]),
                          float(v.get("seen", 0.0)))
                for k, v in raw.items()
            }
            log.info("quota: loaded %d cached workspace sizes", len(self._samples))
        except FileNotFoundError:
            pass
        except Exception as exc:  # noqa: BLE001 - a corrupt cache must not block boot
            log.warning("quota: ignoring unreadable usage cache: %s", exc)

    def _save(self) -> None:
        tmp = f"{self._path}.tmp"
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(tmp, "w") as fh:
                json.dump(
                    {k: {"bytes_used": s.bytes_used, "at": s.at, "seen": s.seen}
                     for k, s in self._samples.items()},
                    fh,
                )
            os.replace(tmp, self._path)
        except Exception as exc:  # noqa: BLE001
            log.warning("quota: could not persist usage cache: %s", exc)

    # --- accounting -------------------------------------------------------
    def last_known(self, uid: str) -> int:
        s = self._samples.get(uid)
        return s.bytes_used if s else 0

    def total_known(self) -> int:
        return sum(s.bytes_used for s in self._samples.values())

    def record(self, uid: str, used: int) -> None:
        prev = self._samples.get(uid)
        self._samples[uid] = Sample(used, time.time(), prev.seen if prev else 0.0)
        self._save()

    def note_activity(self, uid: str) -> None:
        """Mark a uid as active now. Cheap and in-memory; persisted on the next
        measurement or sweep, which is frequent enough for a day-scale policy."""
        s = self._samples.get(uid)
        if s is None:
            self._samples[uid] = Sample(0, 0.0, time.time())
            self._save()
        else:
            s.seen = time.time()

    def last_activity(self, uid: str) -> float:
        s = self._samples.get(uid)
        return s.seen if s else 0.0

    def flush(self) -> None:
        self._save()

    def forget(self, uid: str) -> None:
        if self._samples.pop(uid, None) is not None:
            self._save()

    async def measure(self, uid: str, base_url: str, key: str) -> int | None:
        """`du -sb` inside the runner. Returns None if the runner did not answer;
        callers must not treat that as zero."""
        try:
            res = await rc.exec_sync(base_url, key, "du -sb \"$HOME\" 2>/dev/null | cut -f1", wait=20)
        except rc.RunnerUnreachable as exc:
            log.debug("quota: %s unreachable for measurement: %s", uid, exc)
            return None
        text = rc.output_text(res)
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            log.debug("quota: unparseable du output for %s: %r", uid, text[:120])
            return None
        used = int(digits)
        self.record(uid, used)
        return used

    # --- gates -------------------------------------------------------------
    def admit(self, uid: str) -> None:
        """Called before spawning. Uses cached sizes, which is the best we can
        do for a user whose container is not running."""
        used = self.last_known(uid)
        if self.soft and used >= self.soft:
            raise QuotaExceeded(uid, used, self.soft, "workspace")
        total = self.total_known()
        if self.ceiling and total >= self.ceiling:
            raise QuotaExceeded(uid, total, self.ceiling, "aggregate")

    def over_hard(self, uid: str) -> bool:
        return bool(self.hard) and self.last_known(uid) >= self.hard
