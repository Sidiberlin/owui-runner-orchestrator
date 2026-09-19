# 05: Spawn integration — resources, image and exec timeout per profile

**What to build:** The first user-visible effect. As a user in a mapped group, I
want my runner to start with my profile's cpus, memory, image and exec timeout,
so that the work I was granted more capacity for actually completes and a long
legitimate job is not cut off at the fleet default. As an operator, I want the
profile name written to the runner's durable labels so that a runner adopted
after an orchestrator restart still reports the profile it was created under,
instead of reconciliation quietly relabelling my fleet as default. A profile
change applies to the user's next runner and never mutates a live one.
Demoable by spawning two users in different groups and showing two genuinely
different containers.

**Blocked by:** 04 (GROUP_MAP parsing and resolution)

**Status:** ready-for-agent

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
- [ ] No changes to `runner/Dockerfile`, `runner/shims/*`, or
      `THIRD-PARTY-NOTICES.md`.
- [ ] Ticket 01 guard still green; full suite green; committed.
