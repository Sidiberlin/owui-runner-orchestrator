"""Per-runner Open Terminal key derivation (N1).

WHY DERIVED AND NOT STORED
    The orchestrator's routing map lives in memory and dies with the process.
    Label-based reconciliation (A4) adopts surviving runners after a restart,
    but an adopted runner is useless if we cannot authenticate to it. Storing
    keys on disk just moves the problem and adds a secret at rest.

REFINEMENT TO N1 AS WRITTEN
    v1.2/N1 specified HMAC(secret, uid || container_id). The container id does
    not exist until *after* create, but the key must be injected as env *at*
    create time — a chicken-and-egg. Instead we mint a random nonce, record it
    in an immutable container label, and derive from that:

        nonce  = 32 random hex chars           (fresh on every spawn)
        key    = HMAC-SHA256(master, uid:nonce)

    The nonce is readable via `docker inspect` on adoption, so the key is fully
    recomputable after any restart, and it rotates on every respawn. The master
    secret never leaves the orchestrator.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets


def mint_nonce() -> str:
    return secrets.token_hex(16)


def derive_key(master_secret: str, uid: str, nonce: str) -> str:
    return hmac.new(
        master_secret.encode("utf-8"),
        f"{uid}:{nonce}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
