# 11 — Lane D'': compose helpers on ZenDiS coreutils

Type: task
Status: resolved
Blocked by: —

## Question

Swap every `busybox:1.36` helper in `docker-compose.yml` (devguard cache/vulndb
init, retention sweep, etc.) to `zendis/coreutils:main` (BusyBox 1.37, verified
M0), digest-pinned. Verify the `user: "0:0"` chown-init semantics behave
identically (coreutils default USER=53111, but compose overrides). Record digests.

Detail: brief §1.6; M0 evidence `/root/.planning/user-briefs/m0-zends-probe.md`.

## Answer
Implemented in commit 3603204 (night shift), suite-verified, pushed 2026-09-19 (2211d91).
