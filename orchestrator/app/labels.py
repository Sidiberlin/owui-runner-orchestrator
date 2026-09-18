"""Container labels — the only durable state the orchestrator relies on (A4).

Everything needed to adopt a runner after an orchestrator restart is carried
here, so reconciliation never depends on in-memory state or a state file:

    uid      who it belongs to (the raw OWUI X-User-Id, unsanitised)
    nonce    key-derivation input (N1) — lets us re-derive the API key
    version  runner generation; a bump makes old runners reapable
"""
from __future__ import annotations

NS = "io.owui.runner"
UID = f"{NS}.uid"
NONCE = f"{NS}.key-nonce"
VERSION = f"{NS}.version"
CREATED = f"{NS}.created-at"
ROLE = f"{NS}.role"
# Which orchestrator owns this runner. Reconciliation filters on it so two
# deployments sharing a Docker host cannot adopt (and then reap) each other's
# containers. Found live: a test stack adopted the production runner and tore
# it down 60s later under its own shorter IDLE_TIMEOUT.
NETWORK = f"{NS}.network"

# Identifies anything this orchestrator owns, for list filters and reaping.
MANAGED = f"{NS}.managed"
MANAGED_VALUE = "1"


def build(uid: str, nonce: str, version: str, created_at: str,
          role: str = "user", network: str = "") -> dict[str, str]:
    return {
        MANAGED: MANAGED_VALUE,
        UID: uid,
        NONCE: nonce,
        VERSION: version,
        CREATED: created_at,
        # Carried so an adopted runner reports the role it was created under.
        # Without it, reconciliation silently relabels every runner "user",
        # which misleads an operator reading /_orch/runners after a restart.
        ROLE: role,
        NETWORK: network,
    }
