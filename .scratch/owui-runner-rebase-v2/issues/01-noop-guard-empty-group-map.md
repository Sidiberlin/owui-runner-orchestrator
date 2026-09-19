# 01: No-op guard — empty GROUP_MAP is byte-for-byte today

**What to build:** A named regression guard that proves this feature is
invisible when it is not configured. As an operator deploying v2.0 onto a live
fleet, I need to know that with no **GROUP_MAP** and no `POLICY_*` vars set, a
runner comes up exactly as it does today — not approximately. Written against
current `main` before any production change, so it captures real v1 behaviour
rather than the behaviour of a half-built feature. It is re-run by every later
ticket, and a failure in it blocks that ticket.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

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
- [ ] No changes to `runner/Dockerfile`, `runner/shims/*`, or
      `THIRD-PARTY-NOTICES.md`.
- [ ] Full suite green; committed on its own.
