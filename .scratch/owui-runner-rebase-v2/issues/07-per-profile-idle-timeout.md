# 07: Per-profile idle timeout honoured by the sweeper

**What to build:** The lifecycle half of the bundle. As a user in a mapped
group, I want my profile's idle timeout to govern my runner's teardown, so that
a workflow with long thinking pauses is not reclaimed underneath me. The idle
sweeper stops comparing every runner against one global timeout and compares
against the timeout that runner was created under, surviving an orchestrator
restart via the labels landed in ticket 05. Busy is still not idle, for every
profile. Demoable with two runners on different timeouts: the shorter one is
reclaimed, the longer one survives.

**Blocked by:** 05 (Spawn integration — resources, image and exec timeout)

**Status:** ready-for-agent

- [ ] Each runner carries the idle timeout it was created under; the sweeper
      compares against that value.
- [ ] The value survives orchestrator restart and runner adoption.
- [ ] Busy-is-not-idle behaviour is unchanged for every profile (prior art:
      `tests/integration/test_idle.py`).
- [ ] With no mapping configured, every runner uses the global timeout exactly
      as today.
- [ ] Timing assertions are margin-generous and duration-agnostic where possible
      (ticket 16 discipline).
- [ ] No changes to `runner/Dockerfile`, `runner/shims/*`, or
      `THIRD-PARTY-NOTICES.md`.
- [ ] Ticket 01 guard still green; full suite green; committed.
