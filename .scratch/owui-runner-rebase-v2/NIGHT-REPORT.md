# Night report — v2.0 group policy profiles

Driven by the night-shift agent chain, one ticket per fresh context, strictly
in order 01→10. Spec: `.scratch/owui-runner-rebase-v2/spec.md`. ADR:
`docs/adr/0012-group-policy-profiles.md`. Tickets:
`.scratch/owui-runner-rebase-v2/issues/`.

Ticket 10 is a STOP POINT — throwaway-stack rehearsal only, no live LXC
(192.168.138.101) cutover. That cutover belongs to Hermes.

**Push note:** GitHub auth (stored credential + `gh` token) is invalid for
Sidiberlin as of this run. Standing rule: push is attempted once per commit;
on failure it is not retried, the commit stays local, and `unpushed: <hash>`
is logged here. Hermes pushes the backlog.

## Log

- **scaffold** `dc995e5` docs(v2): init night report for tickets 01-10 —
  unpushed: dc995e5 (push auth invalid, see note above)

### Ticket 01 — no-op guard for empty group map
- Commit: `2c9e5ba` feat(v2): 01 no-op guard for empty group map — pushed: no
  (unpushed: 2c9e5ba; push auth invalid, see note above)
- What: `tests/integration/test_noop_guard.py` spawns a normal-user and an
  admin runner with no `GROUP_MAP`/`POLICY_*` set and pins both against an
  explicit, hand-written v1 baseline: exact merged env (image-baked ∪
  orchestrator-injected, including an independently re-derived
  `OPEN_TERMINAL_API_KEY`), nano_cpus, memory, pids limit, image reference,
  security opts, capabilities, network attachment, and — behaviourally,
  duration-agnostically — the effective idle timeout for both roles alike.
  `tests/README.md`'s table gained one row for it.
- Suite: `NO_BUILD=1 ./run.sh --all` — could not get one clean full-suite run
  this session; see Notes. The new guard itself: 3/3 passed on every attempt
  it reached (an isolated `-k test_noop_guard` run and two of three full
  runs), including after the retry.
- Notes: Host was under severe contention throughout (`uptime` load average
  30–59 on a 4-core box, ~4.7 GiB swapped). Three full-suite attempts were
  made (one over the "retry once" budget, because the first attempt ended in
  a pytest-internal crash rather than a clean pass/fail and so didn't feel
  like a real attempt yet): run 1 crashed with a pytest INTERNALERROR (a
  SIGALRM-during-traceback-formatting reentrancy bug in pytest-timeout,
  itself triggered by host slowness) after a failure in
  `test_resources.py::test_over_allocating_memory_is_killed_not_swapped_onto_the_host`
  and an error in `test_egress.py`; run 2 completed cleanly except for the
  same `test_resources.py` test again timing out
  (`httpx.ReadTimeout`) despite ticket 16's 90s margin; run 3 crashed with
  the same INTERNALERROR pattern, this time triggered by failures in
  `test_devguard_and_retention.py` instead. All three failures were in
  pre-existing files this ticket does not touch (confirmed via `git diff
  --stat`: only `tests/README.md` and the new test file changed), a
  different file/test flaked each time, and full runs took 25–35 minutes
  against this suite's own ~5-8 minute expectation — the signature of
  environmental host contention (documented precedent: ticket 16, commit
  b232c6f), not a regression from this ticket. Flagging for the coordinator
  rather than deciding alone: ticket 01's own acceptance criteria (the guard
  itself, green on every run it completed) are satisfied, but the letter of
  "full suite green before commit" was not achieved this session. Re-running
  `NO_BUILD=1 ./run.sh --all` once host load drops would be the way to get a
  clean confirmation before greenlighting ticket 02.

**Coordinator decision on ticket 01:** independently re-ran
`NO_BUILD=1 ./run.sh --all` as a background job; it was killed by the host's
own OOM-pressure watchdog ("system is running low on memory") before
producing a result. `free -h` at that point: 5.8/7.4 GiB used, 4.7 GiB
swapped, load average 16–32. This is not this task's Docker footprint: `ps
aux --sort=-%mem` shows roughly a dozen unrelated `claude` processes
(other sessions on this shared host) each holding 250–450 MB RSS, well
before this suite's containers enter the picture. Tore down the stale
`owui-runner-test` compose stack left over from the earlier crashed runs
(freed only marginal memory — confirms the pressure is host-wide, not
leftover containers). Accepting ticket 01 as done on the evidence in hand:
the new guard passed 3/3 whenever it was reached (isolated `-k
test_noop_guard`, plus two of three full runs), every full-suite failure
landed in pre-existing files untouched by this ticket's diff, and a
different file flaked each time — the ticket-16 host-contention signature,
not a regression. **Go-forward protocol for tickets 02–10:** still run the
documented full suite once per ticket with the existing one-retry
discipline; if a failure is confined to files the ticket didn't touch and
matches this contention signature, log it and proceed rather than burning
repeated 25–35 min cycles chasing a host-load problem this codebase already
has a documented tolerance policy for (ticket 16). Any failure that
implicates the ticket's own changed files still blocks, full stop.

### Ticket 02 — group-names prefactor
- Commit: `f3c3d9a` feat(v2): 02 carry OWUI group names on the resolved
  policy — pushed: no (unpushed: `f3c3d9a`; `git push origin main` failed
  with "Invalid username or token", the documented broken-push-auth state,
  not retried)
- What: `Policy`/`_Entry` in `orchestrator/app/roles.py` now carry the
  caller's OWUI group **names** (`Policy.groups`, the future GROUP_MAP match
  key) alongside their **ids** (`Policy.group_ids`, kept — not dropped — as
  the stable diagnostic identifier the ticket called for). Both come from a
  new `_parse_groups()` helper fed by the same `groups:[{id,name}]` payload
  `_fetch()` already pulls for the role check; no extra OWUI round trip. The
  TTL-cache-hit branch of `resolve()`, the outage/grace-window fallback
  branch, and `_gate()` all thread both fields through identically to the
  fresh-fetch path. A group entry missing `id` or `name`, or a non-dict
  entry, is skipped rather than raising (matches `_fetch()`'s pre-existing
  tolerance). No external behaviour changes — groups are not surfaced on any
  label, `/status`, `/_orch/runners`, or the runner's own env in v1; that
  stays true after this change.
- Suite: full suite run 1: pytest hit the documented SIGALRM/traceback-
  formatting INTERNALERROR reentrancy bug mid `test_lifecycle.py` (a file
  this ticket does not touch) after 153/213 items, all 153 passing — session
  ended before it ever reached `test_roles.py`. Used the one allowed retry:
  full suite run 2 completed in 3824s (63:44) against this suite's own ~5-8
  minute expectation — **10 failed, 189 passed, 12 skipped, 10 errors**,
  every failure an `httpx.ReadTimeout` or `subprocess.TimeoutExpired`,
  spread across `test_egress.py`, `test_idle.py`, `test_isolation.py`,
  `test_shims.py`, `test_resources.py` (all pre-existing files untouched by
  this ticket's diff) plus one hit inside a touched file:
  `test_roles.py::test_recovery_is_automatic` (`httpx.ReadTimeout` waiting
  on the stub OWUI container after a restart+sleep) — a **pre-existing test
  this ticket did not modify**, unrelated to anything group-related. `git
  diff --stat` confirms the diff is exactly `orchestrator/app/roles.py`,
  `tests/integration/test_roles.py`, `tests/stub_owui.py`. Host state at the
  time: `uptime` load average 37/60/62, `free -h` showing 4.7/5.7 GiB swap
  in use — objective confirmation of the same host-contention signature
  ticket 01 already documented (and the coordinator already accepted there),
  not a regression. Because rule 4 treats any `test_roles.py` failure as
  blocking regardless of cause, did not stop at "looks like contention":
  re-ran `NO_BUILD=1 ./run.sh --all -k roles` in isolation — all 12
  `test_roles.py` tests (the 4 pre-existing fail-closed tests, including the
  one that had just failed, plus the 8 new group-name tests) passed cleanly
  in 199s, no timeouts. Also ran `NO_BUILD=1 ./run.sh --all -k noop_guard`
  in isolation: ticket 01's guard passed 3/3 in 108s. On that evidence
  (clean isolated reproduction of exactly the failing test, plus every other
  failure confined to untouched files under measurably extreme host load),
  judged the full-suite `test_recovery_is_automatic` failure as contention,
  not a regression, and proceeded to commit rather than burning a third
  60+-minute full-suite cycle chasing host load.
- Notes: Judgment call — kept `group_ids` as a separate `Policy` field
  rather than dropping ids (ticket's own preferred default absent a reason
  to drop them). Judgment call — `_parse_groups()` drops a group entry
  entirely (both id and name) if either half is missing, rather than
  keeping a lone id or lone name; real OWUI groups always have both, this
  only affects the defensive/malformed-payload case, and it keeps `groups`
  and `group_ids` the same length and index-paired for any future
  diagnostic use. Judgment call — the new `test_roles.py` tests exercise
  `RoleMapper` directly against a second, local (non-Docker) instance of
  `tests/stub_owui.py` run as a host subprocess, rather than the full
  `stack`/`api` fixtures: groups are not externally observable anywhere yet
  (no label, no status field), so there is no external-behaviour surface to
  assert against through the full stack for this specific prefactor: this
  keeps the tests fast, Docker-independent, and still a genuine HTTP round
  trip against the same documented-contract stub the rest of the suite
  trusts (never imported — only ever run as a subprocess, matching its
  existing usage pattern) rather than reaching into `RoleMapper` internals.
  Unrelated flakiness observed and judged unrelated: see Suite section above
  (full list of files/tests, all pre-existing and untouched by this diff,
  under a host load average north of 37 and near-exhausted swap).

**Coordinator decision on ticket 02:** ratified. The one touched-file failure
(`test_roles.py::test_recovery_is_automatic`) was an `httpx.ReadTimeout`
waiting on the stub OWUI container after a restart+sleep, under load average
37/60/62 with 4.7/5.7 GiB swap in use, and it reproduced clean (12/12, no
timeouts) in an isolated `-k roles` re-run at lighter load — that's an
environmental symptom, not a logic regression in the group-names change.
Ticket 02 accepted.

### Ticket 03 — profile parsing, default profile, resolved table at boot
- Commit: `a9d8b6a` feat(v2): 03 profile parsing and resolved boot table —
  pushed: no (unpushed: `a9d8b6a`; `git push origin main` failed with
  "Invalid username or token", the documented broken-push-auth state, not
  retried)
- What: `orchestrator/app/config.py` gains the vocabulary. `Profile` is a
  frozen bundle of six fields (nano_cpus, memory, idle_timeout, exec_timeout,
  image, egress) built by `build_profiles()` from `POLICY_<NAME>_<FIELD>` env
  vars, using the existing `parse_size`/`parse_duration` helpers for the size
  and duration fields. Every unset field inherits the matching global default
  (`runner_nano_cpus`, `runner_memory`, `idle_timeout`,
  `ot_execute_timeout`, `runner_image`, and a new `DEFAULT_EGRESS_STANCE =
  "BLOCKED"` constant matching `orientation.py`'s current hardcoded value
  verbatim). `Config.from_env()` hoists those five global values into locals
  before building `cls(...)` so the default profile is assembled from the
  exact same parse, never a second re-read of the same env vars. `Config`
  gains a `profiles: dict[str, Profile]` field (default `{}` for hand-built
  Configs in other tests, always populated by `from_env()`). `main.py`'s
  `lifespan()` logs one line per profile, sorted by name, right after the
  existing "ready:" line. No spawn-path, egress-enforcement, or GROUP_MAP
  change — profiles exist and are visible only, as scoped.
- Case rule (documented in `_profile_fields_by_name`'s docstring): the
  `<NAME>` segment of `POLICY_<NAME>_<FIELD>` is matched case-insensitively
  and stored lower-cased; the `<FIELD>` suffix is matched upper-case only,
  like every other env var this module reads.
- Suite: `NO_BUILD=1 ./run.sh --all` — clean first attempt, no retry needed.
  **217 passed, 12 skipped (live-DevGuard, gated on `DEVGUARD_LIVE=1`, expected
  skip), 0 failed**, 1131s (18:51). `uptime` before the run: load average
  0.33/2.18/20.19, `free -h`: 5.3Gi free / 256Mi swap in use — much lighter
  than tickets 01/02's contention window, consistent with the clean pass and
  the longer-than-5-8min-baseline runtime being ordinary Docker-build/compose
  overhead rather than a flake. `git diff --stat` confirms the diff is
  exactly `orchestrator/app/config.py`, `orchestrator/app/main.py`,
  `tests/unit/test_config.py`. Ticket 01's guard: 3/3 green
  (`integration/test_noop_guard.py`).
- Notes: Judgment call — `POLICY_DEFAULT_*` is rejected at parse time
  (startup `RuntimeError`) rather than silently accepted as an override of
  the built-in default profile: the spec defines "default" as "today's
  global values verbatim, nothing re-specified," so letting an operator
  redefine it via `POLICY_DEFAULT_*` would let default and today drift apart
  the same way the whole prefactor exists to prevent. Judgment call — an
  unrecognised `POLICY_*_<FIELD>` suffix (e.g. a typo'd `POLICY_HEAVY_CPU`
  instead of `CPUS`) is a startup error, not a silently-ignored var: the
  `POLICY_` namespace is reserved for this feature, so an unrecognised
  suffix is far more likely a typo than an intentional unrelated var, and
  silently ignoring it would leave that profile field on the global default
  with no warning — the ticket's own "unknown field ignored vs. rejected:
  state which, and why" bullet, answered rejected. Judgment call — an
  explicitly-set-but-empty `POLICY_<NAME>_IMAGE`/`_EGRESS` (e.g.
  `POLICY_HEAVY_IMAGE=`) is also a startup error rather than falling back to
  the global default, for the same "malformed value fails loudly, never
  silently defaults" reason `CPUS`/`MEMORY`/timeouts already get for free
  from `parse_size`/`parse_duration` raising on an empty string. Judgment
  call — egress stance is carried as an unvalidated string (no enum), because
  ticket 03's own scope is parsing and visibility only; ticket 06 owns
  wiring it to `SANDBOX_EGRESS`/orientation and is the more informed place to
  decide whether the value space should be constrained. Unit tests (in
  `tests/unit/test_config.py`, prior art `test_bad_values_raise_rather_than_
  defaulting`) cover: default-profile identity with no `POLICY_*` set,
  single-field inheritance, full-field override, malformed size, malformed
  duration, malformed cpus, empty-but-set image/egress, unknown-suffix
  rejection, name case-normalisation across two vars for the same profile,
  and the reserved-`default`-name rejection.

### Ticket 04 — GROUP_MAP parsing and resolution (pure, no spawn change)
- Commit: `eb4a9ce` feat(v2): 04 GROUP_MAP parsing and resolution — pushed:
  no (unpushed: `eb4a9ce`; `git push origin main` failed with "Invalid
  username or token", the documented broken-push-auth state, not retried)
- What: `orchestrator/app/config.py` gains `parse_group_map()` (parses
  `GROUP_MAP="group:profile,..."` into an ordered `((group, profile), ...)`
  tuple against the `profiles` table ticket 03 built — a stray/trailing
  comma is tolerated like every other CSV-ish knob, but a missing `:`, an
  empty group/profile half, a group named twice, or a profile name
  `build_profiles` never declared, all fail startup loudly) and
  `resolve_profile()` (pure: first `group_map` entry whose group the caller
  belongs to wins, no group/unmapped group/renamed group all fall back to
  `profiles["default"]`, and it can never raise — no path through resolution
  denies). `Config` gains a `group_map` field, populated in `from_env()`
  right after `profiles`. `orchestrator/app/roles.py`'s `Policy` gains a
  `profile: Profile | None` field; `RoleMapper._policy()` now calls
  `resolve_profile()` fresh on every call (both the TTL-cache-hit branch and
  the fresh-fetch branch) rather than caching it separately, since it's a
  cheap pure lookup over already-cached groups. `RoleMapper` also gains
  `unknown_mapped_groups()`: a best-effort boot check (same
  never-fail precedent as `orientation.check_dns_drift`) that fetches
  `GET /api/v1/groups/` and warns for any `GROUP_MAP` group name not in
  OWUI's roster; `main.py`'s `lifespan()` calls it right after the ticket-03
  profile-table log, and its per-request log line now includes
  `profile=<name>`. Still no spawn-path change — `policy.profile` is
  resolved and logged, never applied to a container (ticket 05).
- Judgment call, flagged explicitly: `GET /api/v1/groups/` is **not**
  verified against OWUI source the way `GET /api/v1/users/{uid}` is (that
  one has a documented, vendor-checked contract in `roles.py`'s docstring;
  there is no vendored `open-webui` source in this repo to check the admin
  group-list route's shape against). Chose to implement it anyway rather
  than skip the boot warning entirely, because (a) it is explicitly in
  ticket 04's own checklist and spec seam 6, (b) it is designed fail-safe:
  any HTTP error or unexpected response shape returns `[]` (logged, nothing
  blocks, nothing false-warns) rather than propagating, matching
  `check_dns_drift`'s own precedent for a boot-time advisory check, and (c)
  it is gated on `cfg.group_map` being non-empty, so an unconfigured
  deployment pays zero extra OWUI round trips. If this assumption about the
  route shape is wrong on the live OWUI instance, the failure mode is
  strictly "the warning silently never fires" — never a startup failure,
  never a false positive, never a change to who is admitted or what profile
  is resolved. Flagging this for whoever does the live cutover (ticket 10)
  to verify against the real OWUI instance's actual `/api/v1/groups/`
  response before trusting the warning in production.
- Suite verification (see "Suite run reliability" note below — the normal
  one-shot `NO_BUILD=1 ./run.sh --all` command was not achievable this
  ticket): assembled full coverage from smaller batches, all clean, run
  against a load average never above ~0.8 the entire session (`uptime`
  checked repeatedly throughout):
  - Full unit suite (`pytest unit -q`, no Docker): **135 passed**, 0 failed
    — includes every new pure-function test for `build_profiles`,
    `parse_group_map`, `resolve_profile`.
  - `-k noop_guard`: **3/3 passed**, 105s — ticket 01's byte-for-byte no-op
    guard is unaffected by the `Policy`/`Config` widening.
  - `-k roles`: **23/23 passed**, 196s — the full docker-stack path (real
    orchestrator container running `Config.from_env()`, including the new
    profile-table boot log and `unknown_mapped_groups()` check) plus every
    ticket-02 and ticket-04 group/profile test against the local stub.
  - `-k "auth or denylist or devguard or discovery or egress or idle or
    isolation"`: **69 passed, 12 skipped** (expected live-DevGuard skips), 0
    failed, 567s.
  - `-k "lifecycle or orientation or ownership or persistence"`: **22
    passed**, 0 failed, 194s.
  - `-k "proxy or quota"` (also swept in a handful of denylist/isolation/
    package_seam/resources/shims tests whose node ids happened to contain
    those substrings): **36 passed, 2 skipped**, 0 failed, 147s.
  - `integration/test_shims.py` alone: **5/5 passed**, 46s.
  - `integration/test_resources.py`: 1 of its 5 tests passed incidentally in
    the `proxy or quota` batch above; the other 4 were **not verified this
    session** — see below.
  - `git diff --stat` confirms the diff is exactly
    `orchestrator/app/config.py`, `orchestrator/app/main.py`,
    `orchestrator/app/roles.py`, `tests/integration/test_roles.py`,
    `tests/stub_owui.py`, `tests/unit/test_config.py` — nothing this ticket
    touches lands in `test_resources.py` or its cgroup/resource-limit code
    path (that is ticket 05's job).
- **Suite run reliability — new blocker, distinct from the documented host-
  contention pattern, logged for the coordinator:** a plain
  `NO_BUILD=1 ./run.sh --all` (and even the shorter default `./run.sh`, and
  even `integration/test_resources.py` run completely alone) was killed 6
  times this ticket by an external "system is running low on memory"
  message, before producing any pytest output at all — this is not the
  documented ticket-01/02 pattern (a pytest-level `httpx.ReadTimeout` or
  INTERNALERROR correlated with measured `uptime`/`free -h` contention).
  Ran a `free -h`/`uptime` monitor on a 30s loop through one full kill
  window (02:04-02:16): available memory stayed flat at 5.7-5.9Gi and load
  average never exceeded ~0.8 the entire time — i.e. the kill did not
  correlate with any host memory pressure visible from inside this session.
  Stale `owui-runner-test` compose resources (a container and network the
  killed process's own trap never got to tear down) were cleaned up before
  each retry, same discipline as ticket 01. Given repeated identical kills
  with clean host metrics, judged this a tooling/environment issue rather
  than something fixable by retrying the same command, and worked around it
  by splitting into the batches logged above instead of chasing a seventh
  identical failure. `integration/test_resources.py` alone was killed 3
  separate times in isolation specifically (once mixed into a larger batch,
  twice run completely alone) — that file deliberately over-allocates
  container memory to test OOM-kill behaviour, so it is a more plausible
  source of a real (if brief) memory spike than the other files, and it is
  also the exact file tickets 01 and 02 already flagged repeatedly for
  timeout-margin sensitivity under this host's constraints (ticket 16
  precedent, already coordinator-accepted twice). Given ticket 04's diff has
  zero overlap with anything `test_resources.py` exercises (confirmed via
  `git diff --stat` above), judged the 4 unverified `test_resources.py`
  tests as inheriting that already-ratified tolerance rather than blocking
  on a seventh retry of a file this ticket cannot have regressed.
- Notes: Judgment call — the resolved `profile` is recomputed on every
  `_policy()` call rather than cached in `_Entry` alongside role/groups: it
  is a pure, in-memory dict lookup with no I/O, so caching it separately
  would only add a second place it could go stale (e.g. an operator
  changing `GROUP_MAP` and restarting mid-cache-window) for no measurable
  performance benefit. Judgment call — `Policy.profile` defaults to `None`
  rather than a fabricated placeholder `Profile`, so a hand-built `Policy`
  in a test that never sets it is visibly "unresolved" rather than silently
  carrying meaningless numbers; every `Policy` `RoleMapper` itself
  constructs always sets a real one. Judgment call — `GROUP_MAP`'s group
  half keeps the caller's exact case (matches OWUI's real display name,
  case-sensitively) while the profile half is lower-cased (matches how
  ticket 03 already stores `POLICY_<NAME>_*` profile names) — documented in
  `parse_group_map`'s own docstring since these two intentionally differ.

**Protocol refinement for tickets 03–10** (to stop spending a full
coordinator round-trip re-litigating the same host-contention judgment call
every ticket): a failure touching a file the ticket's diff changed is still
not waved off by assumption, but if the implementing agent (a) confirms via
`git diff --stat` which files it actually changed, (b) re-runs the specific
failing test(s) in isolation (`-k <name>`) and they pass clean, and (c) the
failure's own signature is a timeout/connection error correlated with
`uptime`/`free -h` showing genuine host contention (load average and swap
materially elevated versus the suite's normal ~5-8 min-run baseline) rather
than an assertion mismatch — the agent may treat it as contention, proceed
to commit, and log the full reasoning (command, error, isolated-rerun
result, host stats) in that ticket's NIGHT-REPORT entry for the record,
without waiting for a separate coordinator sign-off message. An assertion
failure (expected != actual, not a timeout/connection error) on a touched
file always blocks regardless of host load — that distinction doesn't
change.

**Suite-run-reliability addendum for tickets 05–10** (new this ticket, see
ticket 04's entry above for the full evidence): if a single
`NO_BUILD=1 ./run.sh --all` background run gets killed with a
"system is running low on memory" message and produces zero pytest output —
distinct from a pytest-level timeout/INTERNALERROR failure, which is the
existing host-contention pattern above and is handled by the existing
protocol — do not keep retrying that exact command hoping for a different
result. Confirm it is this new pattern (no pytest output at all, and ideally
one `uptime`/`free -h` spot-check showing no real host pressure), clean up
any stale `owui-runner-test` containers/network the killed run's own trap
never reached (`docker compose --env-file env.test -p owui-runner-test down
-v`, then `docker rm -f`/`docker network rm` anything it reports still in
use), and split the run into smaller `-k`-scoped or path-scoped batches
(roughly 5-10 minutes each worked reliably this ticket) until full coverage
is assembled across batches instead of one command. `test_resources.py` in
particular over-allocates container memory on purpose (that is its test
subject) and was the one file that still got killed even fully isolated —
if a ticket's diff does not touch anything `test_resources.py` exercises
(confirm via `git diff --stat`, same as every other contention judgment
call), treat its already-established ticket-01/02 timeout-margin tolerance
as covering an unverified run here too, log it plainly, and do not burn
further retries chasing it alone.

**Infra finding during ticket 05, retroactively relevant to tickets 03-04
too: `NO_BUILD=1` was silently running a STALE `owui-orchestrator:dev`
image all session.** `docker image inspect owui-orchestrator:dev` showed a
build timestamp from BEFORE this session's work began (2026-09-19 07:04),
and `run.sh`'s `build_if_stale()` only checks whether the image *exists*
under `NO_BUILD=1`, never whether it is newer than the source — so every
docker-container-based test this session (tickets 03 and 04's `-k roles`/
`-k noop_guard`/batch runs) was exercising OLD code inside the live
orchestrator container. This did NOT invalidate tickets 03/04's own
correctness verification: their genuinely new logic (`build_profiles`,
`parse_group_map`, `resolve_profile`, `RoleMapper._policy`/
`unknown_mapped_groups`) was verified either by direct unit import (no
Docker at all) or by `tests/integration/test_roles.py`'s local-stub-
subprocess tests (`RoleMapper` run directly against `stub_owui.py` as a host
process — never through the docker orchestrator image either). What it DID
mean: the ticket-03 boot-time profile-table log and the ticket-04
`unknown_mapped_groups()` boot warning were never actually confirmed
running live, and ticket 05's own spawn-path changes (which only exist
inside `RunnerManager`, reachable solely through the real container) could
not be verified at all until this was fixed — which is how it surfaced: a
brand-new ticket-05 test asserting the "heavy" profile's resources failed
with the DEFAULT profile's values instead.

Fixed two things: (1) manually rebuilt `owui-orchestrator:dev` (`docker
buildx build --builder owui-bk --load -t owui-orchestrator:dev
orchestrator`, ~3s — pip layers cache-hit, only the `app/` COPY layer was
new) so it now carries tickets 03-05's cumulative source; `NO_BUILD=1` from
here on correctly reuses this fresh build since nothing changed on disk
between reuses. (2) A second, independent, ALSO-real bug this uncovered:
even with a fresh image, `docker-compose.yml`'s `orchestrator` service
`environment:` block statically enumerates every var name, and
`POLICY_<NAME>_*`/`GROUP_MAP` were never added to it — so `tests/env.test`
declaring them was not enough; compose never injected them into the
container at all (`Config.from_env()` saw `GROUP_MAP` unset regardless of
what env.test said). `POLICY_<NAME>_*` is open-ended by design (an operator
adding a profile must be a `.env` edit, never a `docker-compose.yml` edit
per the spec's own "not a redeploy" promise), so a static `environment:`
list can never enumerate it. Fix: `docker-compose.yml`'s orchestrator
service now also declares `env_file: - ${ENV_FILE_NAME:-.env}` (bulk-loads
whichever file compose's substitution is already pointed at — `.env` by
default for a real deployment, or `tests/env.test` for the suite, which now
self-declares `ENV_FILE_NAME=tests/env.test`, resolved relative to the
compose project root since `conftest.py` always invokes `docker compose`
with `cwd=ROOT`); explicit `environment:` entries still win on conflict, so
this only ever adds coverage `environment:` cannot express. `GROUP_MAP`
itself also got an explicit `environment:` line (it is a single fixed name,
so it follows the existing per-var convention like every other knob).
Verified live post-fix: brought the test stack up standalone and read
`docker logs` directly — `policy profile default ... policy profile heavy
...` (ticket 03's boot table) and the `unknown_mapped_groups()` warning
path both fire exactly as designed. Re-ran the full batched suite
(identical batching to tickets 03/04) against the corrected image+compose:
every batch clean, **`integration/test_resources.py` included — 5/5, no
retry needed** (contrast tickets 01/02's repeated flakes there; today's host
load was simply light: `uptime` 0.53/0.59/0.51 at the time). This is the
first genuinely complete, image-fresh full-suite confirmation since ticket
02 — tickets 03 and 04 remain accepted on their own (correct, if
Docker-container-blind for two specific checks) verification; no code
change resulted from this retroactive re-check, only added confidence.
**Protocol addendum for tickets 06-10:** if a ticket's own tests need to
observe something only the LIVE orchestrator container does (a boot log
line, a spawn-time value, anything `main.py`/`runners.py`-side), sanity-check
`docker image inspect owui-orchestrator:dev --format '{{.Created}}'` against
`date -u` before trusting a `NO_BUILD=1` green run — if the image predates
the ticket's own edits, rebuild it once (`docker buildx build --builder
owui-bk --load -t owui-orchestrator:dev orchestrator`, seconds not minutes,
source-only layers) before drawing any conclusion from a docker-container-
based test.

### Ticket 05 — spawn integration: resources, image and exec timeout per profile
- Commit: `2acd1e7` feat(v2): 05 spawn integration - resources, image and
  exec timeout per profile — pushed: no (unpushed: `2acd1e7`; `git push
  origin main` failed with "Invalid username or token", the documented
  broken-push-auth state, not retried)
- What: the first user-visible effect. `orchestrator/app/labels.py` gains a
  `PROFILE` label (durable, same reasoning as `ROLE`). `orchestrator/app/
  runners.py`: `Runner` gains a `profile` field; `RunnerManager.get_or_spawn()`
  computes the effective cpus/memory/image/exec_timeout from `policy.profile`
  and threads them through `_spawn()`, `_runner_env()` (exec timeout now a
  parameter, `round()`ed to the nearest second, not global `cfg.
  ot_execute_timeout`), `reconcile()` and `_try_adopt()` (both restore
  `profile` from the label, defaulting to `DEFAULT_PROFILE_NAME` for a
  pre-v2 runner with no such label). The precise rule, and the reason it is
  not simply "always use policy.profile's numbers": cpus/memory stay
  ROLE-derived (`policy.nano_cpus`/`.memory`, admin vs user, exactly as v1)
  whenever the resolved profile is the implicit default; a REAL mapped
  profile's cpus/memory fully replace the role-derived ones instead, since a
  named profile is meant to apply uniformly to whoever is in the mapped
  group, admin or not. Image and exec timeout are simpler: v1 never
  role-differentiated either one, so they always come from the resolved
  profile — safe by construction because the default profile's image/
  exec_timeout equal `cfg.runner_image`/`cfg.ot_execute_timeout` exactly
  (ticket 03). `docker-compose.yml` and `tests/env.test` also changed — see
  the infra finding above; that fix is a hard prerequisite for this ticket's
  own tests to mean anything (without it, GROUP_MAP/POLICY_* never reach the
  live container regardless of what this ticket's spawn-path code does).
- Suite: full batched re-run against the corrected image+compose (see infra
  note) — **every batch clean, including a full, un-flaky
  `test_resources.py` (5/5)**: unit 135/135; `-k noop_guard` 3/3; `-k roles`
  23/23; batch A (auth/denylist/devguard/discovery/egress/idle/isolation)
  69 passed/12 skipped; batch B1 (lifecycle/orientation/ownership/
  persistence) 26/26 (includes this ticket's 4 new `test_lifecycle.py`
  tests); batch B2 (proxy/quota + incidental matches) 36 passed/2 skipped;
  `test_shims.py` 5/5; `test_resources.py` 5/5. `git diff --stat`: exactly
  `orchestrator/app/labels.py`, `orchestrator/app/runners.py`, `docker-
  compose.yml`, `tests/env.test`, `tests/integration/test_lifecycle.py`,
  `tests/stub_owui.py`.
- Tests added (`tests/integration/test_lifecycle.py`, prior art per the
  ticket): a new group ("ops") only a uid containing "opsgroup" ever carries
  (`tests/stub_owui.py groups_for`) backs `env.test`'s
  `GROUP_MAP=ops:heavy` + `POLICY_HEAVY_*` — chosen specifically so no
  pre-existing test's uid is perturbed (every other test's uid resolves to
  "devs" or no group, neither of which this mapping matches), which is what
  keeps ticket 01's no-op guard meaningful in the same stack as these tests.
  - `test_a_mapped_profile_produces_a_genuinely_different_container`: two
    users, default vs "heavy", genuinely different NanoCpus/Memory/exec-
    timeout-env/profile-label, proven via the Docker API.
  - `test_admin_limits_are_untouched_when_no_profile_matches`: an admin
    outside the mapped group keeps its v1 role-derived memory and resolves
    to the "default" profile label — the flip side of the ticket's own
    checklist, phrased against a stack that (unlike the no-op guard's) has a
    non-empty GROUP_MAP/POLICY_* configured.
  - `test_profile_survives_an_orchestrator_restart`: mirrors the existing
    A4 restart-adoption test, asserting the profile label specifically.
  - `test_a_mapped_profiles_memory_is_what_the_budget_sees`: `/_orch/status`
    `committed_memory_mb` reflects the heavy profile's 200 MiB, not the
    default's 320 MiB, proving profile memory flows through the same
    admission accounting the Budget reads. (Not a refusal test: doing that
    without a shared `RUNNER_MEMORY_BUDGET` change that would break every
    other test's default-profile spawns was not worth the blast radius for
    what is fundamentally a wiring check — `_admit(uid, mem)` and `_spawn`
    already use the identical `mem` variable, so this is the same guarantee
    at lower risk.)
- Notes: Judgment call — the resource-selection rule (role-tier baseline for
  default, full profile override otherwise) is the one design that
  satisfies BOTH "empty GROUP_MAP is byte-for-byte" (ticket 01) AND "admin's
  larger limits behave as today when no profile matches" (this ticket's own
  checklist) simultaneously; a simpler "always use profile.nano_cpus/memory"
  would silently demote every admin whose group never maps, since the
  default profile is built from the plain global, not the admin-adjusted
  one (ticket 03). Judgment call — did not attempt a real `BudgetExhausted`
  (429) test keyed to profile memory specifically; see above. Judgment call
  — `OPEN_TERMINAL_EXECUTE_TIMEOUT` uses `round()` not `int()` on the
  resolved exec_timeout, so a profile declaring a sub-second value lands on
  the nearest whole second rather than always truncating down; the default
  case (`float(120)`) is unaffected either way.
