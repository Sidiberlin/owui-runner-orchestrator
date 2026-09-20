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


def _package_seam() -> dict:
    """Resolve the Package Seam: the single surface through which package
    traffic reaches runners (ADR-0008).

    Precedence is deliberate — an explicit value ALWAYS wins, so an operator
    can point at something other than DevGuard without editing code. Enabling
    DevGuard only supplies defaults.

    Both paths are now verified live against DevGuard v1.14.0 from a container
    on the runners network, with and without a trailing slash.

    npm WORKS: /api/v1/dependency-proxy/npm. It works despite DevGuard serving
    the packument verbatim, dist.tarball still pointing at
    registry.npmjs.org, and that host being unresolvable from a runner --
    because npm's own `replace-registry-host` default ("npmjs") rewrites the
    npmjs.org tarball host onto the configured registry, landing exactly on
    DevGuard's /npm/:package/-/* route. Setting replace-registry-host=never in
    a runner would therefore break installs; nothing sets it.

    pip needs a hop that npm does not, and the URL is not the reason. DevGuard
    passes PyPI's simple index through unrewritten (ProxyPyPISimple ->
    writeResponse, no rewriting on main either), so every link still points at
    files.pythonhosted.org, which a zero-egress runner cannot resolve; pip
    follows those links literally. So pip points at pip-shim (ADR-0010), which
    rewrites the links onto DevGuard's own pypi/packages route. Traffic still
    passes through devguard-api, so the firewall applies to index and download
    alike.

    DEVGUARD_BASE_URL therefore intentionally does NOT drive the pip default;
    PIP_SHIM_BASE_URL does. Point PIP_INDEX_URL straight at DevGuard and
    metadata will resolve while every download dies in DNS -- which is exactly
    how this looked before it was measured.
    """
    enabled = os.getenv("DEVGUARD_ENABLED", "false").strip().lower() in (
        "1", "true", "yes", "on")
    base = os.getenv("DEVGUARD_BASE_URL", "http://devguard-api:8080").rstrip("/")
    pip_base = os.getenv("PIP_SHIM_BASE_URL", "http://pip-shim:8080").rstrip("/")
    pip = os.getenv("PIP_INDEX_URL", "").strip()
    npm = os.getenv("NPM_CONFIG_REGISTRY", "").strip()
    host = os.getenv("PIP_TRUSTED_HOST", "").strip()
    if enabled:
        # pip goes through the shim; npm goes straight to DevGuard.
        pip = pip or f"{pip_base}/api/v1/dependency-proxy/pypi/simple"
        npm = npm or f"{base}/api/v1/dependency-proxy/npm"
        if not host:
            # Must match the host in PIP_INDEX_URL, not DevGuard's: pip
            # refuses a plain-http index unless the host it actually contacts
            # is trusted.
            host = pip.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    return {"pip_index_url": pip, "pip_trusted_host": host,
            "npm_registry": npm, "devguard_enabled": enabled}


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


# --- Policy profiles (ADR-0012, ticket 03) ----------------------------------
# The vocabulary only: POLICY_<NAME>_<FIELD> env vars parse into named
# Profile bundles. Nothing here selects a profile for a request (that is
# GROUP_MAP, ticket 04) or applies one to a container (ticket 05+); this
# module only builds the resolved table and lets main.py log it at boot.

DEFAULT_PROFILE_NAME = "default"
# Matches orientation.py's current hardcoded SANDBOX_EGRESS value verbatim,
# so the default profile's egress field is "today", not a new default.
DEFAULT_EGRESS_STANCE = "BLOCKED"

_PROFILE_FIELDS = ("CPUS", "MEMORY", "IDLE_TIMEOUT", "EXEC_TIMEOUT", "IMAGE", "EGRESS")


@dataclass(frozen=True)
class Profile:
    """A named bundle of runner settings (ADR-0012). Every field inherits the
    matching global default when its POLICY_<NAME>_<FIELD> var is unset, so
    the "default" profile (DEFAULT_PROFILE_NAME) is exactly today's global
    values -- nothing re-specified. Profiles tune; they never gate: this
    object carries no admission decision, that stays the role check's and
    the allowlist's alone.
    """
    name: str
    nano_cpus: int
    memory: int
    idle_timeout: float
    exec_timeout: float
    image: str
    egress: str


def _profile_fields_by_name(environ: dict) -> dict[str, dict[str, str]]:
    """Group POLICY_<NAME>_<FIELD> env vars by canonical profile name.

    Case rule: the <NAME> segment is matched case-insensitively and stored
    lower-cased, because GROUP_MAP (ticket 04) is free-form operator text
    while POLICY_* is a shell env var and conventionally upper-case -- a
    single lower-casing point here means a GROUP_MAP entry and a POLICY_*
    declaration never have to agree on casing convention to refer to the
    same profile. The FIELD suffix itself is matched upper-case only, same
    as every other env var this module reads.

    A POLICY_* var whose suffix does not match one of the six known fields
    is a startup error, not a silent ignore: this namespace is reserved for
    profile fields, so an unrecognised suffix is far more likely to be a
    typo (POLICY_HEAVY_CPU) than an intentional unrelated var, and a typo
    here would otherwise silently fall back to the global default -- exactly
    the failure mode this module exists to rule out.
    """
    by_name: dict[str, dict[str, str]] = {}
    for key, value in environ.items():
        if not key.startswith("POLICY_"):
            continue
        rest = key[len("POLICY_"):]
        field = next((f for f in _PROFILE_FIELDS if rest.endswith("_" + f)), None)
        if field is None:
            raise RuntimeError(
                f"{key} is not a recognised policy field; expected "
                f"POLICY_<NAME>_<FIELD> where FIELD is one of "
                f"{', '.join(_PROFILE_FIELDS)}"
            )
        name = rest[: -(len(field) + 1)]
        if not name:
            raise RuntimeError(f"{key} is missing a profile name")
        canonical = name.lower()
        if canonical == DEFAULT_PROFILE_NAME:
            raise RuntimeError(
                f"{key}: profile name {DEFAULT_PROFILE_NAME!r} is reserved "
                "for the implicit default profile (today's global values "
                "verbatim); declaring POLICY_DEFAULT_* would let it drift "
                "from today, which defeats the point of a default -- pick "
                "another name"
            )
        by_name.setdefault(canonical, {})[field] = value.strip()
    return by_name


def build_profiles(
    *,
    default_nano_cpus: int,
    default_memory: int,
    default_idle_timeout: float,
    default_exec_timeout: float,
    default_image: str,
    default_egress: str,
    environ: dict | None = None,
) -> dict[str, "Profile"]:
    """The resolved profile table: always contains DEFAULT_PROFILE_NAME
    (assembled from the passed-in global values, never from POLICY_DEFAULT_*
    -- see `_profile_fields_by_name`), plus one Profile per distinct name
    found in POLICY_<NAME>_<FIELD> vars, each field inheriting the matching
    global default when unset.
    """
    environ = os.environ if environ is None else environ
    profiles: dict[str, Profile] = {
        DEFAULT_PROFILE_NAME: Profile(
            DEFAULT_PROFILE_NAME, default_nano_cpus, default_memory,
            default_idle_timeout, default_exec_timeout, default_image,
            default_egress,
        )
    }
    for name, fields in _profile_fields_by_name(environ).items():
        try:
            nano_cpus = (
                int(float(fields["CPUS"]) * 1_000_000_000)
                if "CPUS" in fields else default_nano_cpus
            )
            memory = (
                parse_size(fields["MEMORY"])
                if "MEMORY" in fields else default_memory
            )
            idle_timeout = (
                parse_duration(fields["IDLE_TIMEOUT"])
                if "IDLE_TIMEOUT" in fields else default_idle_timeout
            )
            exec_timeout = (
                parse_duration(fields["EXEC_TIMEOUT"])
                if "EXEC_TIMEOUT" in fields else default_exec_timeout
            )
        except ValueError as exc:
            raise RuntimeError(f"policy profile {name!r}: {exc}") from exc

        image = fields.get("IMAGE", default_image)
        if "IMAGE" in fields and not image:
            raise RuntimeError(f"policy profile {name!r}: IMAGE is set but empty")
        egress = fields.get("EGRESS", default_egress)
        if "EGRESS" in fields and not egress:
            raise RuntimeError(f"policy profile {name!r}: EGRESS is set but empty")

        profiles[name] = Profile(
            name, nano_cpus, memory, idle_timeout, exec_timeout, image, egress,
        )
    return profiles


# --- GROUP_MAP (ADR-0012, ticket 04) -----------------------------------------
# The mapping: which OWUI group selects which already-declared Profile.
# Resolution never denies -- that stays the role check's and the allowlist's
# job alone; this module only ever returns a Profile.

def parse_group_map(
    raw: str, profiles: dict[str, Profile],
) -> tuple[tuple[str, str], ...]:
    """GROUP_MAP="group:profile,group2:profile2" -> an ordered
    ((group_name, profile_name), ...) tuple. Order is priority:
    `resolve_profile` returns the first entry whose group the caller belongs
    to. `profile_name` is looked up case-insensitively (lower-cased here) to
    match how POLICY_<NAME>_* profile names are stored; `group_name` is kept
    exactly as written and matched case-sensitively against OWUI's own group
    names in `resolve_profile` -- unlike a profile name (our own env-var-
    driven identifier), a GROUP_MAP group name is the operator's copy of a
    real OWUI display name and silently folding its case could match two
    OWUI groups that differ only by case as if they were one.

    A stray or trailing comma produces an empty entry, which is skipped, not
    an error -- the same tolerance `_csv()` already gives every other
    comma-separated knob. Everything else is loud: an entry with no `:`, an
    empty group or profile half, a group name repeated across entries (only
    the first occurrence could ever be reached, so a repeat is always a
    copy-paste mistake, never intentional), or a profile name `build_profiles`
    did not declare, all fail startup rather than silently doing something
    plausible-looking with a malformed line.
    """
    entries: list[tuple[str, str]] = []
    seen_groups: set[str] = set()
    for raw_entry in raw.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise RuntimeError(
                f"GROUP_MAP entry {entry!r} is missing ':profile' "
                "(expected group:profile)"
            )
        group, _, profile_name = entry.partition(":")
        group = group.strip()
        profile_name = profile_name.strip().lower()
        if not group:
            raise RuntimeError(f"GROUP_MAP entry {entry!r} has an empty group name")
        if not profile_name:
            raise RuntimeError(f"GROUP_MAP entry {entry!r} has an empty profile name")
        if group in seen_groups:
            raise RuntimeError(
                f"GROUP_MAP names group {group!r} more than once; only the "
                "first entry for a group is ever reachable (first match "
                "wins), so a repeat is always a mistake"
            )
        if profile_name not in profiles:
            raise RuntimeError(
                f"GROUP_MAP maps group {group!r} to undeclared profile "
                f"{profile_name!r} (declared profiles: "
                f"{', '.join(sorted(profiles))})"
            )
        seen_groups.add(group)
        entries.append((group, profile_name))
    return tuple(entries)


def resolve_profile(
    caller_groups: tuple[str, ...] | list[str],
    group_map: tuple[tuple[str, str], ...],
    profiles: dict[str, Profile],
) -> Profile:
    """Pure. The first `group_map` entry (left to right) whose group the
    caller belongs to wins; no group, an unmapped group, and a renamed
    (no-longer-matching) group all fall back to `profiles[DEFAULT_PROFILE_
    NAME]`. Can never deny: this always returns a Profile, never raises for
    a caller that matches nothing -- denial is the role check's and the
    allowlist's job alone, and profiles only ever tune.

    Assumes `profiles` was built by `build_profiles` (so DEFAULT_PROFILE_NAME
    is present) and `group_map` was built by `parse_group_map` against that
    same `profiles` (so every referenced profile name already exists) --
    both true for every Config built via `Config.from_env()`.
    """
    caller = set(caller_groups)
    for group, profile_name in group_map:
        if group in caller:
            return profiles[profile_name]
    return profiles[DEFAULT_PROFILE_NAME]


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
    retention_days: float = 0.0
    retention_sweep_interval: int = 3600
    idle_sweep_interval: float = 30.0

    # --- Open Terminal passthrough (C6) -----------------------------------
    ot_max_sessions: int = 8
    ot_execute_timeout: int = 120
    ot_session_cwd_ttl: int = 604800
    # --- Package Seam (ADR-0008) -------------------------------------------
    pip_index_url: str = ""
    pip_trusted_host: str = ""
    npm_registry: str = ""
    devguard_enabled: bool = False

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

    # --- policy profiles (ADR-0012, the v2 group-tuning vocabulary) --------
    # Always contains at least DEFAULT_PROFILE_NAME. Empty only for a Config
    # built by hand (tests) rather than via from_env().
    profiles: dict[str, Profile] = field(default_factory=dict)
    # Ordered (group_name, profile_name) pairs, priority left to right.
    # Empty is a behavioural no-op: resolve_profile always falls back to
    # DEFAULT_PROFILE_NAME with nothing to match against.
    group_map: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_env(cls) -> "Config":
        # Hoisted (rather than inlined below, like every other field) because
        # the policy-profile default table is assembled from these same
        # parsed values -- "default" must be these globals verbatim, not a
        # second, possibly-drifted read of the same env vars.
        runner_image = os.getenv("RUNNER_IMAGE", "owui-agent-runner:dev")
        runner_nano_cpus = int(_float("RUNNER_CPUS", 1.5) * 1_000_000_000)
        runner_memory = parse_size(os.getenv("RUNNER_MEMORY", "1g"))
        idle_timeout = parse_duration(os.getenv("IDLE_TIMEOUT", "30m"))
        ot_execute_timeout = _int("OPEN_TERMINAL_EXECUTE_TIMEOUT", 120)

        profiles = build_profiles(
            default_nano_cpus=runner_nano_cpus,
            default_memory=runner_memory,
            default_idle_timeout=idle_timeout,
            default_exec_timeout=float(ot_execute_timeout),
            default_image=runner_image,
            default_egress=DEFAULT_EGRESS_STANCE,
        )
        group_map = parse_group_map(os.getenv("GROUP_MAP", ""), profiles)

        return cls(
            orch_api_key=_req("ORCH_API_KEY"),
            master_secret=_req("ORCH_MASTER_SECRET"),
            owui_base_url=_req("OWUI_BASE_URL").rstrip("/"),
            owui_admin_token=_req("OWUI_ADMIN_TOKEN"),
            role_cache_ttl=_int("ROLE_CACHE_TTL", 60),
            role_cache_grace=_int("ROLE_CACHE_GRACE", 600),
            owui_api_timeout=_float("OWUI_API_TIMEOUT", 5.0),
            runner_image=runner_image,
            runners_network=os.getenv("RUNNERS_NETWORK", "owui-runners-internal"),
            runner_nano_cpus=runner_nano_cpus,
            runner_memory=runner_memory,
            runner_pids=_int("RUNNER_PIDS", 256),
            max_containers=_int("MAX_CONTAINERS", 6),
            idle_timeout=idle_timeout,
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
            # 0 disables deletion entirely. Defaulting a data-destroying policy
            # to OFF is deliberate: it must be an explicit operator choice.
            retention_days=_float("VOLUME_RETENTION_DAYS", 0.0),
            retention_sweep_interval=_int("RETENTION_SWEEP_INTERVAL", 3600),
            idle_sweep_interval=_float("IDLE_SWEEP_INTERVAL", 30.0),
            ot_max_sessions=_int("OPEN_TERMINAL_MAX_SESSIONS", 8),
            ot_execute_timeout=ot_execute_timeout,
            ot_session_cwd_ttl=_int("OPEN_TERMINAL_SESSION_CWD_TTL", 604800),
            **_package_seam(),
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
            profiles=profiles,
            group_map=group_map,
        )
