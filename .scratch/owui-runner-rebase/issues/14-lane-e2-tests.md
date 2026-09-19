# 14 — Lane E-impl: tests for rebase + orientation

Type: task
Status: resolved
Blocked by: 10, 11, 12, 13

## Question

Extend the suite per brief §1.5 + tickets 04/05: L3-T1..T6 shim tests (external
≤2s + explanation + 126; internal pass-through; `-x` fail; pip/npm green; apt
blocked), cross-render consistency (env ↔ AGENTS.md), seed survives
teardown/recreate + fresh-volume reseed, zero-egress suite green on the new
image, `cap_drop ALL` still effective, `docker history` shows no unpinned
`latest`, README "What the agent sees" grep-matches actual env, and the
opencode absence assert (binary no longer in the image).

## Answer
Implemented in commit 8f2b894..8f2b89a + fixups; full suite green 2026-09-19; pushed (2211d91). Follow-up: ticket 16 (flaky timeout race).
