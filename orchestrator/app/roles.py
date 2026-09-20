"""X-User-Id -> role -> policy (the brief's "single injection point").

ENDPOINT, VERIFIED AGAINST OWUI SOURCE (routers/users.py)

    GET {OWUI_BASE_URL}/api/v1/users/{user_id}     Depends(get_admin_user)

    Returns UserActiveResponse, which spreads UserModel and therefore carries
    `role` (declared `role: str = "pending"`), plus `groups: [{id, name}]` and
    `is_active`. Note it raises **400**, not 404, for an unknown user —
    treating 400 as "our request was malformed" would be wrong here.

    `groups` is already in the response. That is the v2 group-permissions hook
    the brief asked for: Policy below is the one place to widen, and nothing
    upstream of it needs to change.

    v2 prefactor (docs/adr/0012, "group names not ids"): Policy.groups now
    carries each group's *name* — the field GROUP_MAP will match against —
    and Policy.group_ids carries the same membership's ids alongside it, kept
    as the stable identifier for diagnostics. Both come from this same
    response; no extra OWUI round trip is introduced.

    v2 ticket 04 (GROUP_MAP resolution): Policy.profile now carries the
    resolved Policy profile (config.Profile) for these groups — first entry
    in cfg.group_map whose group the caller belongs to, default profile
    otherwise. Resolution is recomputed fresh on every call to `_policy()`
    (both the TTL-cache-hit branch and the fresh-fetch branch) rather than
    cached alongside role/groups: it is a pure, in-memory lookup against
    already-cached groups, so caching it separately would only add a second
    place it could go stale for no performance benefit. Still not applied to
    any container in this slice — that is ticket 05.

FAIL-CLOSED (A8)
    A role we cannot verify is not a role. On any OWUI failure we serve a
    cached answer for up to ROLE_CACHE_GRACE, then refuse with 503. We never
    fall open to "probably a user" — that would let a deleted or demoted
    account keep a runner.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx

from .config import Config, Profile, resolve_profile

log = logging.getLogger(__name__)

ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLE_PENDING = "pending"


class AccessDenied(RuntimeError):
    """Role resolved successfully and is not permitted (403)."""


class RoleUnavailable(RuntimeError):
    """Role could not be resolved and no usable cached answer exists (503)."""


def _parse_groups(raw: object) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """OWUI's `groups: [{id, name}]` -> (names, ids), same order, index-paired.

    Tolerant by construction, matching the pre-existing id-only parse this
    replaces: a non-dict entry, or a dict missing either `id` or `name`, is
    skipped rather than raising. A group entry is only as useful as its
    weakest field — an id we cannot match by name, or a name with no stable
    id behind it, is not worth carrying half of.
    """
    names: list[str] = []
    ids: list[str] = []
    for g in raw or []:
        if not isinstance(g, dict):
            continue
        gid, gname = g.get("id"), g.get("name")
        if not gid or not gname:
            continue
        ids.append(str(gid))
        names.append(str(gname))
    return tuple(names), tuple(ids)


@dataclass(frozen=True)
class Policy:
    """What this identity is allowed to have. Widen here for v2 groups."""
    uid: str
    role: str
    groups: tuple[str, ...] = ()       # group NAMES — the v2 GROUP_MAP match key
    group_ids: tuple[str, ...] = ()    # same membership's ids, for diagnostics
    # The resolved v2 Policy profile (config.Profile) for `groups`, or None
    # for a Policy built by hand (tests) rather than through RoleMapper,
    # which always resolves one. Not yet applied to any container (ticket 05).
    profile: Profile | None = None
    nano_cpus: int = 0
    memory: int = 0
    disk_soft: int = 0


@dataclass
class _Entry:
    role: str
    groups: tuple[str, ...]
    group_ids: tuple[str, ...]
    at: float


class RoleMapper:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._cache: dict[str, _Entry] = {}
        self._client = httpx.AsyncClient(
            base_url=cfg.owui_base_url,
            timeout=cfg.owui_api_timeout,
            headers={"Authorization": f"Bearer {cfg.owui_admin_token}"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _policy(self, uid: str, role: str, groups: tuple[str, ...],
                group_ids: tuple[str, ...]) -> Policy:
        profile = resolve_profile(groups, self.cfg.group_map, self.cfg.profiles)
        if role == ROLE_ADMIN:
            return Policy(
                uid, role, groups, group_ids, profile,
                nano_cpus=self.cfg.admin_nano_cpus,
                memory=self.cfg.admin_memory,
                disk_soft=self.cfg.admin_disk_soft,
            )
        return Policy(
            uid, role, groups, group_ids, profile,
            nano_cpus=self.cfg.runner_nano_cpus,
            memory=self.cfg.runner_memory,
            disk_soft=self.cfg.disk_soft,
        )

    async def _fetch(self, uid: str) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
        r = await self._client.get(f"/api/v1/users/{uid}")
        if r.status_code in (400, 404):
            # OWUI answers 400 for USER_NOT_FOUND. Authoritative "no such user".
            raise AccessDenied(f"unknown user {uid!r}")
        if r.status_code in (401, 403):
            # Our admin token is wrong or lost its privileges. This is a
            # misconfiguration, not a user problem — say so loudly.
            log.error(
                "OWUI rejected the orchestrator's admin token (%s). "
                "Check OWUI_ADMIN_TOKEN.", r.status_code,
            )
            raise RoleUnavailable("orchestrator admin token rejected by OWUI")
        r.raise_for_status()
        body = r.json()
        if not isinstance(body, dict):
            raise RoleUnavailable("unexpected OWUI response shape")
        role = str(body.get("role") or ROLE_PENDING).lower()
        groups, group_ids = _parse_groups(body.get("groups"))
        return role, groups, group_ids

    async def resolve(self, uid: str) -> Policy:
        now = time.time()
        cached = self._cache.get(uid)
        if cached and now - cached.at < self.cfg.role_cache_ttl:
            return self._gate(uid, cached.role, cached.groups, cached.group_ids)

        try:
            role, groups, group_ids = await self._fetch(uid)
        except AccessDenied:
            # Authoritative denial: drop any cached grant immediately so a
            # deleted account cannot ride out the grace window.
            self._cache.pop(uid, None)
            raise
        except (httpx.HTTPError, RoleUnavailable) as exc:
            if cached and now - cached.at < self.cfg.role_cache_grace:
                log.warning(
                    "OWUI unreachable (%s); serving %s's cached role for %.0fs more",
                    exc, uid, self.cfg.role_cache_grace - (now - cached.at),
                )
                return self._gate(uid, cached.role, cached.groups, cached.group_ids)
            log.error("OWUI unreachable (%s) and no usable cache for %s", exc, uid)
            raise RoleUnavailable(
                "cannot verify your account with Open WebUI right now"
            ) from exc

        self._cache[uid] = _Entry(role, groups, group_ids, now)
        return self._gate(uid, role, groups, group_ids)

    def _gate(self, uid: str, role: str, groups: tuple[str, ...],
              group_ids: tuple[str, ...]) -> Policy:
        if role == ROLE_PENDING:
            raise AccessDenied(
                "your Open WebUI account is still pending admin approval"
            )
        if role not in (ROLE_USER, ROLE_ADMIN):
            # Unknown future role: deny rather than guess. Adding a role is a
            # deliberate act, not something that should happen by omission.
            raise AccessDenied(f"role {role!r} is not permitted to use runners")
        return self._policy(uid, role, groups, group_ids)

    async def unknown_mapped_groups(self) -> list[str]:
        """GROUP_MAP group names OWUI's roster does not currently contain
        (ADR-0012 seam 6) -- a renamed or deleted OWUI group silently demotes
        its members to the default profile, and this is how that becomes
        visible at boot in seconds rather than as a mystery incident weeks
        later. Empty (nothing to warn about) when GROUP_MAP is unset, so an
        unconfigured deployment never pays for this extra OWUI round trip.

        Best-effort, like orientation.check_dns_drift: any failure to fetch
        or parse the roster is logged and answered as "nothing known to be
        wrong" ([]), never raised -- a roster the orchestrator cannot
        currently reach is a reason to skip the check, not to refuse every
        runner or produce a false unknown-group warning.

        UNVERIFIED against OWUI source: unlike GET /api/v1/users/{uid} above
        (checked against the vendored open-webui routers/users.py), there is
        no vendored copy of open-webui's admin group-list route in this repo
        to verify GET /api/v1/groups/'s exact response shape against. This
        assumes it returns a JSON list of objects each carrying a `name`
        field, matching Open WebUI's documented admin group management API.
        A wrong assumption fails safe: any unexpected shape or HTTP error
        already falls into the "return []" path above.
        """
        if not self.cfg.group_map:
            return []
        try:
            r = await self._client.get("/api/v1/groups/")
            r.raise_for_status()
            body = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning(
                "could not verify GROUP_MAP against OWUI's group roster (%s); "
                "skipping the unknown-group check for this boot", exc,
            )
            return []
        if not isinstance(body, list):
            log.warning(
                "could not verify GROUP_MAP against OWUI's group roster: "
                "unexpected response shape; skipping the unknown-group check"
            )
            return []
        known = {
            str(g["name"]) for g in body
            if isinstance(g, dict) and g.get("name")
        }
        mapped = {group for group, _ in self.cfg.group_map}
        return sorted(mapped - known)
