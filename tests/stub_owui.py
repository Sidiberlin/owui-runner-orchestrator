"""Minimal stand-in for the OWUI admin API.

Mirrors the real contract from open-webui/backend/open_webui/routers/users.py:

    GET /api/v1/users/{user_id}     Depends(get_admin_user)
    -> UserActiveResponse: UserModel fields (incl. `role`) + groups + is_active
    unknown user -> 400 (NOT 404), matching OWUI's USER_NOT_FOUND

Roles are resolved by prefix so every test can use a unique uid and never
collide with another test's runner:

    u-<anything>  -> user        a-<anything>  -> admin
    p-<anything>  -> pending     x-<anything>  -> auditor (an unknown role)

The fixed names alice / adam / pat / weird are kept for manual poking.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.getenv("STUB_TOKEN", "stub-admin-token")

FIXED = {"alice": "user", "adam": "admin", "pat": "pending", "weird": "auditor"}
PREFIX = {"u-": "user", "a-": "admin", "p-": "pending", "x-": "auditor"}


def role_for(uid: str) -> str | None:
    if uid in FIXED:
        return FIXED[uid]
    for pre, role in PREFIX.items():
        if uid.startswith(pre):
            return role
    return None


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
            "groups": [{"id": "g-devs", "name": "devs"}] if role == "user" else [],
            "is_active": True,
        })


ThreadingHTTPServer(("0.0.0.0", 8099), H).serve_forever()
