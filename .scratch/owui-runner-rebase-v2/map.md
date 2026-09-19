# Map — v2.0 group policy profiles

## Destination

Per-profile tuning of runners, selected by **Groups (OWUI)**: a named **Policy
profile** bundles cpus, memory, idle timeout, exec timeout, image and egress
stance; **GROUP_MAP** maps group names to profiles in priority order, first
match wins. The access gate is unchanged — role check plus allowlist still
decide who may have a runner at all. Profiles tune; they never gate. No group,
unmapped group or renamed group gets the default profile, which is today's
global values verbatim, so a deployment with an empty **GROUP_MAP** is a
behavioural no-op.

## Documents

- Spec: `.scratch/owui-runner-rebase-v2/spec.md` (problem, solution, six seams,
  user stories, implementation/testing decisions, out of scope)
- Decision record: `docs/adr/0012-group-policy-profiles.md` (accepted, binding)
- Glossary: `CONTEXT.md` — Policy profile, GROUP_MAP, Groups (OWUI)
- Draft breakdown this was published from: `TICKETS-DRAFT.md`
- Tickets: `issues/01`–`issues/10`, dependency order

## Tickets

| # | Gist |
|---|------|
| 01 | No-op guard, written first against current `main`: empty GROUP_MAP spawns a byte-for-byte v1 runner. Test only. |
| 02 | Prefactor: carry OWUI group *names* on the resolved policy (already fetched, currently discarded). No behaviour change. |
| 03 | `POLICY_<NAME>_*` parsing, field inheritance, default profile ≡ today's globals, resolved table logged at boot. |
| 04 | `GROUP_MAP` parsing and pure resolution: priority order, unknown group warns and falls back, resolution can never deny. |
| 05 | Spawn integration: resolved cpus, memory, image and exec timeout applied at create; profile name in labels, restored on adoption. |
| 06 | Per-profile egress stance via spawn env; orientation's env and prose channels agree per profile. No shim changes. |
| 07 | Idle sweeper compares each runner against the timeout it was created under, surviving restart. |
| 08 | Status surface reports the resolved profile table and each live runner's profile, adopted runners included. |
| 09 | `.env.example` block, README profiles section with worked example and boot log, env-docs drift guard extended. |
| 10 | Two-profile rehearsal on a throwaway stack plus cutover runbook. STOP POINT: no live `.env`, no ssh to the live host. |

## Explicitly out of scope

Per-profile docker networks; runner image variant builds; groups as an access
gate; DB or YAML configuration; per-user overrides; the live cutover itself
(stakeholder's, after rehearsal).
