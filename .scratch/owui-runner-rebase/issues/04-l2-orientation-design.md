# 04 — L2: orientation channels design (AGENTS.md + env + shim text)

Type: grilling
Status: resolved
Blocked by: 05

## Question

How do the four orientation channels get designed so an LLM in the runner treats
zero-egress as expected: what does the single renderer (L2) emit into env vars and
into the AGENTS.md seed, and what exactly do the curl/wget/apt-get shims (L3,
scope fixed by D5) print on a blocked call? What is the allowlist syntax
(`SANDBOX_INTERNAL_SERVICES` format) and the trust model (orchestrator-computed vs
static env)?

## Answer

Stakeholder accepted all recommended options (this session).

**Shim failure mode = hybrid (Q1c):**
- `SANDBOX_EGRESS=BLOCKED` set → instant fail (<100 ms): explanation to stderr,
  exit 126, no network attempt.
- Env absent (degraded spawn) → attempt the real connection with a 2 s budget
  (`--connect-timeout` for curl, `timeout 2` wrapper for wget/apt-get), then wrap
  the real failure with the same explanation. Success → pass through untouched
  (honesty preserved in every mode; never fake output — D5 precedence).

**Env syntax (Q2a):** one comma-separated var, `name:port=description`:
    SANDBOX_INTERNAL_SERVICES=devguard-api:8080=package proxy: pip/npm packages, malware-checked
Shim parses by cutting on `,` then `=` then `:` (POSIX-safe). The LLM reads the
same var as prose. Shims gate on destination host:port against this list; `-x`
/`--proxy` flags fail fast with the explanation.

**Trust model (Q3c):** the list is STATIC config (`.env`, compose passthrough at
create time — N15 habit: every var in BOTH files). The orchestrator DNS-checks
each listed name against the runners network at BOOT, warns (never fails) on
drift. Spawns stay config-driven, no socket-proxy round-trip in the hot path.

**Var set (graduated from fog):** `SANDBOX_MODE=air-gapped`,
`SANDBOX_EGRESS=BLOCKED`, `SANDBOX_INTERNAL_SERVICES=<list>`, plus existing
`PIP_INDEX_URL` / `NPM_CONFIG_REGISTRY` passthrough.

**Renderer:** one function in the orchestrator renders BOTH the env list AND the
AGENTS.md service section from the same config → they cannot drift. Services are
listed only when actually reachable for that runner (DEVGUARD_ENABLED decides).

**Measured default entry** (from docker-compose.yml, this session):
`devguard-api:8080` (alias on `runners`, health `GET /api/v1/health`) — the only
chokepoint with upstream. `pip-shim:8080` (ADR-0010 index rewriter) is
deliberately NOT listed: it is pip plumbing, reached automatically via
`PIP_INDEX_URL`; advertising it would invite direct curl use.

**AGENTS.md seed:** English only, ≤20 lines, baked at `/opt/sandbox/AGENTS.md.seed`,
copied to `$HOME/AGENTS.md` at startup only if absent (L1 shadowing rules).
Draft lives at `assets/AGENTS.md.seed-draft.md` beside this ticket; stakeholder
has seen the text in-chat.

**Wart found while grounding this design:** `.env.example` defines the DevGuard
block TWICE (a stale `PIP_INDEX_URL=http://devguard:3141/...` copy and the live
`PIP_INDEX_URL=` empty one; env last-wins → silently empty). Fix in the
implementation lane together with the N15 sweep (every config.py var present in
compose AND .env.example exactly once).

**Tests:** L3-T1..T6 from ticket 05, plus cross-render consistency (every service
in env appears in AGENTS.md and vice versa), AGENTS.md survives teardown/recreate,
re-seeded on fresh volume, README "What the agent sees" matches actual env (grep).
