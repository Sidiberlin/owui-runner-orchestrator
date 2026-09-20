# Why runners can't reach the internet, why config changes wait for a respawn, and the `terminal:true` incident

Three design decisions that only make sense together: the sandbox has no
real internet access under any configuration, a policy or role change never
touches a runner that's already running, and one single boolean flag turned
out to control far more than its name suggested. This doc explains the
reasoning behind all three, and documents a real incident where getting the
third one wrong silently broke the feature end to end.

## The problem: an AI agent that can't tell "sandboxed" from "broken"

The thing driving tool calls inside a runner isn't a person who reads a
README — it's an LLM in an Open WebUI chat, and it never sees a stack trace,
a man page, or this repository from inside the container. All it sees is
whatever lands in its environment, its workspace, and its tool output. A
model that hits a dead network call and gets nothing but a generic
connection-refused error has no way to distinguish "this sandbox is
air-gapped by design" from "something is misconfigured," and left alone it
will burn a whole session debugging DNS, suggesting a proxy, or retrying a
call that can never succeed.

## The approach: enforce once, explain four times

Real enforcement is exactly one thing: the `runners` Docker network is
`internal: true` and no runner ever gets a second capability or a second
network attachment. `RunnerManager._assert_single_network` checks this at
spawn time and refuses to serve a runner that ends up attached to anything
else — this is the only layer that actually makes egress impossible, and
every runner has zero capabilities beyond the five explicitly added back
after `cap_drop: [ALL]` (none of which are network-related).

Everything else is explanation, aimed at the agent rather than at security:

1. **Data** — `SANDBOX_MODE`, `SANDBOX_EGRESS`, `SANDBOX_INTERNAL_SERVICES`
   env vars injected at create time (see
   [Reference: runner environment](../reference/runner-environment.md)).
2. **Prose** — `AGENTS.md`, seeded into the workspace on first spawn only if
   absent, spelling the same facts out in sentences.
3. **Enforcement** — the network topology itself, already covered above.
4. **Feedback** — `curl`/`wget`/`apt-get` shims in `/usr/local/bin`, ahead of
   the real binaries on `PATH` and outside the workspace volume (so they
   survive teardown and shadow the real thing for every session). An
   allowlisted internal `host:port` always gets the real binary's real
   response; anything else gets a real failure and a short, honest
   explanation on stderr, exit 126 — never a fake success, never mimicked
   output.

One renderer, `orchestrator/app/orientation.py:sandbox_services`, produces
both the env-var list and the `AGENTS.md` prose from the same source, so the
two channels can never disagree about what's reachable.

### `SANDBOX_EGRESS` is an explanation, not a permission

This is the one detail worth being explicit about, because a policy
profile's `EGRESS` field (ADR-0012) looks, at a glance, like a real access
control knob. It isn't. Setting `POLICY_HEAVY_EGRESS=ALLOWED` changes exactly
one thing: whether the shim refuses a call to an external host **instantly**
(`BLOCKED`) or makes a real attempt for up to two seconds before failing
the same way (anything else). Either way, the call still always fails,
because the network topology — the actual control — is identical for every
profile in this version. The field exists so an operator can tell an agent
"expect a slightly longer failure here" per group, not so an operator can
grant one group real internet access. Per-profile *networks* (which would be
a real access-control difference) are explicitly deferred, not implemented,
per ADR-0012's consequences section.

## Spawn-time binding: config changes apply to the *next* runner, never the current one

`RunnerManager.get_or_spawn` resolves CPU, memory, image, exec timeout, idle
timeout, and egress stance **once, at the moment a container is created**,
and burns them into that container's Docker config and a set of durable
labels. A role change, a `GROUP_MAP` edit, or a policy profile's field
change is picked up the next time `get_or_spawn` actually creates a new
container for that user — never by mutating a container that's already
running.

This is deliberate, not an oversight: Docker containers don't support live
resource-limit or environment changes without a restart anyway, and treating
"resolved once at create time, durable via labels" as the single rule means
an orchestrator restart can always reconstruct exactly what a running
container was promised (`reconcile()` reads the `profile`, `role`, and
`idle-timeout` labels back off each adopted container, rather than
re-deriving them from *current* config — an operator editing
`POLICY_HEAVY_IDLE_TIMEOUT` and restarting the orchestrator must not
retroactively change the timeout an already-running runner is reclaimed
under).

The practical consequence, verified live during the v2.0 QA pass: adding a
user to a `GROUP_MAP`-mapped OWUI group doesn't change anything about a
runner they already have. It changes what they get on their **next spawn**,
gated by two independent delays stacked on top of each other:

1. **Role-cache TTL** (`ROLE_CACHE_TTL`, default 60s) — how long the
   orchestrator trusts its last-known answer for that user's group
   membership before asking Open WebUI again.
2. **A fresh spawn** — the profile is only *applied* when a new container is
   actually created, so a user with a live runner sees no change at all
   until that runner is torn down (by idling out, or an operator's
   `DELETE /_orch/runners/<uid>`) and respawned.

The QA report measured this precisely: adding a user to a mapped group, then
tearing down and respawning, showed the new profile immediately. Removing
them, then respawning at +8 seconds, still showed the *old* profile (cache
hit); respawning again at +65 seconds — past the 60-second TTL — showed the
correct, updated profile. **This is documented, verified product behavior,
not a bug**, and it's why
[How to create a policy profile](../how-to/create-a-policy-profile.md) tells
you to force a teardown if you want a change to land immediately rather than
waiting for both delays to elapse naturally.

## The `terminal:true` incident: one flag, two meanings

`GET /api/config` answers Open WebUI's connection-discovery probe with a
`features` object, one field of which is `terminal`. The original design
computed it as `not proxy.is_denied("/api/terminals", denied)` — since
`/api/terminals` sits on the `PROXY_DENY_PREFIXES` denylist by design (the
WebSocket PTY pane is out of scope for this version), that expression always
evaluated to `false`. The reasoning at the time was narrow and, on its own
terms, correct: don't advertise a PTY affordance that would just 403 the
moment someone clicked it.

Live QA against the v2.0 deployment found that reasoning incomplete. Open
WebUI's chat model gates its **exec / `run_command` tool call** on this same
`terminal` flag — not just whether to render a PTY pane. A connection
advertising `terminal:false` made every chat-driven exec attempt fail
**client-side**, inside Open WebUI's own backend, before any HTTP request
ever reached the orchestrator: the access logs showed zero `/execute`
traffic for the failing calls, while an otherwise-identical connection
advertising `terminal:true` succeeded and logged normally with the same
model and user. That one flag, chosen to hide a pane, had silently disabled
the entire feature's real interaction path — including every one of ADR-0012's
`SANDBOX_EGRESS` profile checks, since none of them could be exercised
through the product at all.

**The fix is not "stop caring about the PTY pane."** It's recognizing that
the denylist and the discovery advertisement are two independent
enforcement points, and only one of them needed to change. `/api/terminals`
is still hard-blocked at the proxy layer in `proxy_to_runner()` regardless of
what `/api/config` advertises — that's a separate code path
(`proxy.denied_prefix`), exercised on every request except the unauthenticated
discovery probe itself, and covered by its own denylist test. So the fix —
advertise `terminal: true` unconditionally — restores the exec tool without
reopening the PTY: if Open WebUI ever does render a PTY-pane affordance from
this flag, opening it still 403s with the same Q5 explanation as before. Same
outcome the original design wanted, reached through the layer that actually
enforces it instead of the layer that only describes it.

The broader lesson, if you're ever tempted to derive a discovery/advertisement
value from an enforcement rule the way the original `terminal` field was: an
advertisement can be consumed by more than the one system you had in mind
when you wrote it. Enforce access control at the layer that actually serves
or refuses the request; be generous about what you advertise, unless the
advertisement itself is the security boundary.

## Related

- [Reference: runner environment](../reference/runner-environment.md) for the exact `SANDBOX_*` values and shim behavior described above.
- [Reference: `/_orch/*` endpoints](../reference/orch-endpoints.md#get-apiconfig--the-owui-discovery-probe) for the `/api/config` contract.
- [How to create a policy profile](../how-to/create-a-policy-profile.md) for the practical consequence of spawn-time binding.
- ADR-0001 (shared internal network), ADR-0005 (blocklist over allowlist), and ADR-0012 (group policy profiles) in [`docs/adr/`](../adr/).
- `.scratch/owui-runner-rebase-v2/QA-REPORT.md` for the full incident record this doc summarizes, including the live A/B test and the exact commit (`0947ca4`) that fixed it.
