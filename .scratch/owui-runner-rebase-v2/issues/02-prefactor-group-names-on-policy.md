# 02: Prefactor — carry OWUI group names on the resolved policy

**What to build:** The one prefactor the feature needs, landed alone so that
nothing else is in the blast radius. **Groups (OWUI)** membership already
arrives on the call the orchestrator makes for its role check, as id/name pairs,
and the code keeps only the ids — but the locked decision is to match by group
name. As the operator, I want the names recovered with no extra Open WebUI round
trip and no change in what any user experiences, so the feature that follows can
match on readable config.

**Blocked by:** 01 (No-op guard)

**Status:** ready-for-agent

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
- [ ] No changes to `runner/Dockerfile`, `runner/shims/*`, or
      `THIRD-PARTY-NOTICES.md`.
- [ ] Ticket 01 guard still green; full suite green; committed.
