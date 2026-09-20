# LIVE CUTOVER — v2.0 on .101 (2026-09-20)

Executed by Hermes (per runbook slot; CC correctly declined the live box).
Teardown first (stakeholder-authorized): main stack `down -v`, devguard
containers + images brute-cleared (their compose is parent-included, so a
subdir `down` cannot interpolate — noted for #3067 retirement scripting).
`open-webui` and `webui.db` untouched throughout. Tree synced by rsync
(minus `.env`, `.git`, data) — repo is private, so no git pull on .101.

## Findings during cutover

1. **Dialect change (v2)**: the orchestrator no longer exposes the v1
   `/v1/runners` surface. OWUI drives `/execute` (command is a STRING now),
   admin surface moved to `/_orch/*` (`status`, `healthz`, `runners`,
   `retention/sweep`). Runners speak open-terminal directly behind the proxy.
2. **`X-User-Id` required**: group resolution is per-request, so every call
   must carry the OWUI user id. Missing header → 400 with a shim that explains
   the admin-settings integration mistake in plain language.
3. **`OWUI_ADMIN_TOKEN` must hold a working credential** (config.py:435,
   roles.py:149). The legacy variable still contained the dead expiring JWT;
   v1 degraded, v2 refuses (503 "cannot verify your account"). Fixed by
   pointing the variable at the non-expiring API key. DOC DEBT: the variable
   name is now a misnomer — rename to `OWUI_ADMIN_CREDENTIAL` in v2.1 with a
   compat alias.
4. **pip is not on PATH** in runner shells; `python3 -m pip` works and shows
   the shim: index-url `http://pip-shim:8080/api/v1/dependency-proxy/pypi/simple`,
   trusted-host `pip-shim`. Orientation should teach `python3 -m pip`.

## E2E evidence (all against LIVE, admin uid 9f96309a…)

- `/execute` string-command: exit 0, `user` @ `/home/user`, streamed chunks ✓
- Egress: `curl https://example.com` → exit 126, "sandbox: curl →
  example.com blocked (no rout…" — instant, self-explaining ✓
- pip shim: index + trusted-host correct ✓
- Graceful DELETE → workspace survives respawn (`survive-me` read back) ✓
- `/_orch/status`: live/max runners, memory gate, workspace ceiling,
  devguard_enabled, package seam — all populated ✓
- Probe runner removed; stack left: orchestrator + socket-proxy healthy,
  zero stray runner containers, tarballs cleaned both sides ✓

## State after cutover

- .101 runs v2.0 orchestrator (`owui-orchestrator:dev` = 69dcb30 tree) and
  the unchanged runner image; remote `main` = local `main` (pushed).
- Follow-ups: `OWUI_ADMIN_CREDENTIAL` rename (v2.1); `#3067` watcher already
  armed (Mondays 09:00); OWUI-side groups can now be created and mapped via
  GROUP_MAP without another deploy.
