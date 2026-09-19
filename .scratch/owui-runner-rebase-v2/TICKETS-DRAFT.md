# Ticket breakdown (DRAFT — not published) — v2.0 group policy profiles

Source of truth: `.scratch/owui-runner-rebase-v2/spec.md`, `docs/adr/0012-group-policy-profiles.md`.
Status: draft for stakeholder review. Nothing here is started.

Slicing rules applied:

- Each ticket is a vertical slice: it lands parsing/behaviour/observability/tests
  together and is demoable on its own, without the next ticket existing.
- Each ticket is sized to one fresh context window: one seam, its tests, its
  commit.
- Out of bounds for every ticket: `runner/Dockerfile`, `runner/shims/*`,
  `THIRD-PARTY-NOTICES.md`.
- Full suite green is the gate inside each ticket, not a later cleanup.
- T1 deliberately precedes the prefactor: it is test-only, adds no production
  code, and therefore protects the prefactor as well as everything after it.

---

## T1 — No-op guard: empty GROUP_MAP is byte-for-byte today

**Blocked by:** —

**What it delivers:** A named regression guard, written against current
`main` before any production change, that captures a spawned runner's full
external configuration and asserts it field for field. It is green on today's
code, is re-run by every later ticket, and is the single test that enforces the
additive promise. Demoable as "here is the test that fails the moment this
feature stops being invisible".

- [ ] A guard test spawns a runner with no `GROUP_MAP` and no `POLICY_*` vars set
      and captures, from the Docker API and the runner's own environment: the
      complete env list, nano-cpus, memory, pids limit, image reference,
      security options, capabilities, network attachment, and the effective exec
      and idle timeouts.
- [ ] The captured set is asserted against an explicit expected baseline (no
      "compare to whatever the code produced" self-fulfilling assertion).
- [ ] The env comparison is exact — an added or renamed variable fails the test,
      not just a changed value.
- [ ] The guard also covers the admin path, so role-derived limits are pinned
      alongside user limits.
- [ ] Test is duration-agnostic where it touches timeouts (no zero-margin waits;
      follows the `test_resources.py` lesson from ticket 16).
- [ ] Guard is listed in `tests/README.md`'s table with the finding it protects.
- [ ] Full suite green; committed and pushed on its own.

---

## T2 — Prefactor: carry OWUI group names on the resolved policy

**Blocked by:** T1

**What it delivers:** The one prefactor the feature needs. The role mapper
already receives group id/name pairs on the call it makes for the role check but
keeps only ids; name matching needs names. This ticket changes what is carried
and nothing else — no profiles, no mapping, no behaviour change. Demoable by
showing a resolved identity's group names in the log/status where only ids (or
nothing) appeared before.

- [ ] The per-identity policy object carries the caller's group names.
- [ ] Group ids remain available (they are the stable identifier for diagnostics)
      unless review decides otherwise; if dropped, say so explicitly in the commit.
- [ ] No additional Open WebUI request is introduced — names come from the
      response already being fetched.
- [ ] Cache entries carry names, and the cached-answer path (grace window)
      returns them consistently with the fresh path.
- [ ] Malformed or partial group entries in the payload are skipped rather than
      raising, matching the existing tolerance of that parse.
- [ ] `tests/integration/test_roles.py` prior art extended: names resolve for a
      grouped user; an ungrouped user resolves to an empty set; fail-closed
      behaviour is unchanged.
- [ ] The OWUI stub reflects the group shape used by the tests.
- [ ] T1 guard still green; full suite green; committed and pushed.

---

## T3 — Profile parsing, default profile, resolved table at boot

**Blocked by:** T2

**What it delivers:** The vocabulary. `POLICY_<NAME>_*` vars parse into named
profiles; unset fields inherit global values; the default profile is the global
values verbatim. Boot prints the fully resolved profile table. No runner
behaviour changes yet — profiles exist and are visible. Demoable by booting with
two profiles declared and reading the table in the log.

- [ ] Profile fields parsed: cpus, memory, idle timeout, exec timeout, image,
      egress stance — using the existing size/duration helpers.
- [ ] Every unset field inherits the corresponding global value; the default
      profile equals today's globals with nothing re-specified.
- [ ] A malformed profile value fails startup loudly (prior art:
      `tests/unit/test_config.py`), never silently defaults.
- [ ] Profile names are case-normalised consistently between env var and mapping
      reference; the chosen rule is documented in the parser's docstring.
- [ ] Boot logs the fully resolved profile table, one line per profile, showing
      effective values after inheritance.
- [ ] Unit tests: inheritance, malformed size, malformed duration, unknown field
      ignored vs. rejected (state which, and why), default-profile identity with
      no `POLICY_*` vars set.
- [ ] T1 guard still green; full suite green; committed and pushed.

---

## T4 — GROUP_MAP parsing and resolution (pure, no spawn change)

**Blocked by:** T3

**What it delivers:** The mapping. `GROUP_MAP` parses into an ordered list;
resolution turns a caller's group names into a profile with first-match-wins
priority and default fallback. The resolved profile is attached to the identity's
policy object and logged per request, but is not yet applied to containers.
Demoable by showing three users (mapped, unmapped-group, no-group) resolving to
three expected profiles in the log while every runner still spawns identically.

- [ ] `GROUP_MAP="group:profile,..."` parses into an ordered structure; order is
      priority, first match wins.
- [ ] Whitespace, empty entries and duplicate group names handled explicitly;
      the duplicate rule is documented.
- [ ] A mapping entry naming an undeclared profile fails startup.
- [ ] A mapping entry naming a group OWUI does not know warns loudly at boot,
      and the user still resolves to the default profile.
- [ ] No group, unmapped group and renamed group all resolve to default; no
      resolution path can deny a request.
- [ ] Resolution is a pure function unit-tested without Docker or OWUI:
      priority order, multi-group users, empty mapping, unknown group.
- [ ] Integration check that admission is unaffected: a pending or unknown-role
      account in a mapped group is still refused (prior art:
      `tests/integration/test_roles.py`).
- [ ] T1 guard still green; full suite green; committed and pushed.

---

## T5 — Spawn integration: resources, image and exec timeout per profile

**Blocked by:** T4

**What it delivers:** The first user-visible effect. The resolved profile's
cpus, memory, image and exec timeout are applied at container creation, and the
profile name is written to the durable container labels so a restart-adopted
runner reports what it was created under. Demoable by spawning two users in
different groups and showing two genuinely different containers.

- [ ] Resolved cpus, memory and image applied at create; exec timeout lands in
      the runner's environment.
- [ ] Profile name written to container labels and restored by reconciliation
      after an orchestrator restart.
- [ ] Per-profile memory flows through existing Budget admission accounting: a
      generous profile is refused admission rather than overcommitting.
- [ ] A profile change affects the user's next runner only; a live runner is
      never mutated.
- [ ] Admin role-derived limits still behave as today when no profile matches.
- [ ] Integration tests (prior art: `tests/integration/test_resources.py`,
      `tests/integration/test_lifecycle.py`): two profiles produce two different
      container configurations, proven via the Docker API and by effect;
      adoption after restart preserves the profile; new assertions are
      duration-agnostic.
- [ ] T1 guard still green; full suite green; committed and pushed.

---

## T6 — Per-profile egress stance through spawn env and orientation

**Blocked by:** T5

**What it delivers:** Per-profile egress. The resolved stance is injected as
spawn environment and the orientation renderer is parameterised by it, so the
machine-readable channel and the prose channel agree per profile. No shim
change: the shims read their stance at runtime. Demoable by two runners on
different profiles reporting different stances while the strict one's egress
behaviour is unchanged.

- [ ] Resolved egress stance is injected at runner creation as spawn env.
- [ ] The orientation renderer emits the environment channel and the prose
      channel from the resolved stance, remaining a single source of truth.
- [ ] No file under `runner/shims/` and no image definition is modified.
- [ ] The strict stance is byte-identical to today's, verified against the T1
      baseline.
- [ ] Zero-egress behaviour continues to hold by effect for every profile
      (prior art: `tests/integration/test_egress.py`) — a stance is an
      explanation to the agent, not a hole in the topology.
- [ ] The two orientation channels are asserted consistent per profile (prior
      art: `tests/integration/test_orientation.py`,
      `tests/unit/test_orientation_renderer.py`).
- [ ] T1 guard still green; full suite green; committed and pushed.

---

## T7 — Per-profile idle timeout honoured by the sweeper

**Blocked by:** T5

**What it delivers:** The lifecycle half of the bundle. The idle sweeper stops
comparing every runner against one global timeout and uses the timeout the
runner was created under, surviving an orchestrator restart via the labels
landed in T5. Demoable by two runners with different idle timeouts, the shorter
one reclaimed while the longer one survives.

- [ ] Each runner carries the idle timeout it was created under; the sweeper
      compares against that value.
- [ ] The value survives orchestrator restart and runner adoption.
- [ ] Busy-is-not-idle behaviour is unchanged for every profile (prior art:
      `tests/integration/test_idle.py`).
- [ ] With no mapping configured, every runner uses the global timeout exactly
      as today.
- [ ] Timing assertions are margin-generous and duration-agnostic where possible
      (ticket 16 discipline).
- [ ] T1 guard still green; full suite green; committed and pushed.

---

## T8 — Observability: profile on the status surface

**Blocked by:** T5

**What it delivers:** The operator's answer to "did my mapping take effect?"
The status surface reports the resolved profile table and the profile name of
each live runner. Demoable by mapping a group, spawning, and reading the profile
back from status without exec-ing into anything.

- [ ] Status reports the resolved profile table with effective values.
- [ ] Status reports the profile name per live runner, including
      restart-adopted runners.
- [ ] Unknown mapped group names are surfaced in status, not only in the boot
      log.
- [ ] No secret or token is added to the status payload.
- [ ] With no mapping configured, the added fields report the default profile
      and nothing else changes in the payload's existing fields.
- [ ] Tests assert the response body, never internals.
- [ ] T1 guard still green; full suite green; committed and pushed.

---

## T9 — Config surface documentation

**Blocked by:** T3 (content complete after T8)

**What it delivers:** The convention, documented in the repo's existing style —
every var documented in the env example, a README section covering `GROUP_MAP`,
the `POLICY_*` convention, the first-match rule, the rename caveat and a sample
boot-log table — with the drift guard extended so the docs cannot silently
diverge from the parser. Demoable by diffing docs against a boot log.

- [ ] `.env.example` documents `GROUP_MAP` and the full `POLICY_<NAME>_*` block
      in the file's existing one-comment-per-var style.
- [ ] README gains a profiles section: what a profile is, how groups select one,
      first-match priority, default-equals-today, the group-rename caveat, and a
      worked two-profile example with its boot-log output.
- [ ] Glossary terms are used exactly as `CONTEXT.md` defines them: Policy
      profile, GROUP_MAP, Groups (OWUI).
- [ ] The env-documentation drift guard is extended to cover the profile
      convention (prior art: `tests/unit/test_readme_env_docs.py`).
- [ ] `tests/README.md` table lists the new tests and the findings they guard.
- [ ] T1 guard still green; full suite green; committed and pushed.

---

## T10 — Two-profile rehearsal on a throwaway stack (STOP POINT)

**Blocked by:** T6, T7, T8, T9

**What it delivers:** Evidence, not code. A full two-profile deployment
rehearsed end to end on a throwaway compose project — mapped user, unmapped
user, group-rename demotion, restart adoption — written up as the cutover
runbook the stakeholder follows on the live box. This ticket stops before the
live `.env`: the live cutover is the stakeholder's, not the implementer's.

- [ ] Rehearsal on a throwaway compose project with two declared profiles and a
      populated mapping; no production change of any kind.
- [ ] Captured evidence: boot table, unknown-group warning, per-runner profile
      from status, two differing container configurations, differing egress
      stance, shorter-idle reclamation, restart adoption.
- [ ] Empty-mapping rehearsal captured on the same build, showing the no-op.
- [ ] Rollback note: what removing `GROUP_MAP` restores, and when it takes
      effect for a live runner.
- [ ] Runbook written to `.scratch/owui-runner-rebase-v2/` with the exact env
      block to apply and the checks to run after.
- [ ] Explicit STOP: no ssh to the live host, no live `.env` edit.
- [ ] Full suite green on the final build; committed and pushed.

---

## Deliberately not tickets

Per-profile docker networks; runner image variant builds; groups as an access
gate; DB or YAML configuration; per-user overrides; the live cutover itself.
