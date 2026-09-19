# 06: Per-profile egress stance through spawn env and orientation

**What to build:** Per-profile egress. As an operator, I want each profile to
carry its own egress stance so that an evaluation group can be stricter than the
rest of the fleet without changing global env. As the driving agent, I want the
sandbox environment variables and the prose orientation in the workspace to
describe the stance of the runner I am actually in, and to agree with each other,
so that I never waste a session assuming a strictness that does not apply. The
stance rides the existing spawn-env plumbing: the shims read it at runtime, so
they stay deployment-wide binaries and are not touched. A stance is an
explanation to the agent, not a hole in the topology — zero egress still holds
by effect for every profile.

**Blocked by:** 05 (Spawn integration — resources, image and exec timeout)

**Status:** ready-for-agent

- [ ] Resolved egress stance is injected at runner creation as spawn env.
- [ ] The orientation renderer emits the environment channel and the prose
      channel from the resolved stance, remaining a single source of truth.
- [ ] No file under `runner/shims/` and no image definition is modified.
- [ ] The strict stance is byte-identical to today's, verified against the
      ticket 01 baseline.
- [ ] Zero-egress behaviour continues to hold by effect for every profile
      (prior art: `tests/integration/test_egress.py`).
- [ ] The two orientation channels are asserted consistent per profile (prior
      art: `tests/integration/test_orientation.py`,
      `tests/unit/test_orientation_renderer.py`).
- [ ] No changes to `runner/Dockerfile`, `runner/shims/*`, or
      `THIRD-PARTY-NOTICES.md`.
- [ ] Ticket 01 guard still green; full suite green; committed.
