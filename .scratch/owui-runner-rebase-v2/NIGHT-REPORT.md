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
