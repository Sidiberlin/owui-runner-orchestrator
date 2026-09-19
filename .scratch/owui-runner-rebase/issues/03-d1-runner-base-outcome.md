# 03 — D1: runner base outcome (R-A / R-B / R-C)

Type: grilling
Status: resolved
Blocked by: —

## Question

Which runner base outcome does the M0 evidence support and the stakeholder choose:
R-A (ZenDiS image directly capable of hosting the agent toolchain), R-B (ZenDiS
hybrid: zends base + copied toolchain layers), or R-C (fallback: keep
open-terminal:slim as the runner runtime, move everything else to ZenDiS bases)?

## Answer

**Decision: R-C full** (stakeholder, 2026-09-18, on the completed M0 evidence).

- **R-A and R-B are dead on measurement**: the ZenDiS images are Nix-built
  (stdlib under /nix/store), ship no bash/git/curl/apt/pip, `ensurepip` fails,
  and the Nix store layout breaks dynamic linking of copied-in binaries —
  no workable path to an agent-workspace toolchain on those bases.
- **R-C full**: runner keeps `open-terminal:slim` (M0 evidence committed as the
  brief requires); ZenDiS adoption where it provably works:
  compose helpers → `zendis/coreutils:main` (BusyBox 1.37, verified),
  orchestrator image → `zendis/python3:3.13-main` via the verified
  venv+get-pip bootstrap, GATED on a serve-smoke + full suite green
  (failure = informed fallback to R-C minimal, never silent).
- During the D1 discussion the stakeholder clarified the architecture: the OWUI
  chat model is the driving agent; open-terminal is a plain HTTP terminal API,
  not a harness; the opencode CLI in the image is an unused leftover.
  **opencode: DROPPED from the runner image** (own decision record in ticket 10;
  D2 becomes moot and is marked superseded in ticket 01).
- Implementation tickets graduated: 10 (runner image w/o opencode) ∥
  11 (coreutils swap) ∥ 13 (orientation build) → 12 (orchestrator on zends
  python, gated) → 14 (tests) → 15 (publication).
