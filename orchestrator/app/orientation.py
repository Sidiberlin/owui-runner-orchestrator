"""Agent orientation (Workstream L, tickets 04/05/13).

The driving agent is the LLM in the OWUI chat, not a process inside the
runner, so it never sees a stack trace or a man page from in here -- it only
sees whatever we put in its environment, its workspace, and its tool output.
Four independent channels, because any one alone loses to a stubborn model:

  1. Prose    -- AGENTS.md, seeded into the workspace (never auto-loaded).
  2. Data     -- SANDBOX_* env vars, injected at runner create.
  3. Enforcement -- unchanged: `internal: true` topology, no capabilities.
  4. Feedback -- the curl/wget/apt-get shims' explanation text (runner/shims).

`sandbox_services()` is the single source of truth for channels 1 and 2: the
env renderer and the AGENTS.md renderer both consume its output, so the two
can never list different services.

v2 (ADR-0012, ticket 06): both renderers also take the resolved profile's
egress stance as an explicit parameter, rather than the hardcoded "BLOCKED"
literal this module used through v1. Deliberately a caller-supplied value,
not something read back off `cfg` here -- the stance is per-request/per-
profile (config.Profile.egress), never a single global, and threading it as
a parameter is what keeps this module a pure function of its inputs rather
than needing to know about profile resolution at all. Passing
config.DEFAULT_EGRESS_STANCE reproduces the exact v1 behaviour every caller
had before this ticket.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

from .config import Config

log = logging.getLogger(__name__)

AGENTS_MD_PATH = "AGENTS.md"


@dataclass(frozen=True)
class SandboxService:
    name: str
    port: int
    description: str

    @property
    def hostport(self) -> str:
        return f"{self.name}:{self.port}"


def sandbox_services(cfg: Config) -> list[SandboxService]:
    """What a runner on THIS deployment can actually reach. Today that is
    DevGuard alone, and only once it is turned on (ADR-0008) -- `pip-shim`
    is deliberately absent here: it is pip plumbing reached automatically
    via PIP_INDEX_URL, not something an agent should curl directly."""
    if not cfg.devguard_enabled:
        return []
    return [
        SandboxService(
            "devguard-api", 8080,
            "package proxy: pip/npm packages, malware-checked",
        ),
    ]


def render_services_env(services: list[SandboxService]) -> str:
    """`name:port=description,name2:port2=description2` (ticket 04 Q2a).
    The shim parses this the same way: cut on `,`, then `=`, then `:`."""
    return ",".join(f"{s.hostport}={s.description}" for s in services)


def sandbox_env(cfg: Config, egress: str) -> dict[str, str]:
    """The data channel. Always present, even with an empty services list --
    an agent checking `env | grep SANDBOX` should never find nothing.

    SANDBOX_MODE stays the constant "air-gapped": that describes the
    TOPOLOGY (internal: true, no capabilities), which is single and
    unchanged for every profile in v2.0 (per-profile networks are out of
    scope). SANDBOX_EGRESS is the one value a profile actually varies --
    the shim's own fast-refuse-vs-real-attempt behaviour keys on it
    (runner/shims/sandbox-shim.sh), unmodified by this ticket."""
    return {
        "SANDBOX_MODE": "air-gapped",
        "SANDBOX_EGRESS": egress,
        "SANDBOX_INTERNAL_SERVICES": render_services_env(sandbox_services(cfg)),
    }


# English, factual, <=20 lines (ticket 04): models obey specifics, not
# lectures. The services line is the one part that varies by deployment;
# the egress-behaviour sentence is the other (ticket 06, ADR-0012) -- see
# _egress_note() for the exact wording per stance.
_AGENTS_MD_TEMPLATE = """\
# This machine

This runner is AIR-GAPPED BY DESIGN. It has no internet access, and that is
not a malfunction. Connection failures to external hosts are EXPECTED:
never retry them, never debug DNS, never suggest VPN/proxy/registry fixes.

Packages are served by an internal, malware-checked mirror that is already
configured. Just run `pip install <pkg>` / `npm install <pkg>` normally --
pip uses $PIP_INDEX_URL, npm uses $NPM_CONFIG_REGISTRY. Never point them
at public registries; it cannot work.

Internal services (machine-readable in $SANDBOX_INTERNAL_SERVICES):
{services}

curl, wget and apt-get work ONLY for internal services. Pointed at the
outside world they {egress_note}
Never use them against external URLs; never run `apt-get update`/`install`.

git works locally (init, commit, diff). Cloning from external hosts is
impossible -- if you need external code, say so in your reply instead of
trying to fetch it.

Check `env | grep SANDBOX` for the machine-readable facts about this machine.
"""


def _egress_note(egress: str) -> str:
    """The one sentence fragment that must stay honest about
    sandbox-shim.sh's actual per-stance timing (unmodified by this ticket):
    SANDBOX_EGRESS=BLOCKED refuses instantly, no network touched; any other
    value lets the real binary attempt for a couple of seconds first. Either
    way the call still always fails (exit 126) -- the network topology
    enforces that regardless of this env var (ticket 06: "a stance is an
    explanation to the agent, not a hole in the topology")."""
    if egress == "BLOCKED":
        return "print an explanation and fail instantly (exit 126), no network touched."
    return (
        "attempt for a couple of seconds, then print an explanation and "
        "fail (exit 126) -- there is no real route out either way."
    )


def render_agents_md(services: list[SandboxService], egress: str) -> str:
    body = (
        "\n".join(f"- {s.hostport} -- {s.description}" for s in services)
        if services else "- (none configured on this deployment)"
    )
    return _AGENTS_MD_TEMPLATE.format(services=body, egress_note=_egress_note(egress))


async def seed_agents_md(
    base_url: str, key: str, content: str, timeout: float = 10.0,
) -> None:
    """Write AGENTS.md into a freshly spawned runner's workspace, but ONLY
    if absent -- a user's own file (or their own project's AGENTS.md deeper
    in the tree) is never touched. There is no exec path into a runner (the
    socket proxy denies EXEC), so this goes through the runner's own Open
    Terminal API, exactly like any other file write a user's tool call would
    make. Best effort: this is a read-me-first artifact, not core function,
    so a failure here is logged and never blocks the spawn."""
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(
                f"{base_url}/files/read", headers=headers,
                params={"path": AGENTS_MD_PATH},
            )
            if r.status_code == 200:
                return
            w = await c.post(
                f"{base_url}/files/write", headers=headers,
                json={"path": AGENTS_MD_PATH, "content": content},
            )
            w.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - orientation is best-effort
        log.warning("could not seed AGENTS.md: %s", exc)


async def check_dns_drift(services: list[SandboxService]) -> list[str]:
    """Boot-time check (ticket 04 Q3c): do the configured names actually
    resolve on the runners network the orchestrator itself is attached to?
    Never fails startup -- a drifted name is a config problem to warn about,
    not a reason to refuse every runner."""
    loop = asyncio.get_event_loop()
    drifted: list[str] = []
    for s in services:
        try:
            await asyncio.wait_for(loop.getaddrinfo(s.name, s.port), timeout=3.0)
        except Exception:  # noqa: BLE001
            drifted.append(s.hostport)
    return drifted
