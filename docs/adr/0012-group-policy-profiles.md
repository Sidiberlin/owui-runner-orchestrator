# 0012 — Group-selected policy profiles with per-profile egress

Date: 2026-09-19 (decided in grill-with-docs v2 round)
Status: accepted

## Context

Today every runner gets identical settings from global env (cpus, memory,
timeouts, image). The per-role `Policy` seam in `orchestrator/app/config.py`
(line ~159, marked "the v2 group-permission injection point") was reserved for
exactly this. Open WebUI's users-list payload carries each user's `group_ids`
directly, so group membership is available at request time with zero extra API
round-trips. The user wants per-group tuning of runner resources AND per-group
egress stance, while keeping the existing role + allowlist gate untouched.

## Decision

- **Profiles, not gates.** A `Policy profile` is a named bundle
  (cpus, memory, idle_timeout, exec_timeout, image, egress stance) defined by
  `POLICY_<NAME>_*` env vars. OWUI groups select a profile via
  `GROUP_MAP="groupname:profile,..."` (order = priority, first match wins).
  Access control stays exactly as today: role check + allowlist. A user with
  no group, or no mapped group, gets the default profile = today's global
  defaults. Nobody is locked out on deploy.
- **Group names, not IDs.** Config readability beats rename-stability; the
  boot log warns loudly on unknown group names so renames are discovered in
  seconds, not incidents.
- **Per-profile egress.** Each profile carries its own `SANDBOX_EGRESS` /
  shim configuration, applied as spawn-env at runner creation. Feasible
  without shim rework because the shims read `SANDBOX_EGRESS` at runtime:
  the per-profile value rides the same spawn-env plumbing as the other knobs.
  The shims themselves stay deployment-wide binaries.
- **All-env config.** No YAML, no DB. Matches the repo's existing config
  style; one more documented env convention, no new parser.
- **Image per profile.** The field exists from day one; every profile
  currently points at the same tag. Differentiation later needs no schema
  change.
- **Observability.** Boot logs the fully resolved profile table; unknown
  groups warn; `/status` reports the active profile per runner.

## Consequences

- Deploying with an empty `GROUP_MAP` must be a no-op — the orchestrator
  behaves byte-for-byte as v1 (guard test required).
- Group renames silently demote users to the default profile (mitigated by
  the boot warning and `/status` visibility).
- Per-profile egress means two profiles can have different shims
  strictness; incident analysis must check the runner's profile, not just
  global env.
- Compose stays single-network; per-profile docker networks are explicitly
  deferred (the trusted-circle threat model holds for v2.0).
