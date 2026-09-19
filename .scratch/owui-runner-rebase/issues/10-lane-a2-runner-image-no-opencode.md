# 10 — Lane A'': runner image without opencode

Type: task
Status: resolved
Blocked by: —

## Question

Strip the opencode CLI from `runner/Dockerfile` (decided: dropped — unused by the
architecture, the OWUI chat model drives open-terminal directly). Remove the
`opencode` stage, `OPENCODE_VERSION`/`OPEN_TERMINAL_REF=ghcr.io/anomalyco/opencode`
args and any copies from it. Keep: `open-terminal:slim` base (R-C, M0 evidence),
Node 22.14.0 stage (dev toolchain for user work — NOT harness-related), the
entrypoint semantics, uid-1000 layout, N8 caps, N10 `WORKDIR /home/user`.
Target: smaller image, one less supply-chain pin to audit.

Detail: brief §1.3 (as amended by this map's D1/opencode decisions).

## Answer
Implemented in commit 8703003 (night shift), suite-verified, pushed 2026-09-19 (2211d91).
