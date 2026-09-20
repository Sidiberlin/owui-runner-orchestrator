# How to create a policy profile

Give one Open WebUI group different runner limits — CPU, memory, timeouts,
image, egress stance — without touching code or redeploying anything besides
`.env`.

## Prerequisites

- A running orchestrator (see [Getting started](../tutorials/getting-started.md)).
- The name of an existing Open WebUI group you want to target (Admin → Users
  → Groups). You don't need to create it specially for this — any group
  works.
- Read access to `.env` on the orchestrator host.

## Steps

### 1. Pick a profile name and decide what it changes

A policy profile is a named bundle of exactly six settings:
`cpus`, `memory`, `idle_timeout`, `exec_timeout`, `image`, `egress`. You only
ever declare the fields that make this profile *different* — anything you
leave unset inherits the matching global knob (`RUNNER_CPUS`,
`RUNNER_MEMORY`, `IDLE_TIMEOUT`, `OPEN_TERMINAL_EXECUTE_TIMEOUT`,
`RUNNER_IMAGE`, and `BLOCKED` for egress) verbatim.

Pick any name except `default` — that name is reserved for the implicit
profile that equals today's global values, and declaring `POLICY_DEFAULT_*`
is a startup error.

### 2. Declare the profile's fields in `.env`

Each field is an env var named `POLICY_<NAME>_<FIELD>`. To give a `heavy`
profile more CPU and memory, leaving everything else at the global default:

```
POLICY_HEAVY_CPUS=4
POLICY_HEAVY_MEMORY=4g
```

`<NAME>` is matched case-insensitively (`POLICY_Heavy_CPUS` and
`POLICY_HEAVY_CPUS` are the same profile). `CPUS` accepts a plain number
(cores); `MEMORY` accepts a size string (`4g`, `512m`); `IDLE_TIMEOUT` and
`EXEC_TIMEOUT` accept duration strings (`30m`, `120s`, or a bare number of
seconds); `IMAGE` is an image tag; `EGRESS` is a free-form string that only
changes the sandbox shim's *retry timing* (see
[Explanation](../explanation/sandbox-and-spawn-time-binding.md)) — it is not
a real network permission and never has been, regardless of what value you
put here.

Any `POLICY_*` var whose suffix isn't one of those six fields is a startup
error, not a silent no-op — this catches a typo like `POLICY_HEAVY_CPU`
(missing the `S`) before it ships.

### 3. Map an OWUI group to the profile with `GROUP_MAP`

```
GROUP_MAP=data-science:heavy
```

`GROUP_MAP` is an ordered, comma-separated `groupname:profile` list.
Matching is **by group name, not ID** (readability over rename-stability —
see the caveat in Step 5), and it's **first-match-wins, left to right**: if a
user belongs to several mapped groups, they get whichever mapping entry
appears first in this list, not whichever group happens to be first on their
own account. A user in no group, an unmapped group, or a group this list
names that no longer matches any OWUI group, all fall back to the `default`
profile — mapping can never deny access, only tune resources; the role check
and the connection's access grants still decide who gets a runner at all
(see [How to entitle users](entitle-users.md)).

You can map several groups to the same or different profiles:

```
GROUP_MAP=data-science:heavy,interns:light
```

### 4. Restart the orchestrator

```bash
docker compose up -d orchestrator
```

Policy profiles are read from `.env` at process start, like every other
config knob — there's no live-reload.

### 5. Verify the resolved table

The boot log prints one line per profile with every field's *effective*
value after inheritance — read this instead of re-deriving it from the env
vars in your head:

```bash
docker compose logs orchestrator | grep 'policy profile'
```

```
policy profile default      cpus=1.50 memory=768MiB idle=1800s exec=120s image=owui-agent-runner:dev egress=BLOCKED
policy profile heavy        cpus=4.00 memory=4096MiB idle=1800s exec=120s image=owui-agent-runner:dev egress=BLOCKED
```

Or check it any time without reading logs, via the status endpoint (same
fields, plus `unknown_mapped_groups` — see Troubleshooting below):

```bash
K=$(grep ^ORCH_API_KEY= .env | cut -d= -f2)
curl -s -H "Authorization: Bearer $K" localhost:8080/_orch/status | python3 -m json.tool
```

Or per-runner, once someone in the mapped group has actually triggered a
spawn:

```bash
curl -s -H "Authorization: Bearer $K" localhost:8080/_orch/runners
```

Each entry's `profile` field shows what it was created under.

## Verification

A member of the mapped OWUI group who has **not yet had a runner spawned**
will get the new profile on their next request. **A profile change never
applies retroactively to an already-running runner** — it takes effect only
on that user's *next* spawn (after their current runner idles out or you
tear it down with `DELETE /_orch/runners/<uid>`). This is the same rule
role-derived limits already followed before policy profiles existed. See
[Explanation: spawn-time binding](../explanation/sandbox-and-spawn-time-binding.md)
for why.

To confirm end-to-end: have a member of the mapped group run
`env | grep SANDBOX` inside a chat, and check the CPU/memory limits Docker
actually applied:

```bash
docker inspect runner-<their-uid> --format '{{.HostConfig.NanoCpus}} {{.HostConfig.Memory}}'
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Startup fails with `POLICY_HEAVY_CPU is not a recognised policy field` | Typo in the field suffix | Check spelling against the six valid fields: `CPUS`, `MEMORY`, `IDLE_TIMEOUT`, `EXEC_TIMEOUT`, `IMAGE`, `EGRESS` |
| Startup fails with `profile name 'default' is reserved` | You declared `POLICY_DEFAULT_*` | Pick a different profile name; `default` always equals the global knobs verbatim |
| Startup fails with `GROUP_MAP maps group ... to undeclared profile ...` | `GROUP_MAP` references a profile name with no matching `POLICY_<NAME>_*` vars | Either declare that profile or fix the typo in `GROUP_MAP` |
| A user in the mapped group still gets `default` limits | Their runner was spawned *before* you added the mapping | Tear it down (`DELETE /_orch/runners/<uid>`) or wait for it to idle out, then have them trigger a fresh spawn |
| `/_orch/status`'s `unknown_mapped_groups` lists your group name | The OWUI group was renamed or deleted after you wrote `GROUP_MAP` | Update `GROUP_MAP` to match the group's current name, or recreate the group — matching is by name, not ID, so a rename silently demotes members to `default` until you fix this |

## Related

- [How to entitle users](entitle-users.md) — profiles tune resources; they don't grant access at all.
- [Reference: environment variables](../reference/environment-variables.md#policy-profiles-adr-0012) for the exact env var grammar.
- ADR-0012 in [`docs/adr/`](../adr/0012-group-policy-profiles.md) for the full design rationale.
- [Explanation: spawn-time binding](../explanation/sandbox-and-spawn-time-binding.md) for why changes aren't retroactive.
