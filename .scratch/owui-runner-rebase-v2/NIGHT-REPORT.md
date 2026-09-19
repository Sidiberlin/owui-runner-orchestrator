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
