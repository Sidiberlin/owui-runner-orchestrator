"""Orchestrator app — Lanes B (lifecycle) + C (proxy, auth, role mapper).

ROUTE NAMESPACE
    Everything this service owns lives under /_orch/. The rest of the URL space
    belongs to the runner's Open Terminal and is proxied verbatim.

    That prefix is deliberate. A route of our own at, say, /admin would shadow
    any upstream path of the same name the day Open Terminal adds one, and the
    failure would be silent — exactly the class of breakage the denylist
    posture (Q5) exists to avoid. /_orch/ is reserved and upstream will never
    use it.

REQUEST PATH
    OWUI backend ──K1──► authenticate ──► role mapper (A8 fail-closed)
                                            │
                                   pending/unknown ──► 403
                                   OWUI down, no cache ──► 503
                                            │ Policy
                                   denylist check (Q5) ──► 403
                                            │
                                   get_or_spawn(uid, policy)
                                     budget/memory ──► 429
                                            │
                                   stream to runner (C8, never buffered)
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from . import auth, dockerapi, proxy, workers
from .config import Config
from .quota import MonitorQuota, QuotaExceeded
from .roles import RoleMapper
from .runners import BudgetExhausted, RunnerManager, SpawnFailed, available_memory_bytes

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("orchestrator")

state: dict[str, object] = {}


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = Config.from_env()
    client = dockerapi.make_client(cfg.docker_host, cfg.docker_api_version)
    quota = MonitorQuota(cfg.state_dir, cfg.disk_soft, cfg.disk_hard, cfg.total_ceiling)
    mgr = RunnerManager(cfg, client, quota)
    mapper = RoleMapper(cfg)
    # read=None: this is a reverse proxy. /execute long-polls and file reads can
    # be large, so a read deadline here would sever legitimate work. Runaway
    # upstreams are bounded by the runner's own EXECUTE_TIMEOUT instead.
    pclient = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=None, write=None, pool=5.0),
        follow_redirects=False,
        # No upstream keep-alive. Runners are replaced behind stable DNS names,
        # so a pooled connection can point at a container that no longer
        # exists; the reuse then fails as "Server disconnected without sending
        # a response" on the next request. On a local bridge the extra
        # handshake costs microseconds, and it removes the whole failure class.
        limits=httpx.Limits(max_keepalive_connections=0, max_connections=64),
    )
    state.update(cfg=cfg, mgr=mgr, mapper=mapper, pclient=pclient)

    await mgr.startup()
    tasks = [
        asyncio.create_task(workers.idle_worker(mgr), name="idle"),
        asyncio.create_task(workers.quota_worker(mgr), name="quota"),
        asyncio.create_task(workers.retention_worker(mgr), name="retention"),
    ]
    log.info(
        "ready: max_containers=%d runner_mem=%dMiB idle=%.0fs deny=%s image=%s",
        cfg.max_containers, cfg.runner_memory // 1024**2, cfg.idle_timeout,
        ",".join(cfg.proxy_deny_prefixes), cfg.runner_image,
    )
    # Resolved profile table (ADR-0012, ticket 03): one line per profile so
    # an operator reads what the deployment will actually do instead of
    # re-deriving it from POLICY_* env vars in their head.
    for name in sorted(cfg.profiles):
        p = cfg.profiles[name]
        log.info(
            "policy profile %-12s cpus=%.2f memory=%dMiB idle=%.0fs "
            "exec=%.0fs image=%s egress=%s",
            name, p.nano_cpus / 1_000_000_000, p.memory // 1024**2,
            p.idle_timeout, p.exec_timeout, p.image, p.egress,
        )
    # ADR-0012 seam 6: a GROUP_MAP entry naming a group OWUI's roster does
    # not currently contain (renamed or deleted) silently demotes its
    # members to the default profile -- warn loudly here so that shows up in
    # seconds, not as a mystery incident weeks later. Best-effort: see
    # RoleMapper.unknown_mapped_groups.
    for group in await mapper.unknown_mapped_groups():
        log.warning(
            "GROUP_MAP names group %r, which Open WebUI's roster does not "
            "currently contain (renamed or deleted?); its members fall back "
            "to the default profile", group,
        )
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await pclient.aclose()
        await mapper.aclose()
        await mgr.shutdown()


app = FastAPI(
    title="owui-runner-orchestrator",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _cfg() -> Config:
    return state["cfg"]  # type: ignore[return-value]


def _mgr() -> RunnerManager:
    mgr = state.get("mgr")
    if mgr is None:
        raise HTTPException(503, "orchestrator still starting")
    return mgr  # type: ignore[return-value]


def _mapper() -> RoleMapper:
    mapper = state.get("mapper")
    if mapper is None:
        raise HTTPException(503, "orchestrator still starting")
    return mapper  # type: ignore[return-value]


def _policy_profiles_payload(cfg: Config) -> dict:
    """v2 (ADR-0012, ticket 08): the resolved profile table with effective
    values, same fields the boot log prints (main.py's lifespan) -- an
    operator confirms a mapping took effect here instead of exec-ing into
    anything. With no POLICY_*/GROUP_MAP configured this is just the one
    "default" entry, equal to the global knobs verbatim (ticket 03)."""
    return {
        name: {
            "cpus": p.nano_cpus / 1_000_000_000,
            "memory_mb": p.memory // 1024**2,
            "idle_timeout_s": p.idle_timeout,
            "exec_timeout_s": p.exec_timeout,
            "image": p.image,
            "egress": p.egress,
        }
        for name, p in sorted(cfg.profiles.items())
    }


async def require_orch_key(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    auth.check_api_key(_cfg(), authorization)


# ---------------------------------------------------------------------------
# Orchestrator's own surface. Registered BEFORE the catch-all so it wins.
# ---------------------------------------------------------------------------
@app.get("/_orch/healthz")
async def healthz() -> Response:
    """Unauthenticated on purpose: it is the container healthcheck. It leaks
    nothing but liveness."""
    return Response("ok", media_type="text/plain")


@app.get("/_orch/status", dependencies=[Depends(require_orch_key)])
async def status() -> dict:
    mgr, cfg, mapper = _mgr(), _cfg(), _mapper()
    avail = available_memory_bytes()
    return {
        "runners_live": len(mgr.all()),
        "max_containers": cfg.max_containers,
        "runner_memory_mb": cfg.runner_memory // 1024**2,
        # Diagnostic only by default: inside Docker-on-LXC this reading is
        # virtualised and under-reports badly (534 MiB vs the host's 1908).
        "host_memory_available_mb": (avail // 1024**2) if avail else None,
        "memory_gate_enabled": cfg.memory_gate,
        "committed_memory_mb": mgr.committed_memory() // 1024**2,
        "workspace_total_known_mb": mgr.quota.total_known() // 1024**2,
        "workspace_ceiling_mb": cfg.total_ceiling // 1024**2,
        "volume_retention_days": cfg.retention_days,
        "devguard_enabled": cfg.devguard_enabled,
        "package_seam": {
            "pip_index_url": cfg.pip_index_url or None,
            "npm_registry": cfg.npm_registry or None,
        },
        "idle_timeout_s": cfg.idle_timeout,
        "deny_prefixes": list(cfg.proxy_deny_prefixes),
        "runner_image": cfg.runner_image,
        # v2 (ADR-0012, ticket 08): "did my mapping take effect?", answered
        # without exec-ing into anything. Checked live on every call (not
        # cached from boot) so a group rename shows up here in the next
        # request, not only in the boot log.
        "policy_profiles": _policy_profiles_payload(cfg),
        "unknown_mapped_groups": await mapper.unknown_mapped_groups(),
    }


@app.get("/_orch/runners", dependencies=[Depends(require_orch_key)])
async def list_runners() -> list[dict]:
    mgr = _mgr()
    now = time.time()
    return [
        {
            "uid": r.uid, "name": r.name, "role": r.role,
            "container_id": r.container_id[:12],
            "idle_s": round(now - r.last_seen, 1),
            "workspace_mb": mgr.quota.last_known(r.uid) // 1024**2,
            "replaced_reason": r.replaced_reason,
            # v2 (ADR-0012, ticket 08): the profile this runner was created
            # under -- restart-adopted runners included, restored from the
            # durable label (ticket 05).
            "profile": r.profile,
        }
        for r in mgr.all()
    ]


@app.post("/_orch/retention/sweep", dependencies=[Depends(require_orch_key)])
async def retention_sweep(dry_run: bool = True) -> dict:
    """Run one R2 sweep. Defaults to dry_run so an operator can see what a
    policy would delete before trusting it."""
    mgr, cfg = _mgr(), _cfg()
    acted = await workers.retention_sweep(mgr, dry_run=dry_run)
    return {
        "retention_days": cfg.retention_days,
        "enabled": cfg.retention_days > 0,
        "dry_run": dry_run,
        "count": len(acted),
        "volumes": acted,
    }


@app.delete("/_orch/runners/{uid}", dependencies=[Depends(require_orch_key)])
async def teardown(uid: str) -> dict:
    await _mgr().teardown(uid, "operator request")
    return {"uid": uid, "torn_down": True}


# ---------------------------------------------------------------------------
# Everything else is the runner's Open Terminal. Catch-all, registered LAST.
# ---------------------------------------------------------------------------
def _advertisement(cfg: Config) -> dict:
    """What this orchestrator honestly supports, derived from the denylist.

    Open Terminal itself answers `{"features":{"terminal":true,"notebooks":true,
    "system":true}}`. We must NOT copy that verbatim: `terminal` refers to the
    interactive PTY widget backed by /api/terminals, which the Q5 denylist
    blocks in v1. Advertising it would make OWUI render a terminal pane that
    403s on first use. Deriving the flag from the denylist keeps the
    advertisement true automatically if the denylist ever changes.
    """
    denied = cfg.proxy_deny_prefixes
    return {
        "features": {
            "terminal": not proxy.is_denied("/api/terminals", denied),
            "notebooks": not proxy.is_denied("/notebooks", denied),
            "system": not proxy.is_denied("/system", denied),
        }
    }


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
async def proxy_to_runner(path: str, request: Request) -> Response:
    cfg, mgr = _cfg(), _mgr()
    mapper: RoleMapper = state["mapper"]  # type: ignore[assignment]

    # --- OWUI discovery probe -------------------------------------------------
    # Admin Settings > Integrations "verify" calls the server with the
    # connection key but NO X-User-Id, because no user is in scope yet. It tries
    # GET /api/v1/policies (an enterprise orchestrator) and falls back to
    # GET /api/config (a plain terminal). Without this branch both probes hit
    # the X-User-Id requirement, return 400, and OWUI reports
    # "Failed to connect to the terminal server" — which is exactly what the
    # first live attempt did.
    #
    # We deliberately answer only the /api/config probe. Claiming
    # /api/v1/policies would have OWUI classify this as an orchestrator and
    # drive it with the enterprise policy/lifecycle API, which v1 does not
    # implement. Presenting as one plain terminal is the whole design: OWUI
    # sees a single endpoint, and per-user multiplexing happens behind it.
    if not request.headers.get("x-user-id") and path.strip("/") == "api/config":
        auth.check_api_key(cfg, request.headers.get("authorization"))
        return JSONResponse(_advertisement(cfg))

    policy = await auth.authenticate(request, cfg, mapper)

    denied = proxy.denied_prefix("/" + path, cfg.proxy_deny_prefixes)
    if denied:
        raise HTTPException(
            403,
            f"{denied} is not available through this orchestrator in v1 "
            "(PTY terminals, port previews and the upstream proxy are out of "
            "scope).",
        )

    try:
        runner = await mgr.get_or_spawn(policy.uid, policy)
    except (BudgetExhausted, QuotaExceeded) as exc:
        raise HTTPException(429, str(exc)) from exc
    except SpawnFailed as exc:
        log.warning("spawn failed for %s: %s", policy.uid, exc)
        raise HTTPException(502, f"could not start your runner: {exc}") from exc
    # Operational visibility: who asked for what. No secrets — the uid is the
    # OWUI user id that OWUI itself put on the wire, and the key never appears.
    # profile (ticket 04): resolved per request, not yet applied to any
    # container (ticket 05) — logged here so a mapping change is visible
    # immediately, ahead of any user-facing effect.
    log.info(
        "%s /%s uid=%s role=%s profile=%s -> %s",
        request.method, path, policy.uid, policy.role,
        policy.profile.name if policy.profile else None, runner.name,
    )

    # Held for the whole proxied call so the idle sweep cannot tear this
    # runner down underneath an active request.
    async with mgr.serving(policy.uid):
        return await proxy.forward(
            request,
            state["pclient"],  # type: ignore[arg-type]
            runner.base_url,
            runner.key,
            path,
            replaced_reason=runner.replaced_reason,
            serve_csp=cfg.files_serve_csp,
        )
