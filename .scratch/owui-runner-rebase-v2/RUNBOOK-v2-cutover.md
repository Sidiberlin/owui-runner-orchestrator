# Runbook — v2.0 group policy profiles live cutover

Ticket 10 (`.scratch/owui-runner-rebase-v2/issues/10-two-profile-rehearsal-stop-point.md`),
a STOP POINT. Everything below was rehearsed on a throwaway compose project
(`-p owui-rehearsal`) on **this** host, using a throwaway stub OWUI and a
fake OWUI network — never the live box (`192.168.138.101`), never the real
`.env`, never `open-webui_default`. No ssh, no live `.env` edit, no live
GROUP_MAP applied. This document is the runbook Hermes (or whoever performs
the live cutover) follows; the implementer does not touch the live host.

Companion files used to run the rehearsal (not applied anywhere live):
`.scratch/owui-runner-rebase-v2/rehearsal.env` (two profiles declared, a
populated GROUP_MAP) and `rehearsal-rollback.env` (identical except
`GROUP_MAP=`, for the rollback half). Both are throwaway secrets/config,
safe to keep or delete after this ticket lands.

## What was rehearsed

Two profiles: **`default`** (untouched globals: 1.5 cpu / 768 MiB / 90s idle
[shortened from the real fleet's 30m for observability] / 120s exec /
`BLOCKED` egress) and **`eval`** (`POLICY_EVAL_*`: 1 cpu / 384 MiB / 20s idle
/ 90s exec / `RELAXED` egress), mapped via
`GROUP_MAP=ops:eval,ghost-team:eval` — `ops` is a real group in the
rehearsal's stub OWUI; `ghost-team` deliberately is not, to rehearse the
unknown-group warning on the same build.

| Checklist item | Result |
|---|---|
| Boot table, both profiles | `policy profile default cpus=1.50 memory=768MiB idle=90s exec=120s image=owui-agent-runner:dev egress=BLOCKED` / `policy profile eval cpus=1.00 memory=384MiB idle=20s exec=90s image=owui-agent-runner:dev egress=RELAXED` — logged at boot, confirmed. |
| Unknown-group warning | `GROUP_MAP names group 'ghost-team', which Open WebUI's roster does not currently contain (renamed or deleted?); its members fall back to the default profile` — logged at boot (once the stub was reachable — see "one snag" below) and independently re-confirmed live via `GET /_orch/status`'s `unknown_mapped_groups: ["ghost-team"]`. |
| Per-runner profile from status | `GET /_orch/runners`: mapped user's row carried `"profile": "eval"`, unmapped user's carried `"profile": "default"`. `GET /_orch/status`'s `policy_profiles` mirrored the boot table exactly. |
| Two differing container configs | mapped user: `NanoCpus=1000000000 Memory=402653184`; unmapped user: `NanoCpus=1500000000 Memory=805306368` — confirmed via `docker inspect`, not just the API's own claim. |
| Differing egress stance | mapped user's container env: `SANDBOX_EGRESS=RELAXED`; unmapped user's: `SANDBOX_EGRESS=BLOCKED`. |
| Shorter-idle reclamation | Both spawned at the same instant; ~22s later the `eval` runner was torn down (`tearing down runner-u-opsgroup-idlefinal (idle 22s, no running work)`) while the `default` runner was still live and answering at 50s idle. |
| Restart adoption (profile + idle timeout preserved) | Same container `Id` before and after `docker restart` on the orchestrator; `io.owui.runner.profile` label read back `eval`, `io.owui.runner.idle-timeout` label read back `20.0` — reconciliation restored both, not just the role. |
| Empty-mapping no-op, same build | Swapped `rehearsal.env` → `rehearsal-rollback.env` (`GROUP_MAP=` blank, `POLICY_EVAL_*` left declared) and recreated the orchestrator container (`docker compose ... up -d orchestrator`, same image, no rebuild). Boot table still lists `eval` (declared, now unreferenced); `unknown_mapped_groups` is now `[]` (nothing to check — zero OWUI round trip, confirmed no `GET /api/v1/groups/` call in the log this time). |
| Rollback: live runner untouched | The `eval`-profile runner spawned *before* the rollback was left completely alone by the restart that applied it: same container `Id`, `profile` label still `eval`, `SANDBOX_EGRESS` still `RELAXED` — config only takes effect at the orchestrator's own restart, and even then only for reconciliation of *existing* containers (which restores what they already were), never a live mutation. |
| Rollback: next spawn for the same group | Explicitly tore down that same user's runner (`DELETE /_orch/runners/{uid}`) and respawned. The **same** OWUI user, same `ops` group membership, now got `profile: default`, `Memory=805306368`, `SANDBOX_EGRESS=BLOCKED` — proving the rollback takes effect on that user's *next* runner, exactly the rule a profile *change* already followed before rollback was ever in question. |

**Rollback note, stated plainly for the cutover:** removing (blanking)
`GROUP_MAP` alone is sufficient to restore v1 behaviour for every future
spawn — leaving `POLICY_<NAME>_*` profile declarations in `.env` is
harmless (they just become unreferenced entries, still visible in the boot
table and `/_orch/status`, selected by nobody). It takes effect at the next
orchestrator restart, for every user's *next* runner from that point on. A
runner already live when the rollback lands keeps whatever it was spawned
with until it is naturally reclaimed (idle) or manually torn down — it is
never retroactively mutated, in either direction (mapping in or mapping
out).

## One snag worth flagging (not a bug, a rehearsal-setup gotcha)

On the very first boot, the throwaway stub OWUI container had not started
yet (a manual sequencing issue in the rehearsal, not the compose file's
`depends_on` graph — the stub is not a compose service here, only a
one-off `docker run`), so the boot-time unknown-group check hit a DNS
failure and logged its documented best-effort skip
(`could not verify GROUP_MAP against OWUI's group roster ([Errno -2] Name
or service not known); skipping the unknown-group check for this boot`)
rather than the real warning. This is the designed fail-safe behaviour
(ticket 04), not a defect — but it's worth the live cutover starting OWUI
connectivity before (or well before) the orchestrator, so the boot-log
warning is meaningful on the first real boot rather than silently skipped.
If it does skip, `GET /_orch/status`'s `unknown_mapped_groups` (ticket 08)
is the live re-check that catches it moments later regardless.

## The exact env block for the live cutover

This is a **template** — the specific group name(s), profile name(s), and
values are the stakeholder's decision, not this rehearsal's. Structure only:

```
# Add one POLICY_<NAME>_<FIELD> block per profile. Every field left unset
# inherits the existing global knob (RUNNER_CPUS, RUNNER_MEMORY, etc.) —
# state only what should differ for this group.
POLICY_<NAME>_CPUS=<cpus, e.g. 4>
POLICY_<NAME>_MEMORY=<size, e.g. 4g>
POLICY_<NAME>_IDLE_TIMEOUT=<duration, e.g. 45m>
POLICY_<NAME>_EXEC_TIMEOUT=<duration, e.g. 10m>
POLICY_<NAME>_IMAGE=<image ref — every profile can share the same tag>
POLICY_<NAME>_EGRESS=<BLOCKED, or anything else for a less-strict shim stance>

# groupname:profile pairs, left to right, first match wins. Reference only
# profile names declared above with a POLICY_<NAME>_* block.
GROUP_MAP=<owui-group-name>:<NAME>,<owui-group-name-2>:<NAME>
```

`docker-compose.yml`'s orchestrator service already declares
`env_file: - ${ENV_FILE_NAME:-.env}` (landed ticket 05), so on the real
host — where `ENV_FILE_NAME` is unset — this resolves to the real `.env`
by default and **no docker-compose.yml edit is needed**: adding the block
above to `.env` and restarting the orchestrator is the entire cutover.

## Checks to run after applying it live

1. `docker compose logs orchestrator | tail -30` — confirm the boot table
   lists every declared profile with the values you expect, and confirm no
   unknown-mapped-group warning appears (or if one does, that it is
   expected — e.g. a genuinely stale entry you're about to clean up).
2. `curl -s $ORCH/_orch/status -H "Authorization: Bearer $ORCH_API_KEY"` —
   `policy_profiles` matches the boot table; `unknown_mapped_groups` is `[]`
   (or exactly the groups you already know are stale).
3. Have one real member of a newly-mapped group make one request, then
   `curl -s $ORCH/_orch/runners -H "Authorization: Bearer $ORCH_API_KEY"` —
   confirm their row's `profile` is the expected one, not `default`.
4. Confirm an UNMAPPED user (or an admin, if role-derived limits matter to
   you) still gets `profile: default` and their pre-cutover resource
   numbers — the no-op guarantee, checked against a real account instead of
   only trusting the test suite.
5. If rolling back is ever needed: blank `GROUP_MAP`, restart the
   orchestrator, re-run checks 1-2. See the rollback note above for what
   does and does not happen to already-live runners.

## What this ticket did NOT do

No ssh to `192.168.138.101`. No edit to the real `.env` (only the
rehearsal's own throwaway copies under `.scratch/owui-runner-rebase-v2/`).
No change to `open-webui_default` or any production Docker resource. No
production restart, of the orchestrator or anything else. The live cutover
itself is explicitly out of scope here — it belongs to Hermes, following
the steps above.
