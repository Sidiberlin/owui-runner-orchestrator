# 16 — Follow-up: test_resources 60s timeout race

Type: task
Status: open
Blocked by: —

## Question

`tests/integration/test_resources.py` has a zero-margin 60s timeout race that
predates the rebase (surfaced during the night-shift suite runs, 2026-09-19;
flaky under host memory pressure, passes on retry). Widen the margin or make
the assertion duration-agnostic so the suite stops flip-flopping on a loaded
host. Found by CC night shift; recorded in NIGHT-REPORT.md.
