# OWUI Runner Rebase — Wayfinder Map

Label: wayfinder:map
Effort: owui-runner-rebase

## Destination

The repo at `/root/owui-runner-orchestrator` is re-based onto ZenDiS/opencode.de
hardened images as far as measurement allows, LLMs driving runners reliably
understand their zero-egress sandbox (no "network bug" debugging loops), and the
repository is publishable (license package complete). Success = the success
criteria §7 of the hardened-rebase brief, each verified by the test suite, with
every D1–D5 decision recorded as a resolved ticket.

## Notes

- Read first, every session: `/root/.planning/user-briefs/owui-runner-hardened-rebase-brief.md` (the
  decided plan: workstreams R / L / P, license facts §0 are VERIFIED — do not re-derive)
  and the v1.0–v1.6 outcomes in `owui-runner-orchestrator-brief.md` (N-findings are law;
  do not re-litigate N1–N27 or Q1–Q7).
- Domain vocabulary: `/root/owui-runner-orchestrator/CONTEXT.md`; decisions: `docs/adr/`.
- Skills: grilling + domain-modeling for every HITL ticket; prototype only where a
  concrete artifact beats prose (L-orientation text is one); research for tracker/registry facts.
- M0 evidence (ZenDiS image capability probe): `/root/.planning/user-briefs/m0-zends-probe.md`
  — **COMPLETE** (every claim live-measured; R-A/R-B ruled out, venv+get-pip verified).
- Host constraints that are NOT re-decidable: LXC (no AppArmor profiles, no loop
  devices, monitor-and-enforce quotas stay), 7.6 GiB RAM with 3×768m budget (N13).
- Hard license constraints (§0.1–0.3): zero code from open-webui/terminals; MIT notices
  preserved; clean-room against the documented integration surface only.
- Do NOT silently pick R-C without M0 evidence. Do NOT revert N13 resource numbers.
- Ticket types: research = AFK, worked by a subagent in parallel; grilling = HITL with
  the stakeholder; task = AFK where the agent can drive it.

## Decisions so far

- [D2 — opencode CLI source](issues/01-d2-opencode-cli-source.md): pinned installer + sha256 verification, NOT a zends mirror — the registry runs GitLab, which cannot serve the release artifact the installer expects; sha256-pinned GitHub installer is the auditable supply chain.
- [D3 — LICENSE](issues/02-d3-license.md): MIT — **decision made, artifact NOT yet written** (an earlier "file written" claim here was retracted; LICENSE is a P2 deliverable).
- [D5 — shim scope](issues/05-d5-shim-scope.md): curl + wget + apt-get only (git wrapper rejected); shims live in `/usr/local/bin`, outside the volume, PATH-first; allowlist-driven pass-through, 2s budget, exit 126 with the 5-line explanation; tests L3-T1..T6 defined. *(NOTE: most L2/L3 detail landed via a batch whose subagent never ran; the design decisions were re-confirmed by the stakeholder in-chat and stand, but implementation files do not exist yet.)*
- [L2 orientation design](issues/04-l2-orientation-design.md): hybrid shim (env-gated instant fail, attempt-then-wrap fallback); `SANDBOX_INTERNAL_SERVICES` as comma-separated `name:port=description`; static config + orchestrator boot-time DNS drift warning; single renderer emits env + AGENTS.md service section; English-only ≤20-line AGENTS.md seed drafted (`assets/AGENTS.md.seed-draft.md`); `.env.example` DevGuard double-definition wart recorded for the impl lane.
- [D1 — runner base outcome](issues/03-d1-runner-base-outcome.md): **R-C full** — M0 proved R-A/R-B unworkable (Nix-built bases: no pip, broken ensurepip, no toolchain, no copied-binary linking); runner stays `open-terminal:slim`, ZenDiS adopted where verified (`coreutils:main` helpers; orchestrator on `python3:3.13-main` via venv+get-pip, serve-smoke-gated).
- [opencode CLI dropped](issues/10-lane-a2-runner-image-no-opencode.md): the OWUI chat model is the agent; open-terminal is a plain HTTP terminal API, not a harness; opencode was an unused leftover → stripped from the runner image (D2 moot, marked superseded in ticket 01).

## Not yet specified

— none: all fog graduated. Implementation tickets 10–15 carry the remaining work.

## Out of scope

- Anything sourced from `open-webui/terminals` (proprietary; §0.1 clean-room rule).
- Runtime egress of any kind; `OPEN_TERMINAL_ALLOWED_DOMAINS` stays unset (N9).
- Group-based permissions, per-runner networks (Q7), TLS on the LAN hop, AppArmor
  profiles inside this LXC (N5), loopback disk quotas (N4 — monitor-and-enforce stays).
- Git history rewriting unless P3 finds a live secret (P4 default: placeholders in docs,
  history untouched).
- Re-litigating N1–N27 / Q1–Q7 (v1.0–v1.6 review outcomes) or the N13 resource numbers.
