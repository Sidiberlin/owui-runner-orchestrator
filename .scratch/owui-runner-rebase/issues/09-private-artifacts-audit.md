# 09 — Private artifacts audit for publication

Type: task
Status: resolved
Blocked by: —

## Question

Before the visibility flip: what private/stakeholder-identifying material is in
the REPO TREE (not history — history is P3 gitleaks, out of scope here), and what
private material exists OUTSIDE the repo (planning dir, homelab IPs in docs) that
P4 must decide on?

## Answer

**Resolved 2026-09-18 (tracked-file audit, `git grep -I -n -E '<patterns>'`).**

Exclusions applied (upstream rules files, clearly NOT our data — would pollute
every future re-run): `docs/upstream/*` (DevGuard upstream rules), `devguard/rules/**/passenger_lists/*.csv`.

**In the tracked tree — 3 findings, all in docs/**, none in code/env/configs:

1. `docs/adr/0004-home-is-the-volume.md` — one RFC1918 IP `192.168.138.101`
   (OWUI LAN IP) in a documented probe command.
2. `docs/adr/0006-single-lxc-consolidation.md` — same OWUI IP, twice, in
   live-ops evidence.
3. `docs/adr/0008-package-seam.md` — homelab DNS name `orch.lxc.` used in
   example URLs.

**Out of the repo (external, for P4 awareness):**
`/root/.planning/` holds a session JWT (OWUI admin, exp 2026-10-16) and private
briefs — outside every git tree, no repo action needed; never paste into the repo.

**Recommended fixes (P4 = placeholders, docs only, history untouched):**
- ADR-0004: `192.168.138.101` → `<owui-host>` (matches README style, which is
  already placeholder-ized).
- ADR-0006: two occurrences → `<owui-host>` / `<runner-host>` as the prose fits.
- ADR-0008: `orch.lxc.` → `<orch-host>` in the two example URLs.
All three files are prose-only changes; no code paths reference these literals.

**CORRECTION (ticket 15, this session): these three findings do NOT reproduce.**
Checked `git log` for all three ADR files — one commit each, ever
(`f593686`), and neither the current tree nor that commit's content contains
`192.168.138.101` or `orch.lxc.` anywhere. This audit's specific
file/string claims were wrong (same failure class ticket 02's LICENSE
overclaim and ticket 08's independent-review gate exist to catch).

A fresh audit this session (`git ls-files | grep -lE
'192\.168\.|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2[0-9]|3[01])\.\d+\.\d+|\.lxc\b'`)
found the actual remaining instance in **README.md**, not the ADRs: the
literal connection id `orch-lxc64` (7 occurrences) and `lxc101-terminal` (2
occurrences) in the "Live OWUI integration" / "Live operation" sections —
both reveal real LXC container numbers from the live homelab. `<owui-host>`
and `<orch-host>` were already placeholder-ized there (commit `b2738f7`);
these two ID strings were missed. Fixed this session:
`orch-lxc64` → `<orch-connection-id>`, `lxc101-terminal` →
`<other-terminal-id>`, throughout README.md.

`tests/integration/test_egress.py`'s RFC1918 addresses
(`192.168.1.101`, `192.168.0.1`, `10.0.0.1`) are intentionally-unreachable
test fixtures proving egress is blocked, not real deployment details -
left as-is.
