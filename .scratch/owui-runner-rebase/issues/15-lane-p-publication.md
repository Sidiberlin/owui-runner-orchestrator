# 15 — Lane P: publication package

Type: task
Status: resolved
Blocked by: 14

## Question

Execute brief workstream P on the final image set (inventory AFTER lanes 10–13
change the refs): LICENSE file (MIT — decided, not yet written),
THIRD-PARTY-NOTICES.md with the independent-review gate (fresh session re-derives
every claim), gitleaks history scan (P3), placeholder fixes for the 3 audited
doc findings (ticket 09: two ADRs with the OWUI IP, one with `orch.lxc.`),
README license/disclaimer sections, then the P5 flip (both remotes same HEAD,
CI green, visibility public, render check). Fix `gh auth` (token invalid) before
any GitHub-side step.

## Answer
Staged 10b3b67; LICENSE ratified (Sidiberlin); notices independently reviewed 2026-09-19 (2 discrepancies fixed, 2211d91); gitleaks clean. Pushed. Remaining: the public flip itself (stakeholder go pending).
