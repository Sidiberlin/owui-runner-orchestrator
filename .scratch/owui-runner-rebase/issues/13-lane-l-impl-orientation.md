# 13 — Lane L-impl: orientation layer build

Type: task
Status: resolved
Blocked by: 10

## Question

Build the decided orientation design (tickets 04 + 05):
- single renderer → `SANDBOX_MODE` / `SANDBOX_EGRESS=BLOCKED` /
  `SANDBOX_INTERNAL_SERVICES` (create-time env, compose + `.env.example` both, N15);
- shims for curl/wget/apt-get in `/usr/local/bin` (hybrid mode: instant fail on
  env, attempt-then-wrap fallback, 2s budget, exit 126, never fake output);
- AGENTS.md seed from `assets/AGENTS.md.seed-draft.md` (see the ticket-04
  amendment: delivery channels are shim stderr + `/system` + OWUI-side system
  prompt; the seed is a cat-first artifact, nothing auto-loads it);
- boot-time DNS drift warning for listed services;
- fix the `.env.example` DevGuard double-definition wart (PIP_INDEX_URL silently
  empty today) in the same sweep.

## Answer
Implemented in commit 18d8080 (seed, env vars, shims, dedup fix), suite-verified, pushed 2026-09-19 (2211d91).
