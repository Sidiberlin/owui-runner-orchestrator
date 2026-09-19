# 10: Two-profile rehearsal on a throwaway stack (STOP POINT)

**What to build:** Evidence, not code. As the operator, I want a full
two-profile deployment rehearsed end to end on a throwaway compose project —
mapped user, unmapped user, group-rename demotion, restart adoption, and the
empty-mapping no-op on the same build — written up as the runbook I follow on
the live box, so that the live cutover is a repetition of something I have
already seen work. This ticket stops before the live `.env`: the live cutover is
the stakeholder's, and the implementer does not touch the live host.

**Blocked by:** 06 (Per-profile egress), 07 (Per-profile idle timeout),
08 (Status surface), 09 (Config surface documentation)

**Status:** ready-for-agent

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
- [ ] No changes to `runner/Dockerfile`, `runner/shims/*`, or
      `THIRD-PARTY-NOTICES.md`.
- [ ] Full suite green on the final build; committed.
