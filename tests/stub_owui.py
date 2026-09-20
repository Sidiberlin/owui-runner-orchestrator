"""Minimal stand-in for the OWUI admin API.

Mirrors the real contract from open-webui/backend/open_webui/routers/users.py:

    GET /api/v1/users/{user_id}     Depends(get_admin_user)
    -> UserActiveResponse: UserModel fields (incl. `role`) + groups + is_active
    unknown user -> 400 (NOT 404), matching OWUI's USER_NOT_FOUND

    GET /api/v1/groups/             Depends(get_admin_user)
    -> list[{id, name, ...}], the full OWUI group roster (ticket 04,
    docs/adr/0012 seam 6). UNVERIFIED against OWUI source -- no vendored copy
    of open-webui's admin group-list route exists in this repo, unlike the
    per-user endpoint above -- this is app.roles.RoleMapper's own documented
    assumption about the response shape, mirrored here so the same stub
    exercises it. Returns the three sample groups every other route on this
    stub already hands out (_DEVS, _QA, _OPS), so "known to OWUI" here means
    "one of those three" -- ticket 08's unknown-mapped-group status field
    needs a group name deliberately absent from BOTH this list and every
    uid's own membership below to have anything to report.

Roles are resolved by prefix so every test can use a unique uid and never
collide with another test's runner:

    u-<anything>  -> user        a-<anything>  -> admin
    p-<anything>  -> pending     x-<anything>  -> auditor (an unknown role)

The fixed names alice / adam / pat / weird are kept for manual poking.

Group membership (ticket 02, docs/adr/0012 "group names not ids") is chosen
by a uid *substring*, independent of role, so a single test can pick a shape
without perturbing the role-prefix convention above:

    nogroups     -> []                                (ungrouped)
    multigroup   -> devs + qa                          (several groups)
    messygroups  -> devs, qa, plus malformed entries mixed in (parser
                    tolerance: missing id, missing name, non-dict)
    withgroups   -> devs                                (used to prove a
                    denied role stays denied even while it carries a group)
    opsgroup     -> ops                                  (ticket 05: a group
                    ONLY a uid containing this substring ever carries, so
                    env.test's GROUP_MAP=ops:heavy mapping cannot perturb any
                    other test's users -- they all keep resolving to "devs"
                    or no group, neither of which GROUP_MAP maps)

Anything else keeps the pre-ticket-02 default: plain `user`-role accounts
carry the sample "devs" group, everyone else carries none.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.getenv("STUB_TOKEN", "stub-admin-token")
PORT = int(os.getenv("STUB_PORT", "8099"))

FIXED = {"alice": "user", "adam": "admin", "pat": "pending", "weird": "auditor"}
PREFIX = {"u-": "user", "a-": "admin", "p-": "pending", "x-": "auditor"}

_DEVS = {"id": "g-devs", "name": "devs"}
_QA = {"id": "g-qa", "name": "qa"}
_OPS = {"id": "g-ops", "name": "ops"}


def role_for(uid: str) -> str | None:
    if uid in FIXED:
        return FIXED[uid]
    for pre, role in PREFIX.items():
        if uid.startswith(pre):
            return role
    return None


def groups_for(uid: str, role: str) -> list:
    if "nogroups" in uid:
        return []
    if "multigroup" in uid:
        return [_DEVS, _QA]
    if "messygroups" in uid:
        return [
            _DEVS,
            {"name": "no-id"},        # missing id -> skipped
            {"id": "g-no-name"},      # missing name -> skipped
            "not-a-dict",             # non-dict entry -> skipped
            _QA,
        ]
    if "withgroups" in uid:
        return [_DEVS]
    if "opsgroup" in uid:
        return [_OPS]
    return [_DEVS] if role == "user" else []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._send(401, {"detail": "Not authenticated"})
        if self.path.rstrip("/") == "/api/v1/groups":
            return self._send(200, [_DEVS, _QA, _OPS])
        if not self.path.startswith("/api/v1/users/"):
            return self._send(404, {"detail": "no route"})
        uid = self.path.rsplit("/", 1)[-1]
        role = role_for(uid)
        if role is None:
            # OWUI answers 400 for USER_NOT_FOUND, not 404.
            return self._send(400, {"detail": "User not found"})
        self._send(200, {
            "id": uid,
            "email": f"{uid}@example.test",
            "name": uid,
            "role": role,
            "groups": groups_for(uid, role),
            "is_active": True,
        })


ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
