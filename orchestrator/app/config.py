"""Environment configuration. One place, parsed once, validated loudly.

Every knob here is documented in .env.example with the reasoning for the
non-obvious ones. Defaults match .env.example so a missing var never silently
changes behaviour relative to the documented config.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else default


def _req(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val:
        raise RuntimeError(f"{name} is required but unset")
    if val.startswith("CHANGEME"):
        raise RuntimeError(f"{name} still holds its .env.example placeholder")
    return val


def _csv(name: str, default: str) -> list[str]:
    raw = os.getenv(name, "").strip() or default
    return [p.strip() for p in raw.split(",") if p.strip()]


_SIZE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([kmgt]?)b?$", re.I)
_MULT = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}


def parse_size(text: str) -> int:
    """'1g' -> 1073741824. Accepts plain byte counts too."""
    m = _SIZE_RE.match(text.strip())
    if not m:
        raise ValueError(f"cannot parse size: {text!r}")
    return int(float(m.group(1)) * _MULT[m.group(2).lower()])


_DUR_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([smhd]?)$", re.I)
_DUR = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text: str) -> float:
    """'30m' -> 1800.0. Bare numbers are seconds."""
    m = _DUR_RE.match(text.strip())
    if not m:
        raise ValueError(f"cannot parse duration: {text!r}")
    return float(m.group(1)) * _DUR[m.group(2).lower()]


@dataclass(frozen=True)
class Config:
    # --- auth -----------------------------------------------------------
    orch_api_key: str
    master_secret: str
    owui_base_url: str
    owui_admin_token: str

    # --- role mapper (A8) ------------------------------------------------
    role_cache_ttl: int
    role_cache_grace: int
    owui_api_timeout: float

    # --- runner lifecycle -------------------------------------------------
    runner_image: str
    runners_network: str
    runner_nano_cpus: int
    runner_memory: int
    runner_pids: int
    max_containers: int
    idle_timeout: float
    runner_security_opt: list[str] = field(default_factory=list)
    runner_cap_add: list[str] = field(default_factory=list)

    # --- disk (N4) --------------------------------------------------------
    disk_soft: int = 0
    disk_hard: int = 0
    total_ceiling: int = 0
    disk_poll_interval: int = 60
    idle_sweep_interval: float = 30.0

    # --- Open Terminal passthrough (C6) -----------------------------------
    ot_max_sessions: int = 8
    ot_execute_timeout: int = 120
    ot_session_cwd_ttl: int = 604800
    pip_index_url: str = ""

    # --- plumbing ----------------------------------------------------------
    # --- per-role policy (the v2 group-permission injection point) ---------
    admin_nano_cpus: int = 0
    admin_memory: int = 0
    admin_disk_soft: int = 0
    # --- proxy -------------------------------------------------------------
    proxy_deny_prefixes: tuple[str, ...] = ()
    files_serve_csp: str = "sandbox"

    docker_host: str = "tcp://docker-socket-proxy:2375"
    docker_api_version: str = "v1.44"
    state_dir: str = "/data"
    runner_port: int = 8000
    # Memory to leave free on the host after admitting a runner (R3).
    memory_reserve: int = 512 * 1024**2
    memory_gate: bool = False
    memory_budget: int = 0
    runner_version: str = "1"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            orch_api_key=_req("ORCH_API_KEY"),
            master_secret=_req("ORCH_MASTER_SECRET"),
            owui_base_url=_req("OWUI_BASE_URL").rstrip("/"),
            owui_admin_token=_req("OWUI_ADMIN_TOKEN"),
            role_cache_ttl=_int("ROLE_CACHE_TTL", 60),
            role_cache_grace=_int("ROLE_CACHE_GRACE", 600),
            owui_api_timeout=_float("OWUI_API_TIMEOUT", 5.0),
            runner_image=os.getenv("RUNNER_IMAGE", "owui-agent-runner:dev"),
            runners_network=os.getenv("RUNNERS_NETWORK", "owui-runners-internal"),
            runner_nano_cpus=int(_float("RUNNER_CPUS", 1.5) * 1_000_000_000),
            runner_memory=parse_size(os.getenv("RUNNER_MEMORY", "1g")),
            runner_pids=_int("RUNNER_PIDS", 256),
            max_containers=_int("MAX_CONTAINERS", 6),
            idle_timeout=parse_duration(os.getenv("IDLE_TIMEOUT", "30m")),
            runner_security_opt=_csv(
                "RUNNER_SECURITY_OPT", "no-new-privileges,apparmor=unconfined"
            ),
            runner_cap_add=_csv(
                "RUNNER_CAP_ADD", "CHOWN,DAC_OVERRIDE,FOWNER,SETUID,SETGID"
            ),
            disk_soft=parse_size(os.getenv("RUNNER_DISK_SOFT", "5g")),
            disk_hard=parse_size(os.getenv("RUNNER_DISK_HARD", "6g")),
            total_ceiling=parse_size(os.getenv("WORKSPACE_TOTAL_CEILING", "60g")),
            disk_poll_interval=_int("DISK_POLL_INTERVAL", 60),
            idle_sweep_interval=_float("IDLE_SWEEP_INTERVAL", 30.0),
            ot_max_sessions=_int("OPEN_TERMINAL_MAX_SESSIONS", 8),
            ot_execute_timeout=_int("OPEN_TERMINAL_EXECUTE_TIMEOUT", 120),
            ot_session_cwd_ttl=_int("OPEN_TERMINAL_SESSION_CWD_TTL", 604800),
            pip_index_url=os.getenv("PIP_INDEX_URL", ""),
            # Admin limits default to the user limits, so "higher limits for
            # admin" is opt-in rather than an accidental capacity hole.
            admin_nano_cpus=int(
                _float("ADMIN_RUNNER_CPUS", _float("RUNNER_CPUS", 1.5)) * 1_000_000_000
            ),
            admin_memory=parse_size(
                os.getenv("ADMIN_RUNNER_MEMORY") or os.getenv("RUNNER_MEMORY", "768m")
            ),
            admin_disk_soft=parse_size(
                os.getenv("ADMIN_RUNNER_DISK_SOFT") or os.getenv("RUNNER_DISK_SOFT", "5g")
            ),
            proxy_deny_prefixes=tuple(
                _csv("PROXY_DENY_PREFIXES", "/proxy,/ports,/api/terminals")
            ),
            files_serve_csp=os.getenv("FILES_SERVE_CSP", "sandbox").strip(),
            docker_host=os.getenv("DOCKER_HOST", "tcp://docker-socket-proxy:2375"),
            docker_api_version=os.getenv("DOCKER_API_VERSION", "v1.44"),
            state_dir=os.getenv("STATE_DIR", "/data"),
            memory_reserve=parse_size(os.getenv("MEMORY_RESERVE", "512m")),
            memory_gate=os.getenv("MEMORY_GATE", "off").strip().lower()
            in ("1", "on", "true", "yes"),
            memory_budget=parse_size(os.getenv("RUNNER_MEMORY_BUDGET", "0"))
            if os.getenv("RUNNER_MEMORY_BUDGET", "").strip() else 0,
            runner_version=os.getenv("RUNNER_VERSION", "1"),
        )
