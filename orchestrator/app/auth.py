"""Request authentication: K1 static key + trusted X-User-Id (the brief's model).

TRUST BOUNDARY — worth being explicit about, because it is unusual

    OWUI's backend proxies every request, so the browser never reaches us and
    no user JWT is ever forwarded. K1 is what proves "this came from OWUI";
    X-User-Id is then trusted *because* K1 was valid. That means anyone holding
    K1 can impersonate any user by setting a header. On a LAN with one operator
    that is the accepted deal (v1 auth decision), but it is exactly why K1 must
    never equal the OWUI admin token or any runner key, and why the runners
    network must not be able to reach a service that would hand K1 out.
"""
from __future__ import annotations

import hmac

from fastapi import HTTPException, Request

from .config import Config
from .roles import AccessDenied, Policy, RoleMapper, RoleUnavailable


def check_api_key(cfg: Config, authorization: str | None) -> None:
    expected = f"Bearer {cfg.orch_api_key}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(401, "invalid or missing API key")


async def authenticate(request: Request, cfg: Config, mapper: RoleMapper) -> Policy:
    check_api_key(cfg, request.headers.get("authorization"))
    uid = request.headers.get("x-user-id", "").strip()
    if not uid:
        raise HTTPException(
            400,
            "X-User-Id header missing. Open WebUI sends this on system-level "
            "connections; check that the integration is configured under Admin "
            "Settings rather than as a personal connection.",
        )
    try:
        return await mapper.resolve(uid)
    except AccessDenied as exc:
        raise HTTPException(403, str(exc)) from exc
    except RoleUnavailable as exc:
        # A8: fail closed. 503 is honest — this is our dependency failing, not
        # the user's fault, and it tells the agent to retry rather than give up.
        raise HTTPException(503, str(exc)) from exc
