# 17 — Live migration of .101 to the rebased stack + non-expiring admin key

Type: task
Status: resolved
Blocked by: —

## Question

Move the LIVE stack on the OWUI LXC (192.168.138.101) to the rebased images and
orientation layer, and retire the expiring admin JWT (2026-10-16 outage risk).

## Answer

**Done 2026-09-19, stakeholder-authorized (SSH + docker + restart-if-needed).**

Token fix:
- `auth.enable_api_keys` was false in the OWUI config DB; set true (DB backup
  `webui.db.bak-20260919` first; OWUI restarted ~40s).
- Non-expiring admin API key minted via `POST /api/v1/auths/api_key` (each call
  rotates; final key captured on .101, stored in Infisical as
  `OWUI_ADMIN_API_KEY`), verified against `/api/v1/users/{id}` (200).
- Live `.env` `OWUI_ADMIN_TOKEN=` now carries that API key (backup
  `.env.bak-20260919`).

Migration:
- New images built here (N11 buildkit path; context fix: build from the
  Dockerfile's own dir), shipped by `docker save|scp|load` (243 MB, 21 s).
- Tree synced to `/opt/owui-runner-orchestrator` with `--exclude .env* data/`
  (compose diff already validated: ORCH_BIND=0.0.0.0 preserved).
- Cutover: retag `:migration`→`:dev`, `docker compose up -d orchestrator`.
- **N28 (live find): the ZenDiS Nix base symlinks /etc/passwd and /etc/group
  into /nix/store → runc rejects every exec ("path escapes from parent"),
  killing docker exec AND the healthcheck (container showed "unhealthy" with
  a fully working API).** Fixed in orchestrator/Dockerfile (dereference to
  real files as root); 930b101. After redeploy: healthy + exec OK.

Live verification (all measured, post-cutover):
- `/_orch/healthz` ok; `/_orch/status` sane (budget, seam).
- OWUI verify probe `/api/config` → 200 (with K1).
- Cold spawn + `/execute` as OWUI would (K1 + X-User-Id from the NEW key):
  exit 0, ran as `user` in `/home/user`.
- Orientation: `/home/user/AGENTS.md` seeded; 3 `SANDBOX_*` vars in env;
  external curl → explanation + rc=126 in 46 ms; `PIP_INDEX_URL` on pip-shim.
- Persistence: file written pre-teardown survived DELETE + respawn.
- OWUI terminal connections intact: `lxc101-terminal` + `orch-lxc64`
  (→ `http://orchestrator:8080`), both enabled — the DB-write approach
  (N23/N24 era) survived the restart.
- Cleanup: tarballs removed both boxes; stray migration tags removed.
