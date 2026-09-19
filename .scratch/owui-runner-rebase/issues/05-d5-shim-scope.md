# 05 — D5: shim scope + trust model

Type: grilling
Status: resolved
Blocked by: —

## Question

Which external-facing commands get sandbox shims (curl/wget/apt-get only, or also
a git wrapper), and what is the shims' trust/allowlist model?

## Answer

**Decision: curl + wget + apt-get only. No git wrapper (too invasive; AGENTS.md
prose covers git; DNS-dead already fails fast).**

Stakeholder answers (this session):

- **Precedence — honesty wins**: shims must never fake output. Local allowlisted
  traffic passes through to the real binary; anything else → stderr explanation
  + exit 126. **Naked exit 126 with a terse message is acceptable** when
  necessary, but the preference is: attempt real connection, wrap failures with
  the explanation (connection error → explanation + 126; success → pass through
  untouched).
- **Explain-on-failure, not explain-always**: `curl example.com` ideally fails
  naturally by egress rules while the shim supplies the explanation; no
  blanket interception of every call.
- **Gate on destination, not name**: allowlist checks the target host:port
  (e.g. DevGuard proxy), not the command name. Syntax: `curl
  http://<host>:<port>/<path>` matches `SANDBOX_INTERNAL_SERVICES` entries;
  `-x/--proxy` flags fail fast.
- **Time budget: 2s** before the shim gives up and prints the explanation (ties
  into the ticket-04 question of whether `SANDBOX_EGRESS=BLOCKED` env could let
  shims skip the attempt entirely).
- **Pass-through list**: pip/npm/plain git need no shims.
- **Install location**: `/usr/local/bin` (real binaries are shadowed, PATH-first),
  outside the volume, baked into the image — survive teardown.
- **Tests defined (L3-T1..T6)**:
  - T1 external curl → ≤2s, explanation + 126;
  - T2 internal DevGuard URL → real response through shim;
  - T3 `-x` proxy attempt → fail fast with explanation;
  - T4 npm install → allowed (registry via mirror, no shim interference);
  - T5 pip install → allowed via internal index;
  - T6 apt-get update → explanation + 126.
- Open sub-question (goes to ticket 04): does the shim attempt-then-wrap, or is
  there a `SANDBOX_EGRESS=BLOCKED` env the shim checks to fail instantly without
  touching the network?

Blocked-by note resolved during the session: DevGuard's compose service names +
ports for the allowlist were read from `docker-compose.yml` directly (the
research ticket 06 was re-scoped to publication trackers only).
