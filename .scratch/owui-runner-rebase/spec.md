# Spec — OWUI Runner: hardened-base rebase, agent orientation, publication

Status: ready-for-agent
Source: wayfinder map `.scratch/owui-runner-rebase/` (decisions 01–09, all resolved),
briefs in `~/.planning/user-briefs/` (hardened-rebase brief §0 license facts are
VERIFIED — do not re-derive), M0 evidence `~/.planning/user-briefs/m0-zends-probe.md`.

## Problem Statement

The orchestrator platform works and is live (v1.6), but three things stand between
it and being a publishable, trustworthy alternative to the commercial Terminals
product: the runner image carries a coding-agent CLI nothing uses (leftover from
the project's confused origin), the driving agent (the LLM in the OWUI chat) gets
no help understanding that the runner's lack of internet is by design — so it
wastes sessions debugging "network problems" that cannot be fixed — and the repo
cannot legally/safely be made public yet (no license file, no third-party notices,
unreviewed history).

## Solution

Strip the unused CLI from the runner image; adopt the ZenDiS/opencode.de hardened
bases exactly where measurement proved them viable (compose helper images;
orchestrator image behind a serve-smoke gate); give the driving agent four
independent orientation channels (prose seed file, machine-readable env, topology
enforcement, self-explaining shim failures); and produce the complete publication
package. The runner runtime itself stays on the proven open-terminal:slim base —
that decision is measured, not provisional (M0: ZenDiS images are Nix-built with
no pip, broken ensurepip, no agent toolchain).

## User Stories

1. As the solo operator, I want the runner image free of unused tooling, so the
   image is smaller and its supply chain is fully auditable.
2. As the solo operator, I want every image reference in the stack pinned by
   digest where practical, so nothing drifts under me between rebuilds.
3. As the solo operator, I want the compose helper images to come from the
   ZenDiS hardened catalog, so maximum feasible share of the stack traces to
   opencode.de.
4. As the solo operator, I want the orchestrator image on the ZenDiS Python base
   if and only if the full test suite proves it there, so hardening never trades
   away verified function.
5. As the solo operator, I want the publication gates (LICENSE, notices,
   disclaimer, history scan) satisfied, so I can flip the repo public without
   legal or privacy risk.
6. As the solo operator, I want the aux services reachable from runners
   documented in one place, so adding an internal service later is a one-line
   change.
7. As a driving agent (LLM in the OWUI chat), I want external network failures
   to be fast and self-explanatory, so I stop retrying and start working within
   the sandbox.
8. As a driving agent, I want a machine-readable list of internal services in my
   environment, so I can route package installs and internal calls correctly.
9. As a driving agent, I want package installs to just work through the
   pre-configured internal mirror, so I never try public registries.
10. As a driving agent, I want a seed document in the workspace describing the
    sandbox rules, so I can read the ground truth if my harness surfaces it.
11. As an OWUI user, I want my files and agent state to survive runner teardown,
    unchanged from today, so the rebase is invisible to me.
12. As an OWUI user, I want zero regression in how fast runners spawn, so the
    hardening costs me nothing.
13. As a downstream self-hoster, I want the repo public with a clear license and
    third-party notices, so I can legally run and modify it.
14. As a downstream self-hoster, I want the README to explain the zero-egress
    design and the agent-orientation mechanism, so I can reproduce the setup.
15. As a future contributor, I want the tests to encode the sandbox guarantees
    (no egress, no cross-user reads, no fake shim output), so I cannot silently
    break the product's core promise.

## Implementation Decisions

- Runner base stays `open-terminal:slim` (D1 = R-C full). The Open Terminal
  server is the product surface OWUI drives; the image also carries the agent
  toolchain (bash/git/curl) that ZenDiS bases measurably lack.
- The opencode CLI is REMOVED from the runner image (dropped: the driving agent
  is the OWUI chat model; nothing invokes the CLI — verified). Node stage stays
  (user-work toolchain, not harness-related).
- Compose helpers move from busybox to `zendis/coreutils:main` (BusyBox 1.37,
  capability-verified), digest-pinned.
- Orchestrator image moves to `zendis/python3:3.13-main` behind a hard gate:
  venv + get-pip bootstrap (system pip is broken on the Nix base), then uvicorn
  serve-smoke + aiodocker import + full suite green in the new image. Gate
  failure = keep current base and record why; never ship unproven.
- Agent orientation, four channels (all decided in tickets 04/05):
  1. Prose: AGENTS.md seed (English, ≤20 lines, drafted in map assets) baked at
     `/opt/sandbox`, copied to the workspace root at startup only if absent.
     Nothing auto-loads it — it is a read-me-first artifact.
  2. Data: `SANDBOX_MODE`, `SANDBOX_EGRESS=BLOCKED`,
     `SANDBOX_INTERNAL_SERVICES` (comma-separated `name:port=description`),
     injected at runner create; every var present in compose AND env example
     exactly once (N15; fixes the recorded DevGuard double-definition wart that
     silently empties the pip index today).
  3. Enforcement: unchanged (`internal: true` topology; no capabilities added).
  4. Feedback: shims for curl/wget/apt-get in `/usr/local/bin` (outside the
     volume, PATH-first): allowlisted internal host:port passes through to the
     real binary; external targets fail per the hybrid rule — instant (<100 ms)
     with the explanation when `SANDBOX_EGRESS=BLOCKED` is set, else a ≤2 s
     real attempt wrapped with the same explanation; exit 126; NEVER fake
     output. No git shim (decided). `-x`/`--proxy` flags fail fast.
- Single renderer emits both the env list and the seed's service section from
  one config source; orchestrator boot DNS-checks listed names against the
  runners network, warns (never fails) on drift. `pip-shim` stays unlisted
  (plumbing, reached via PIP_INDEX_URL, not for direct agent use).
- Publication: MIT LICENSE (decided; artifact still to write),
  THIRD-PARTY-NOTICES.md with SPDX-valid ids and verbatim © lines (independent
  fresh-session review gate before commit), README license + disclaimer line,
  three audited doc placeholder fixes (two ADR IPs, one hostname), gitleaks
  history scan before any visibility flip.
- Clean-room rule unchanged: zero code or API shapes from the proprietary
  upstream orchestrator; MIT notices preserved for open-terminal, opencode
  (removed from image, still in notices for history/attribution if shipped
  anywhere), ZenDiS bases.

## Testing Decisions

- Existing 144-test suite is the regression floor; it must stay green through
  every lane. It runs against a real stack (own compose project) — treat suite
  green as the acceptance gate for each lane, not a follow-up.
- New tests: shim matrix (external ≤2 s + explanation + 126; internal
  pass-through real response; proxy-flag fast fail; pip/npm green through the
  mirror; apt blocked), cross-render consistency (every service in env appears
  in the seed and vice versa), seed survives teardown/recreate + reseeds on a
  fresh volume, zero-egress set green on the final image, runner still starts
  with the reduced capability set, no unpinned `latest` in the final refs,
  README env-documentation matches actual injected vars, and an assert that the
  removed CLI's binary is absent from the image.
- Tests only assert external behavior (HTTP responses, filesystem visibility,
  exit codes), never module internals — matching the existing suite's style.

## Out of Scope

- Runtime egress of any kind; egress-enablement knobs; per-runner networks;
  group permissions; TLS on the LAN hop; AppArmor profiles inside this LXC;
  prevention-based disk quotas; git history rewriting (unless the leak scan
  finds a live secret — rotate first, then rewrite as a separate decision).
- Building an OWUI-side UI beyond the native Open Terminal integration.
- Any fork of the proprietary upstream orchestrator (clean-room only).

## Further Notes

- Build mechanics on this host are non-obvious and documented in the repo
  README (AppArmor-blocked builders; use the unconfined BuildKit sidecar and
  its buildx remote driver). Compose profiles: the build service and the
  DevGuard platform live behind profiles; the test stack brings up its own
  project.
- The runner stack is LIVE for real users on the OWUI host (192.168.138.101).
  Testing happens in throwaway compose projects on this box; nothing in this
  effort may restart or reconfigure the live stack without an explicit
  stakeholder go — updating the live deployment is a morning-after decision,
  not part of the night shift.
- Attribution requirement: the seed file content and shim explanation text are
  user-facing words inside the sandbox; keep them factual and short. The seed
  must never promise capabilities the topology forbids (honesty precedence).
