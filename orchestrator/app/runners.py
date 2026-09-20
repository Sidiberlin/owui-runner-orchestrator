"""Runner lifecycle: spawn, adopt, reconcile, tear down, budget.

    SPAWN PATH — every gate here exists because of a specific review finding

                        request for uid
                              │
                       ┌──────▼───────┐
                       │ per-uid lock │  A5: two parallel OWUI tool calls must
                       └──────┬───────┘      not create two containers that
                              │               mount one volume simultaneously
                  in memory? ─┴─ yes ─► touch ─► ROUTE
                              │ no
                  adopt by name + labels?      A4: survives an orchestrator
                              ├─ yes ─► re-derive key from      restart; without
                              │         the label nonce (N1)    this, adopted
                              │         ─► ROUTE                runners are
                              │ no                              unauthenticatable
                  admission ─┬─ budget full ────► BudgetExhausted  (R3 -> 429)
                             ├─ host memory low ► BudgetExhausted  (R3)
                             └─ quota           ► QuotaExceeded    (N4)
                              │ ok
                  ensure volume (N7: mounts at /home/user)
                              │
                  create with EXACTLY the runners network   A6: never let a
                              ├─ 409 name taken ─► adopt        runner land on
                              │ ok                              the default
                  start ─► wait healthy ─► assert 1 network      bridge with
                              │                                  egress
                            ROUTE

    TEARDOWN is never unconditional: see workers.py for the C7 idle rule.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiodocker

from . import dockerapi, keys, labels as L, orientation, volumes
from .config import Config, DEFAULT_EGRESS_STANCE, DEFAULT_PROFILE_NAME
from .quota import MonitorQuota, QuotaExceeded

log = logging.getLogger(__name__)

_SAFE = re.compile(r"[^a-zA-Z0-9_.-]")


class BudgetExhausted(RuntimeError):
    """Capacity refusal. Lane C maps this to a clean 429 the agent can relay
    to the user, never a stack trace (R3)."""


class SpawnFailed(RuntimeError):
    pass


def safe_uid(uid: str) -> str:
    """Container and volume names allow [a-zA-Z0-9_.-] and must start
    alphanumeric. OWUI user ids are UUIDs today, but nothing guarantees that,
    so anything unusual collapses to a hash. The raw uid always survives on the
    label, which is what reconciliation reads."""
    cleaned = _SAFE.sub("-", uid)
    if cleaned != uid or len(cleaned) > 48 or not cleaned[:1].isalnum():
        return hashlib.sha256(uid.encode()).hexdigest()[:32]
    return cleaned


@dataclass
class Runner:
    uid: str
    safe_uid: str
    container_id: str
    name: str
    nonce: str
    key: str
    port: int
    last_seen: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    role: str = "user"
    memory: int = 0
    # v2 (ADR-0012): the Policy profile this runner was created under, or
    # DEFAULT_PROFILE_NAME. Restored by reconciliation from the durable
    # label, same as `role` above, so an orchestrator restart never quietly
    # relabels a mapped runner as default.
    profile: str = DEFAULT_PROFILE_NAME
    # C7: set when this container replaced a torn-down one, so the proxy can
    # explain a stale process id instead of passing through a bare 404.
    replaced_reason: str | None = None
    # Number of proxied requests currently in flight against this runner. A
    # runner serving a request is never idle, no matter what last_seen says.
    in_flight: int = 0

    @property
    def base_url(self) -> str:
        # Docker DNS on the runners network. The orchestrator is attached to
        # that network, so the container name resolves without publishing a
        # port or tracking IPs across restarts.
        return f"http://{self.name}:{self.port}"


def available_memory_bytes() -> int | None:
    """Host memory available, as seen from inside this container.

    WARNING — this number is NOT trustworthy on every host, which is why the
    gate that uses it is off by default. See `Config.memory_gate`.

    Measured on the target host (Docker inside a Proxmox LXC container):

        host  /proc/meminfo MemAvailable : 1908 MiB
        orchestrator container's view    :  534 MiB

    /proc/meminfo is virtualised inside the container and under-reports by
    well over a gigabyte, so an admission gate built on it refuses users while
    the host has plenty of RAM. It is still reported by /_orch/status as a
    diagnostic, just not used to deny service unless explicitly enabled.
    """
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except Exception:  # noqa: BLE001
        return None
    return None


class RunnerManager:
    def __init__(self, cfg: Config, client: aiodocker.Docker, quota: MonitorQuota):
        self.cfg = cfg
        self.client = client
        self.quota = quota
        self._runners: dict[str, Runner] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()
        self._tombstones: dict[str, tuple[str, float]] = {}

    # --- locking ----------------------------------------------------------
    async def _lock_for(self, uid: str) -> asyncio.Lock:
        async with self._locks_guard:
            return self._locks.setdefault(uid, asyncio.Lock())

    # --- startup ----------------------------------------------------------
    async def startup(self) -> None:
        """R4: fail loudly at boot if the image is missing, rather than inside
        the first user's request where it looks like an orchestrator bug."""
        if not await dockerapi.image_exists(self.client, self.cfg.runner_image):
            raise RuntimeError(
                f"runner image {self.cfg.runner_image!r} not present. "
                "Build it first: docker compose --profile build build runner-image"
            )
        log.info("runner image %s present", self.cfg.runner_image)
        await self.reconcile()
        # Ticket 04 Q3c: SANDBOX_INTERNAL_SERVICES is static config, checked
        # once against reality at boot. Warn, never fail - a drifted name is
        # an operator config problem, not a reason to refuse every runner.
        drifted = await orientation.check_dns_drift(
            orientation.sandbox_services(self.cfg)
        )
        if drifted:
            log.warning(
                "SANDBOX_INTERNAL_SERVICES lists unreachable name(s) on %s: %s",
                self.cfg.runners_network, ", ".join(drifted),
            )

    # --- reconciliation (A4) -----------------------------------------------
    async def reconcile(self) -> None:
        """Rebuild in-memory state from container labels after a restart.

        Without this the orchestrator spawns duplicates, blows MAX_CONTAINERS,
        and the idle worker never reaps the originals because it does not know
        they exist.
        """
        found = await self.client.containers.list(
            all=True,
            # Scoped to OUR network: a second orchestrator on the same Docker
            # host must not adopt these. Without this it does, and then reaps
            # them under its own IDLE_TIMEOUT.
            filters=dockerapi.label_filter(**{
                L.MANAGED: L.MANAGED_VALUE,
                L.NETWORK: self.cfg.runners_network,
            }),
        )
        adopted = reaped = 0
        for c in found:
            try:
                data = await c.show()
            except aiodocker.exceptions.DockerError:
                continue
            lbls = (data.get("Config") or {}).get("Labels") or {}
            uid = lbls.get(L.UID)
            nonce = lbls.get(L.NONCE)
            version = lbls.get(L.VERSION)
            running = (data.get("State") or {}).get("Running", False)
            reason = None
            if not uid or not nonce:
                reason = "missing identity labels"
            elif version != self.cfg.runner_version:
                reason = f"stale runner version {version!r}"
            elif not running:
                reason = "not running"
            if reason:
                log.info("reconcile: reaping %s (%s)", data.get("Name"), reason)
                await self._force_remove(c)
                reaped += 1
                continue
            self._runners[uid] = Runner(
                uid=uid,
                safe_uid=safe_uid(uid),
                container_id=data["Id"],
                name=(data.get("Name") or "").lstrip("/"),
                nonce=nonce,
                # N1: re-derived, never stored. This is the whole point of
                # putting the nonce on a label.
                key=keys.derive_key(self.cfg.master_secret, uid, nonce),
                port=self.cfg.runner_port,
                memory=int((data.get("HostConfig") or {}).get("Memory") or 0),
                role=lbls.get(L.ROLE, "user"),
                profile=lbls.get(L.PROFILE, DEFAULT_PROFILE_NAME),
            )
            adopted += 1
        log.info("reconcile: adopted %d, reaped %d", adopted, reaped)

    # --- liveness -------------------------------------------------------------
    async def prune_dead(self) -> int:
        """Drop tracked runners whose containers no longer exist.

        Found by the Lane E budget test. Containers can vanish out of band:
        an OOM kill, a crash, a `docker rm` by the operator. The in-memory map
        kept counting them, so each phantom permanently consumed one of
        MAX_CONTAINERS until either that same user made another request or the
        idle sweep noticed after IDLE_TIMEOUT (30 minutes in production).

        Three crashed runners meant a total lockout, with every user told
        "all 3 runner slots are in use" while zero containers existed.
        """
        dead = [uid for uid, r in list(self._runners.items())
                if not await self._is_alive(r)]
        for uid in dead:
            log.warning("pruning %s: its container is gone", uid)
            self._runners.pop(uid, None)
            self._tombstones[uid] = ("the runner stopped unexpectedly", time.time())
        return len(dead)

    # --- admission ----------------------------------------------------------
    def committed_memory(self) -> int:
        """What this orchestrator has promised the kernel, which it knows
        exactly — unlike free-memory readings from a virtualised /proc."""
        return sum(r.memory for r in self._runners.values())

    def _admit(self, uid: str, memory: int) -> None:
        live = len(self._runners)
        if live >= self.cfg.max_containers:
            raise BudgetExhausted(
                f"all {self.cfg.max_containers} runner slots are in use; "
                "try again once another session goes idle"
            )
        # Deterministic bound: the sum of what we have actually committed.
        # MAX_CONTAINERS x RUNNER_MEMORY is the real protection, and unlike a
        # free-memory probe it cannot misfire.
        if self.cfg.memory_budget:
            committed = self.committed_memory()
            if committed + memory > self.cfg.memory_budget:
                raise BudgetExhausted(
                    f"runner memory budget exhausted "
                    f"({(committed + memory) // 1024**2} MiB would be committed, "
                    f"{self.cfg.memory_budget // 1024**2} MiB allowed)"
                )
        # Opt-in only: see available_memory_bytes() for why this is not the
        # default. Enable it on a host where /proc/meminfo is accurate.
        if self.cfg.memory_gate:
            avail = available_memory_bytes()
            if avail is not None:
                needed = memory + self.cfg.memory_reserve
                if avail < needed:
                    raise BudgetExhausted(
                        f"host memory too low to start another runner "
                        f"({avail // 1024**2} MiB available, "
                        f"{needed // 1024**2} MiB needed)"
                    )
        self.quota.admit(uid)

    # --- public API used by Lane C -------------------------------------------
    def touch(self, uid: str) -> None:
        r = self._runners.get(uid)
        if r:
            r.last_seen = time.time()
        # Recorded even without a live runner: a request that fails admission
        # still proves the account is in use, and must protect its workspace
        # from the retention sweep.
        self.quota.note_activity(uid)

    @contextlib.asynccontextmanager
    async def serving(self, uid: str):
        """Mark a runner busy for the duration of one proxied request.

        Closes a race the Lane E suite caught: the idle sweep could decide a
        runner was idle and tear it down in the microseconds between
        get_or_spawn() returning and the proxy actually connecting, so a user
        who was mid-request got a 502. last_seen alone cannot express "a
        request is happening right now".
        """
        r = self._runners.get(uid)
        if r is not None:
            r.in_flight += 1
            r.last_seen = time.time()
        self.quota.note_activity(uid)
        try:
            yield
        finally:
            if r is not None:
                r.in_flight = max(0, r.in_flight - 1)
                r.last_seen = time.time()

    def get(self, uid: str) -> Runner | None:
        return self._runners.get(uid)

    def all(self) -> list[Runner]:
        return list(self._runners.values())

    def tombstone(self, uid: str) -> str | None:
        """C7: a process_id whose container is gone must produce a stable,
        distinguishable error rather than a generic 500."""
        entry = self._tombstones.get(uid)
        return entry[0] if entry else None

    async def get_or_spawn(self, uid: str, policy=None) -> Runner:
        """`policy` comes from the role mapper (Lane C). It is applied at spawn
        time only: a role change (or a profile change, v2) takes effect on
        the user's next runner, not retroactively on a live one.

        v2 (ADR-0012, ticket 05): cpus/memory stay role-derived
        (`policy.nano_cpus`/`.memory`, admin vs user, exactly as v1) when the
        resolved profile is the implicit default -- this is what keeps an
        empty GROUP_MAP a byte-for-byte no-op (ticket 01's guard) and admin's
        larger limits intact when no group maps (ticket 05's own checklist).
        A REAL mapped profile's cpus/memory fully replace the role-derived
        ones instead: profiles apply uniformly to whoever is in the mapped
        group, admin or not. Image and exec timeout are NOT role-derived in
        v1, so they always come from the resolved profile -- the default
        profile's image/exec_timeout equal cfg.runner_image/ot_execute_timeout
        by construction (ticket 03), so this is a no-op by itself too.
        """
        profile = policy.profile if policy else None
        if profile and profile.name != DEFAULT_PROFILE_NAME:
            nano = profile.nano_cpus
            mem = profile.memory
        else:
            nano = policy.nano_cpus if policy else self.cfg.runner_nano_cpus
            mem = policy.memory if policy else self.cfg.runner_memory
        image = profile.image if profile else self.cfg.runner_image
        exec_timeout = (
            profile.exec_timeout if profile else float(self.cfg.ot_execute_timeout)
        )
        # v2 (ticket 06): the default profile's egress equals
        # DEFAULT_EGRESS_STANCE by construction (ticket 03), so this is a
        # no-op for a caller with no resolved profile too.
        egress = profile.egress if profile else DEFAULT_EGRESS_STANCE
        profile_name = profile.name if profile else DEFAULT_PROFILE_NAME
        role = policy.role if policy else "user"
        lock = await self._lock_for(uid)
        async with lock:
            existing = self._runners.get(uid)
            if existing and await self._is_alive(existing):
                existing.last_seen = time.time()
                return existing
            if existing:
                log.info("runner for %s vanished; respawning", uid)
                self._runners.pop(uid, None)
            adopted = await self._try_adopt(uid)
            if adopted:
                return adopted
            # Reclaim slots held by containers that died out of band before
            # telling this user the budget is full.
            await self.prune_dead()
            self._admit(uid, mem)
            return await self._spawn(
                uid, nano, mem, role, image, exec_timeout, profile_name, egress,
            )

    # --- internals ------------------------------------------------------------
    async def _is_alive(self, runner: Runner) -> bool:
        try:
            data = await self.client.containers.container(runner.container_id).show()
        except aiodocker.exceptions.DockerError:
            return False
        return bool((data.get("State") or {}).get("Running"))

    async def _try_adopt(self, uid: str) -> Runner | None:
        """The deterministic name is the guard that survives a restart; the
        in-memory lock alone cannot (A5)."""
        name = f"runner-{safe_uid(uid)}"
        try:
            data = await self.client.containers.container(name).show()
        except aiodocker.exceptions.DockerError:
            return None
        lbls = (data.get("Config") or {}).get("Labels") or {}
        nonce = lbls.get(L.NONCE)
        running = (data.get("State") or {}).get("Running", False)
        # Container names are runner-<uid> and therefore IDENTICAL across two
        # deployments for the same user. Never touch one we do not own.
        owner = lbls.get(L.NETWORK)
        if owner is None or owner == "":
            # Legacy: created before runners were stamped with an owner. It
            # cannot be proven ours, but it also blocks the deterministic name.
            # Reap it so a correctly-labelled one takes its place; the user's
            # workspace volume is untouched.
            log.info("adopt: %s predates owner labelling - reaping to respawn", name)
            await self._force_remove(self.client.containers.container(name))
            return None
        if owner != self.cfg.runners_network:
            log.warning(
                "adopt: %s belongs to %r, not %r - leaving it alone",
                name, owner, self.cfg.runners_network,
            )
            return None
        if not nonce or lbls.get(L.VERSION) != self.cfg.runner_version or not running:
            log.info("adopt: removing unusable container %s", name)
            await self._force_remove(self.client.containers.container(name))
            return None
        runner = Runner(
            uid=uid,
            safe_uid=safe_uid(uid),
            container_id=data["Id"],
            name=name,
            nonce=nonce,
            key=keys.derive_key(self.cfg.master_secret, uid, nonce),
            port=self.cfg.runner_port,
            memory=int((data.get("HostConfig") or {}).get("Memory") or 0),
            role=lbls.get(L.ROLE, "user"),
            profile=lbls.get(L.PROFILE, DEFAULT_PROFILE_NAME),
        )
        self._runners[uid] = runner
        log.info("adopted existing runner %s for %s", name, uid)
        return runner

    def _runner_env(self, key: str, exec_timeout: float, egress: str) -> list[str]:
        env = {
            "OPEN_TERMINAL_API_KEY": key,
            "OPEN_TERMINAL_MULTI_USER": "false",
            "OPEN_TERMINAL_FILE_BROWSER_ROOT": "home",
            "OPEN_TERMINAL_MAX_SESSIONS": str(self.cfg.ot_max_sessions),
            # v2: per-profile (ticket 05). round(), not int(): a profile
            # declaring a sub-second value (unusual, but POLICY_*_EXEC_TIMEOUT
            # accepts anything parse_duration does) should land on the
            # nearest whole second the runner's own executor understands,
            # not always truncate down.
            "OPEN_TERMINAL_EXECUTE_TIMEOUT": str(round(exec_timeout)),
            "OPEN_TERMINAL_SESSION_CWD_TTL": str(self.cfg.ot_session_cwd_ttl),
        }
        # Package Seam (ADR-0008). Empty unless configured; there is no second
        # path by which a runner could reach a public registry.
        if self.cfg.pip_index_url:
            env["PIP_INDEX_URL"] = self.cfg.pip_index_url
            # pip refuses a plain-http index without this.
            if self.cfg.pip_trusted_host:
                env["PIP_TRUSTED_HOST"] = self.cfg.pip_trusted_host
        if self.cfg.npm_registry:
            env["NPM_CONFIG_REGISTRY"] = self.cfg.npm_registry
        # N9: OPEN_TERMINAL_ALLOWED_DOMAINS is deliberately never set. Setting
        # it activates the entrypoint's iptables firewall, which needs
        # CAP_NET_ADMIN we do not grant. `internal: true` is the real control.
        # Agent orientation (Workstream L, ticket 13; per-profile, ticket 06).
        env.update(orientation.sandbox_env(self.cfg, egress))
        return [f"{k}={v}" for k, v in env.items()]

    async def _spawn(self, uid: str, nano_cpus: int, memory: int, role: str,
                      image: str, exec_timeout: float, profile_name: str,
                      egress: str) -> Runner:
        s_uid = safe_uid(uid)
        name = f"runner-{s_uid}"
        nonce = keys.mint_nonce()
        key = keys.derive_key(self.cfg.master_secret, uid, nonce)
        vol = await volumes.ensure_volume(
            self.client, s_uid, uid, self.cfg.runner_version,
            network=self.cfg.runners_network,
        )

        config = {
            "Image": image,
            "Labels": L.build(
                uid, nonce, self.cfg.runner_version,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                role=role, network=self.cfg.runners_network,
                profile=profile_name,
            ),
            "Env": self._runner_env(key, exec_timeout, egress),
            "HostConfig": {
                "NanoCpus": nano_cpus,
                "Memory": memory,
                "PidsLimit": self.cfg.runner_pids,
                "CapDrop": ["ALL"],
                # N8: the entrypoint starts as root, chowns $HOME (the real fix
                # for a fresh root-owned volume, C5), then gosu-drops to uid
                # 1000. Trimming these breaks both. Lane A's persistence test
                # is what catches it.
                "CapAdd": self.cfg.runner_cap_add,
                "SecurityOpt": self.cfg.runner_security_opt,
                # Ephemeral by design: a self-restarting runner defeats teardown.
                "RestartPolicy": {"Name": "no"},
                "Binds": [f"{vol}:{volumes.MOUNT_PATH}"],
                "NetworkMode": self.cfg.runners_network,
            },
            # A6: the network is set AT CREATE, not attached afterwards.
            # Create-then-connect leaves the container on the default bridge
            # first, which silently restores egress.
            "NetworkingConfig": {
                "EndpointsConfig": {self.cfg.runners_network: {}}
            },
        }

        try:
            container = await self.client.containers.create(config=config, name=name)
        except aiodocker.exceptions.DockerError as exc:
            if exc.status == 409:
                # Lost a race against another orchestrator or a leftover.
                log.info("create raced on %s; adopting instead", name)
                adopted = await self._try_adopt(uid)
                if adopted:
                    return adopted
            raise SpawnFailed(f"could not create runner for {uid}: {exc}") from exc

        try:
            await container.start()
            await self._assert_single_network(container, name)
            await self._wait_healthy(container, name)
        except Exception:
            await self._force_remove(container)
            raise

        # Agent orientation (ticket 13): the prose channel. "Startup only if
        # absent" (L1) - a fresh volume gets it seeded, an existing one (or a
        # user's own edits) is left alone. Best effort; never blocks a spawn.
        await orientation.seed_agents_md(
            f"http://{name}:{self.cfg.runner_port}", key,
            orientation.render_agents_md(
                orientation.sandbox_services(self.cfg), egress,
            ),
        )

        data = await container.show()
        prior = self._tombstones.get(uid)
        runner = Runner(
            uid=uid, safe_uid=s_uid, container_id=data["Id"], name=name,
            nonce=nonce, key=key, port=self.cfg.runner_port, role=role,
            memory=memory, profile=profile_name,
            # Kept for the life of this container: any process id from the
            # previous incarnation stays invalid for as long as this one lives.
            replaced_reason=prior[0] if prior else None,
        )
        self._runners[uid] = runner
        log.info("spawned runner %s for %s", name, uid)
        return runner

    async def _assert_single_network(self, container, name: str) -> None:
        """A6, enforced rather than assumed. A curl test from inside is not
        enough: it only proves the network you happened to probe."""
        data = await container.show()
        nets = list(((data.get("NetworkSettings") or {}).get("Networks") or {}).keys())
        if nets != [self.cfg.runners_network]:
            raise SpawnFailed(
                f"{name} attached to {nets!r}, expected exactly "
                f"[{self.cfg.runners_network!r}] - refusing to serve a runner "
                "that may have egress"
            )

    async def _wait_healthy(self, container, name: str, timeout: float = 90.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = await container.show()
            state = data.get("State") or {}
            if not state.get("Running"):
                raise SpawnFailed(f"{name} exited during startup")
            health = (state.get("Health") or {}).get("Status")
            if health == "healthy" or health is None:
                if health is None:
                    # No healthcheck in the image: fall back to running.
                    return
                return
            if health == "unhealthy":
                raise SpawnFailed(f"{name} reported unhealthy")
            await asyncio.sleep(1.0)
        raise SpawnFailed(f"{name} did not become healthy within {timeout:.0f}s")

    async def _force_remove(self, container) -> None:
        try:
            await container.delete(force=True, v=False)
        except aiodocker.exceptions.DockerError as exc:
            if exc.status != 404:
                log.warning("could not remove container: %s", exc)

    async def teardown(self, uid: str, reason: str) -> None:
        lock = await self._lock_for(uid)
        async with lock:
            runner = self._runners.pop(uid, None)
            if not runner:
                return
            log.info("tearing down %s (%s)", runner.name, reason)
            await self._force_remove(
                self.client.containers.container(runner.container_id)
            )
            # C7: remember why, so a stale process_id gets a clear answer.
            self._tombstones[uid] = (reason, time.time())
            if len(self._tombstones) > 256:
                oldest = sorted(self._tombstones.items(), key=lambda kv: kv[1][1])
                for k, _ in oldest[:64]:
                    self._tombstones.pop(k, None)

    async def shutdown(self) -> None:
        """Runners deliberately OUTLIVE the orchestrator: they are adopted on
        the next boot (A4). Only the client is closed here."""
        await self.client.close()
