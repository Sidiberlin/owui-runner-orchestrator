# Spec — v2.0 Group policy profiles

Status: draft-for-review (tickets NOT published; no implementation started)
Binding input: `docs/adr/0012-group-policy-profiles.md` (accepted),
`CONTEXT.md` glossary (**Policy profile**, **GROUP_MAP**, **Groups (OWUI)**),
night-shift brief `~/.planning/user-briefs/owui-runner-night-shift-v2.md`
(locked decisions + milestone sketch — input, not the final shape).

## Problem Statement

Every runner on the fleet is identical. CPU, memory, idle timeout, exec timeout,
image and egress stance all come from one set of global env vars, so the only
tuning an operator has is "change it for everybody". The single exception —
admins may get larger limits — is hardcoded as a role special case, which does
not generalise: the operator cannot give a trusted circle of users longer exec
timeouts for a batch job, cannot give an evaluation group a stricter egress
stance than the rest of the fleet, and cannot hand a heavy user more memory
without raising the ceiling for all forty accounts and blowing the Budget.

The information needed to do better is already in hand and costs nothing: Open
WebUI's admin user payload carries each account's **Groups (OWUI)** membership
in the same response the orchestrator already fetches for the role check, and
the per-identity policy object that role check produces was deliberately left
as the widening point for exactly this. What is missing is the vocabulary
(named bundles of settings), the mapping (which group selects which bundle),
and the plumbing that carries a resolved bundle from the authentication moment
through to container creation and teardown.

The risk that makes this delicate rather than trivial: this fleet is live for
real users. Any change to the spawn path can alter what every runner gets. So
the feature must be provably additive — with no mapping configured, the
orchestrator has to behave exactly as it does today, not approximately.

## Solution

Introduce the **Policy profile**: a named bundle of runner settings (cpus,
memory, idle timeout, exec timeout, image, egress stance) declared through
`POLICY_<NAME>_*` env vars. **GROUP_MAP** is an ordered `groupname:profile`
list; at request time the orchestrator resolves the caller's OWUI group names
against it left to right, first match wins, and the winning profile is applied
when that user's runner is created. A user in no group, in an unmapped group,
or in a group whose name no longer matches, gets the default profile — which is
defined to be today's exact global values. Access control does not move: the
role check and the allowlist still decide who may have a runner at all.
Profiles tune; they never gate. Nobody can be locked out by a profile change,
and a deployment with an empty **GROUP_MAP** is a behavioural no-op.

### Seams

Six seams carry this feature; nothing outside them changes.

1. **Config parsing.** The frozen config object gains the parsed profile table
   and the ordered group mapping, built with the same size/duration parsing
   helpers the global knobs already use. The default profile is assembled from
   the existing global values rather than from new defaults, so "default" and
   "today" cannot drift apart.
2. **Identity → policy resolution.** The object the role mapper returns for an
   identity is the documented v2 widening point and is where the resolved
   profile is attached. Two facts about the current implementation matter: it
   already fetches group membership on the same call as the role, and it
   currently keeps only group *ids* while the decision is to match by group
   *name* — the name is present in the payload but discarded. Carrying names is
   the one prefactor this feature needs.
3. **Spawn-time application.** The manager's spawn path already accepts a
   policy object and applies two of its fields (cpus, memory) to container
   creation. It widens to apply the whole resolved bundle: resources, image,
   the exec timeout that rides in the runner's environment, and the egress
   stance. Nothing about the spawn *sequence* changes; only the values do.
4. **Durable labels.** Container labels are the only state reconciliation
   trusts after an orchestrator restart, and the profile name joins them for
   the same reason the role did: an adopted runner must report the profile it
   was created under, not a guess.
5. **Orientation rendering.** The renderer that emits the sandbox environment
   and the agent-facing prose is currently a pure function of global config. It
   becomes a function of the resolved profile's egress stance, so the data
   channel and the prose channel stay consistent with each other and with the
   runner's actual strictness — one source of truth, as today.
6. **Lifecycle and reporting.** The idle sweeper compares each runner against a
   single global timeout; it must compare against the timeout the runner was
   created under. The status surface gains the resolved profile table and the
   per-runner profile name, and boot logs the fully resolved table plus a loud
   warning for every mapped group name that Open WebUI does not know.

## User Stories

### Operator / admin (fleet configuration)

1. As an operator, I want to declare a named policy profile with its own cpus,
   memory, idle timeout, exec timeout, image and egress stance, so that I can
   express "what this class of user gets" once instead of per user.
2. As an operator, I want to map an OWUI group name to a profile in one env
   var, so that granting a user better limits is an OWUI group membership
   change and not a redeploy.
3. As an operator, I want the mapping to be ordered with first match winning,
   so that a user in several groups gets a predictable profile I can reason
   about from the config line alone.
4. As an operator, I want to deploy this release with no mapping configured and
   see the fleet behave exactly as it does today, so that adopting the feature
   is not a leap of faith on a live system.
5. As an operator, I want unmapped and unknown group names to fall back to the
   default profile rather than refusing service, so that a config typo degrades
   tuning instead of causing an outage.
6. As an operator, I want a loud warning at boot for every group name in my
   mapping that Open WebUI does not know, so that a group rename is discovered
   in seconds rather than as a mystery incident weeks later.
7. As an operator, I want the fully resolved profile table printed at boot, so
   that I can read what the deployment will actually do instead of re-deriving
   it from env vars in my head.
8. As an operator, I want a malformed profile value to fail startup loudly, so
   that a typo'd memory limit can never silently become a default.
9. As an operator, I want to see which profile each live runner is running
   under, so that I can confirm a mapping change took effect without exec-ing
   into anything.
10. As an operator, I want a runner adopted after an orchestrator restart to
    still report the profile it was created under, so that reconciliation does
    not quietly relabel my fleet as default.
11. As an operator, I want profiles to be able to name their own image from day
    one, even while every profile points at the same tag, so that introducing a
    variant later is a config change and not a schema migration.
12. As an operator, I want per-profile memory to interact correctly with the
    Budget, so that generous profiles are refused admission rather than
    overcommitting the host.
13. As an operator, I want the config surface documented in the env example and
    the README in the same style as every other knob, so that the convention is
    discoverable without reading the source.
14. As an operator, I want a rehearsal path on a throwaway stack that proves a
    two-profile deployment before I touch the live box, so that the live cutover
    is a repetition of something I have already seen work.
15. As an admin, I want my existing role-based larger limits preserved through
    this change, so that adopting profiles does not silently demote admins.
16. As an admin, I want group membership to remain purely a tuning signal, so
    that adding a user to a group can never accidentally grant access that the
    role and allowlist gate would have refused.

### Grouped user

17. As a user in a mapped group, I want my runner to start with that profile's
    resources, so that the work I was granted more capacity for actually
    completes.
18. As a user in a mapped group, I want that profile's exec timeout to apply to
    my commands, so that a long legitimate job is not cut off at the fleet
    default.
19. As a user in a mapped group, I want that profile's idle timeout to govern
    my runner's teardown, so that a workflow with long thinking pauses is not
    reclaimed underneath me.
20. As a user in a mapped group, I want a profile change to apply to my next
    runner rather than mutating the one I am using, so that my session is never
    disturbed mid-task.
21. As a user whose group was renamed, I want to keep working on default
    settings, so that an admin's housekeeping never costs me access.

### Ungrouped user

22. As a user in no group, I want the same experience I have today, so that a
    feature aimed at other people is invisible to me.
23. As a user in no group, I want my files, keys and sessions untouched by this
    release, so that nothing I have built is at risk.
24. As a user in an unmapped group, I want service on default settings without
    an error, so that being outside the mapping is not a failure state.

### Driving agent

25. As the driving agent, I want the sandbox environment variables to describe
    the egress stance of the runner I am actually in, so that I do not waste a
    session assuming a strictness that does not apply.
26. As the driving agent, I want the prose orientation in the workspace to agree
    with those variables, so that my two sources of ground truth never
    contradict each other.
27. As the driving agent, I want external-network failures to stay fast and
    self-explanatory under every profile, so that the "never retry, never debug
    DNS" rule holds regardless of who I am working for.
28. As the driving agent, I want the exec timeout that governs my tool calls to
    be the one my user's profile declares, so that my long-running command
    behaves as its budget promises.

### Incident response

29. As an operator investigating an incident, I want the runner's profile to be
    part of its reported state, so that I check the strictness that runner
    actually had instead of assuming global env.
30. As an operator, I want a regression guard in the suite that fails if an
    empty mapping ever stops being a no-op, so that the additive promise is
    enforced by tests rather than by memory.

## Implementation Decisions

- A profile is a named, frozen bundle of exactly six settings: cpus, memory,
  idle timeout, exec timeout, image, egress stance. The set is closed for v2.0;
  adding a seventh is a decision, not an omission to be filled opportunistically.
- Profile values are declared as `POLICY_<NAME>_<FIELD>` env vars, parsed with
  the existing size and duration helpers so that `2g` and `45m` mean in a
  profile exactly what they mean globally. All-env config: no YAML, no DB, no
  new parser.
- Every unset profile field inherits the corresponding global value. A profile
  therefore declares only its differences, and the default profile — the one
  used when nothing matches — is the global values verbatim. "Default" is
  defined as "today", not re-specified alongside it.
- `GROUP_MAP` is a comma-separated ordered list of `groupname:profile`. Order is
  priority; the first entry whose group the caller belongs to wins. Resolution
  is a pure function of (caller's group names, parsed mapping) and is unit
  testable without Docker or Open WebUI.
- Matching is by group **name**, accepted with its readability/rename tradeoff:
  a rename silently demotes to default, mitigated by the boot warning and by
  per-runner profile visibility. Group names are taken from the membership data
  the role check already retrieves; no additional Open WebUI round trip is
  added for group resolution.
- Names referenced by the mapping but unknown to Open WebUI warn at boot and at
  resolution; a profile name referenced by the mapping but never declared is a
  startup failure, because it is unambiguously a config error rather than
  drift.
- Unknown-group, no-group and no-mapping paths all resolve to the default
  profile. No path through profile resolution can deny a request; denial
  remains the exclusive business of the role check and the allowlist.
- The resolved profile is attached to the per-identity policy object at
  authentication time and applied once, at container creation. A profile change
  takes effect on the user's next runner and never mutates a live one, matching
  how role-derived limits already behave.
- Carrying group names on that policy object is treated as a prefactor,
  landed and verified on its own before any profile behaviour depends on it.
- The profile name is written to the container's durable labels, so
  reconciliation after an orchestrator restart restores the profile a runner was
  created under instead of defaulting it.
- Per-profile egress is plumbed as spawn environment. The shims read their
  stance at runtime, so a per-profile value needs no shim change; the shims stay
  deployment-wide binaries and are not touched.
- The orientation renderer stays the single source of truth for both the
  environment channel and the prose channel; it is parameterised by the
  resolved stance so the two channels cannot disagree.
- Timeouts are enforced where they already are: the exec timeout rides in the
  runner's environment at creation, and the idle timeout becomes a per-runner
  value the sweeper reads instead of a single global comparison.
- Per-profile memory flows through the existing Budget admission accounting
  unchanged, so a large profile can be refused admission but can never
  overcommit.
- Observability is part of the feature, not a follow-up: resolved profile table
  at boot, unknown-group warnings, resolved table and per-runner profile name on
  the status surface.
- The runner image definition, the shims and the third-party notices are out of
  bounds for this work.

## Testing Decisions

All assertions are on external behaviour — container configuration as the
Docker API reports it, the environment a runner actually receives, HTTP
response bodies, log output, exit codes. No test reaches into module internals.
This matches the existing suite's style and is what makes the no-op guard
meaningful.

Prior art the new tests extend rather than duplicate:

- `tests/unit/test_config.py` — a typo'd limit must raise, never silently
  default. Profile parsing edge cases belong beside it: inherited fields,
  malformed sizes and durations, an undeclared profile named by the mapping,
  and mapping order.
- `tests/integration/test_resources.py` — limits proven in the cgroup and by
  effect. This is the pattern for "two profiles produce two genuinely
  different containers", and its known timeout-margin sensitivity is why new
  resource assertions stay duration-agnostic.
- `tests/integration/test_roles.py` — fail-closed role resolution. The home for
  "group membership never changes who is admitted", including a pending or
  unknown-role account in a mapped group still being refused.
- `tests/integration/test_egress.py` — zero egress and exactly one network. The
  reference for asserting a profile's egress stance by effect, and for proving
  the strict stance is unchanged by the feature.
- `tests/integration/test_orientation.py` and
  `tests/unit/test_orientation_renderer.py` — the two orientation channels must
  agree. Extended so that agreement holds per profile.
- `tests/integration/test_lifecycle.py` — spawn, restart adoption, spawn race,
  budget. The home for "an adopted runner reports its original profile".
- `tests/integration/test_idle.py` — busy is not idle. The home for a
  per-profile idle timeout being the one that governs teardown.
- `tests/unit/test_readme_env_docs.py` — documentation that greps against the
  implementation. Extended so the profile env convention cannot drift from what
  is actually parsed.

The no-op guard is its own named test and is written before any production
change: with no mapping configured, a spawned runner's full environment,
container resource configuration, image reference and effective timeouts are
identical to the pre-feature baseline, field for field. It runs in every
subsequent slice, and a failure in it blocks the slice rather than being
reconciled afterwards.

The full suite is the acceptance gate for each slice, not a follow-up. The
documented no-build pattern and the flaky-timeout retry discipline already
established for the suite apply unchanged.

## Out of Scope

- **Per-profile docker networks.** The fleet stays single-network for v2.0; the
  trusted-circle threat model holds. Profiles differ in stance, not topology.
- **Image variant builds.** The image field exists per profile from day one and
  every profile points at the same tag. Building or publishing a differentiated
  runner image is a separate effort.
- **Groups as an access gate.** Membership never grants or removes access.
  Admission stays role plus allowlist, untouched.
- **Config in a database or YAML file.** All-env only; no new config format, no
  migration, no runtime reload.
- Changes to the runner image definition, the shims, or the third-party
  notices.
- Per-user overrides, per-profile disk quotas beyond what the existing policy
  object already carries, and any live-box cutover (the live migration is the
  stakeholder's, performed after rehearsal on a throwaway stack).

## Note for the stakeholder (one discrepancy, no decision changed)

ADR-0012 describes group membership as arriving on Open WebUI's *users-list*
payload as `group_ids`. The live code path resolves a single user and receives
`groups` as id/name pairs — so group **names** are available on the call
already being made, which supports the name-matching decision more directly
than the ADR's own reasoning does. The only consequence is that the current
code discards the names it receives; recovering them is the prefactor listed
above. No locked decision is affected.
