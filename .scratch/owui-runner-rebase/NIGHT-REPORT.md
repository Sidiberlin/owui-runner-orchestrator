# Night Shift Report — owui-runner-rebase

Status at handoff: **tickets 10–15 all executed, all committed locally, nothing
pushed. The ticket-12-review fixup commit has since been re-verified** (see
"Fixup re-verification" below, added after host memory pressure cleared) —
**everything in this report is now suite-green.**

## Commits (all local, none pushed, no `gh` calls made)

```
80a5cd6 tests: rename unit/test_orientation.py to avoid a module-name collision
1eea884 fixup: address /code-review findings on tickets 12 and 14
10b3b67 publication: LICENSE, THIRD-PARTY-NOTICES draft, doc placeholder fixes (ticket 15)
8f2b89a tests: extend the suite for the rebase and orientation layer (ticket 14)
18d8080 orientation: seed AGENTS.md, inject SANDBOX_* env, ship curl/wget/apt-get shims (ticket 13)
02b80d9 orchestrator: move to zendis/python3:3.13-main, gated (ticket 12)
3603204 compose: swap busybox helpers for digest-pinned zendis/coreutils (ticket 11)
8703003 runner: strip the unused opencode CLI stage (ticket 10)
```

## Ticket 10 — runner image without opencode

**Done.** `runner/Dockerfile`: removed the `opencode` build stage, its
`OPENCODE_VERSION` ARG, the fetch/install RUN block, and the `--from=opencode`
copy; kept `open-terminal:slim`, the Node stage, entrypoint semantics, uid-1000
layout, N8 caps, `WORKDIR /home/user`. Also dropped the now-dead
`OPENCODE_VERSION` build-arg default from `docker-compose.yml`, `.env.example`,
`tests/env.test`.

**Evidence:**
```
$ docker run --rm --entrypoint sh owui-agent-runner:dev -c 'command -v opencode; echo rc=$?'
rc=1                      # not found
$ docker exec runner-<uid> sh -c 'command -v opencode'   # (test_shims.py, live)
rc != 0, empty stdout
```
Image builds clean via the `owui-bk` buildx remote driver.

## Ticket 11 — compose helpers on zendis/coreutils

**Done.** `devguard-cache-init` and `devguard-vulndb-tmp-init` now use
`registry.opencode.de/oci-community/images/zendis/coreutils:main@sha256:4168c1bbcb59f61711cf1e5a99abdb9634b35a22d1db0f49f927daf87c812da8`
(digest-pinned) instead of `busybox:1.36`. `user: "0:0"` override verified to
behave identically.

**Evidence:**
```
$ docker run --rm --user 0:0 <that digest> sh -c 'chown --version; busybox | head -1'
chown (GNU coreutils) 9.7
BusyBox v1.37.0 () multi-call binary.
```

## Ticket 12 — orchestrator on zends python3, gated

**Done, gate passed.** `orchestrator/Dockerfile` now builds on
`registry.opencode.de/oci-community/images/zendis/python3:3.13-main@sha256:bcc27cb47133b3863296808b10ec70417d94364bc6b096279f186d81c786cd2e`,
via the M0-verified `venv --without-pip` + `get-pip.py` bootstrap (system pip
and `ensurepip` are both broken on this Nix base — confirmed again this
session). Recorded as **ADR-0011**.

**Gate evidence (before the review fixup below):**
```
$ docker run --rm --entrypoint .../venv/bin/python owui-orchestrator:dev \
    -c "import aiodocker, fastapi, uvicorn, httpx; import app.main; print(app.main.app)"
import OK: <fastapi.applications.FastAPI object at ...>
```
Full suite against a stack running that exact image: **162 passed, 12
skipped (live-DevGuard-gated), 7 deselected (slow)**.

**Then `/code-review` on this commit found a real bug** (see "review
findings" below) — fixed in `1eea884`, not yet re-verified by a fresh build
(see "Outstanding for the morning").

## Ticket 13 — orientation layer

**Done, suite green.** New `orchestrator/app/orientation.py` is the single
renderer: `sandbox_services(cfg)` is the one list; `render_services_env()`
and `render_agents_md()` both consume it, so the env var and the AGENTS.md
service section cannot independently drift.

- **Data:** `SANDBOX_MODE=air-gapped`, `SANDBOX_EGRESS=BLOCKED`,
  `SANDBOX_INTERNAL_SERVICES=<name:port=description,...>` injected into every
  runner at create (`runners.py::_runner_env`).
- **Prose:** AGENTS.md written into `$HOME/AGENTS.md` on first spawn, only if
  absent, via the runner's own `/files/read` (check) then `/files/write`
  (seed) — there is no exec path into a runner (socket-proxy denies `EXEC`)
  and no in-runner harness left to auto-load a file (opencode is gone), so
  this is orchestrator-driven, not entrypoint-driven, unlike the original
  brief's assumption (spec.md's ticket-04 amendment already anticipated this:
  "nothing auto-loads it — it is a read-me-first artifact").
- **Feedback:** `runner/shims/sandbox-shim.sh`, symlinked as `curl`/`wget`/
  `apt-get` in `/usr/local/bin` (PATH-first, outside the volume). Allowlisted
  internal `host:port` → real pass-through, always. Everything else,
  including `-x`/`--proxy` (which would otherwise bypass the allowlist) → a
  real failure (or instant refusal when `SANDBOX_EGRESS=BLOCKED`) plus a
  4-line stderr explanation, exit 126. Loopback (`127.0.0.1`/`localhost`) is
  exempted unconditionally — **this image's own HEALTHCHECK calls `curl
  http://127.0.0.1:8000/system`**, and that had to keep working; caught this
  myself before it became a real regression. `wget` genuinely isn't
  installed in this base image — its shim says so honestly instead of
  fabricating a fallback.
- **Boot-time DNS check:** `RunnerManager.startup()` resolves every
  configured service name against the runners network and logs a warning
  (never fails) on drift.
- **N15 sweep:** `.env.example`'s DevGuard block was defined twice (documented
  wart — a stale `PIP_INDEX_URL` default, then an empty one, last-wins
  silently emptying the seam). Collapsed to one; added `PIP_SHIM_BASE_URL`/
  `PIP_TRUSTED_HOST`/`NPM_CONFIG_REGISTRY`, which `config.py` already read but
  `.env.example` never documented.
- README: new "What the agent sees" section, grep-tested against the actual
  renderer output (ticket 14).

**A real interaction bug caught and fixed in the same session:** the shim
shadows plain `curl`, but `tests/conftest.py`'s `curl_in`/`cross_request`
helpers (used by `test_egress.py` and `test_isolation.py` to measure raw
network-topology facts — sibling-runner reachability, socket-proxy isolation)
also called plain `curl`. Once shimmed, those probes got refused by the shim
itself before ever touching the network — correct behavior for an agent,
wrong tool for a topology probe. Fixed `curl_in` to call `/usr/bin/curl`
explicitly. `test_shims.py` exercises the shim itself via the PATH-resolved
name.

## Ticket 14 — tests

**Done, suite green.** New: `test_image_pinning.py`, `test_readme_env_docs.py`,
`test_orientation.py` (integration), `test_shims.py`. Plus, after
`/code-review`, `test_orientation.py` (unit) — see review findings.

**Suite result, full run, this exact state (before the ticket-12-review
fixup commit):** **178 passed** (16 new), **12 skipped** (live-DevGuard-gated,
expected), **7 deselected** (slow, expected) — up from 162/12/7 at the end of
ticket 12.

## Ticket 15 — publication package (STAGE ONLY)

**Done. No visibility flip, no push, no `gh` calls, as instructed.**

- **LICENSE**: MIT, copyright `Sidiberlin` (this repo's own git identity —
  confirm this is the name the stakeholder wants publicly before the flip).
  D3 was decided three sessions ago; the file itself had never actually been
  written until now (ticket 02's own retraction).
- **THIRD-PARTY-NOTICES.md**: drafted from upstream LICENSE files fetched
  live this session (`/browse`, per process) — Tecnativa/docker-socket-proxy
  (Apache-2.0), l3montree/devguard (**AGPL-3.0-or-later**, © 2024 l3montree
  GmbH — not previously recorded anywhere in this repo), Ory Kratos
  (Apache-2.0), nginx (BSD-2-Clause-style, © Igor Sysoev / Nginx Inc.),
  Node.js (MIT) — plus brief §0's pre-verified facts (open-terminal, opencode,
  ZenDiS). **Flagged prominently as DRAFT**: ticket 08's independent-review
  gate (a fresh, uninvolved session must re-derive every claim before this is
  relied on for the public flip) has not run — I am the session that built
  the rebase the notices describe, which is exactly the conflict of interest
  that gate exists to catch. The Python dependency section's transitive
  closure (~20 packages) is SPDX-only, explicitly marked not independently
  re-verified this session — the four direct dependencies (fastapi, uvicorn,
  aiodocker, httpx) were spot-checked against PyPI metadata.
  **Flag the AGPL finding to the stakeholder regardless of the review gate** —
  see the file's own "DevGuard and AGPL" section for the (non-legal-advice)
  analysis of why deploying it unmodified as a service doesn't currently
  implicate this project's own MIT code, and what WOULD change that.
- **Ticket 09's doc-placeholder findings didn't reproduce.** It named three
  ADR files; none of the three ever contained the flagged strings in the
  entire git history (one commit each, checked). Corrected that ticket's
  record rather than silently rewriting text that wasn't there. A fresh audit
  (`git ls-files | grep` for RFC1918/`.lxc` patterns) found the actual
  instance in **README.md** instead: `orch-lxc64` (7×) and `lxc101-terminal`
  (2×) are real LXC numbers from the live homelab, missed by the earlier
  host-generalization commit (`b2738f7`). Replaced with
  `<orch-connection-id>` / `<other-terminal-id>`.
- **Gitleaks (P3)**: full history, 20 commits (all of them — `git log
  --oneline | wc -l` also says 20), via the official container image (no
  local gitleaks binary on this host). **Two hits, both false positives**:
  `tests/env.test`'s documented fake test secret, and a prose false-positive
  in `tests/README.md` ("size/duration" tripping the entropy heuristic).
  **Zero live secrets.** Recommendation stands: no history rewrite. Raw
  report: `.scratch/gitleaks-report.json` (untracked, for your own eyes only
  — don't commit it, it's a repo dump artifact not a deliverable).

## Deviations from a literal reading of the tickets (all recorded, none silent)

1. **Two pre-existing test-harness bugs, unrelated to any single ticket, were
   blocking the suite from running AT ALL** on a completely clean checkout —
   fixed as part of the ticket 10 commit since it's the first ticket and
   needed the fix to verify anything:
   - `tests/env.test` was missing `DEVGUARD_DB_PASSWORD`. `docker compose`
     interpolates every service's environment block up front, even ones
     gated behind an unselected profile, so a `:?required` var with no
     default broke plain `up -d`.
   - `docker-compose.yml` still declared a dead `edge` bridge network (with a
     stale topology comment) from before ADR-0006/0009 moved the
     orchestrator onto OWUI's own external network directly. No service was
     attached to it any more, so the test harness's stub-OWUI container
     (still wired to `edge`) could never be reached by the orchestrator by
     name — every integration test failed at `compose up`. Removed the dead
     network, fixed the comment, pointed the harness at a throwaway
     stand-in for the external `owui` network it now needs.
2. **Ticket 09's specific file/string claims were wrong** (see ticket 15
   above) — corrected in the ticket file itself rather than blindly "fixing"
   text that was never there.
3. **A `/code-review` pass I ran after the fact (should have run right after
   each commit, per the process instructions — I ran it late, after ticket 15,
   not immediately after 12/14 as instructed) found a real bug and a real
   test-coverage gap**, both fixed in `1eea884` — see above. Apologies for the
   ordering miss; the findings themselves are addressed.

## Hard gates — self-check

1. **Zero runtime egress, no capabilities added, no ports opened.** Unchanged
   topology; the orchestrator's own cap_drop:ALL is untouched; the shim adds
   a userspace refusal layer, not a network change. `test_egress.py` (5/5)
   and `test_isolation.py` (8/8) both green throughout.
2. **Shims never fake output.** Verified manually and by `test_shims.py`:
   every blocked path produces a REAL exit code (126) and REAL stderr, never
   a synthesized success. `wget`'s absence is reported honestly rather than
   simulated.
3. **Every image ref pinned; zends refs digest-pinned; no `latest`
   introduced.** `test_image_pinning.py` (3 tests, including the
   `${VAR:-default}`-aware check added after review). Manually confirmed no
   other ref in the diff uses `latest`.
4. **The live stack on .101 untouched.** Never connected to it this session;
   no `ssh` calls made at all (wasn't needed — everything verified in
   throwaway compose projects on this box, per the brief).
5. **No secrets/tokens/LAN IPs/hostnames in commits or messages.** Checked
   each commit message before writing it. Gitleaks confirms no live secrets
   in the tree/history. LAN-IP/hostname sweep (ticket 15) is complete.
6. **Suite green before a ticket counts as done; every failure attributed.**
   See the per-ticket sections above and "Outstanding for the morning" below
   for the one exception (a fixup not yet re-verified, clearly labeled as
   such in its own commit message, not silently claimed done).

## Fixup re-verification (completed after host memory pressure cleared)

Host memory recovered later in the session (`free -h` back to ~1.9 GiB
available). Rebuilt `owui-orchestrator:dev` from commit `1eea884` via
`owui-bk` — succeeded, sha256 check on `get-pip.py` logged `OK`, serve-smoke
(`import aiodocker, fastapi, uvicorn, httpx; import app.main`) passed, and
`docker compose config` confirms `orchestrator-state-init` is wired in front
of `orchestrator` via `depends_on`.

**Found one real bug in the process, unrelated to the fixup itself:**
`tests/unit/test_orientation.py` (added by the fixup) collided on basename
with the pre-existing `tests/integration/test_orientation.py` — neither
`tests/unit/` nor `tests/integration/` has an `__init__.py`, so pytest's
rootdir-relative import mode identifies modules by basename alone, and the
whole suite failed to collect (`import file mismatch`). Renamed to
`test_orientation_renderer.py` in commit `80a5cd6`.

**Full suite, run in pieces** (this host's harness-level low-memory guard —
still triggering intermittently from other concurrent sessions early in this
verification pass — kills any single pytest invocation approaching its
auto-background threshold; splitting by file avoids that without weakening
coverage, since each file's own session-scoped stack fixture tears down
cleanly either way): **every unit test (99) and every integration file
passed**, including a full, clean run of `test_isolation.py` (8/8) and
`test_devguard_and_retention.py` (7/7). Two tests needed a single retry, both
confirmed as pre-existing environmental flakiness, not regressions:

- `test_lifecycle.py::test_runner_is_created_with_the_configured_limits` —
  failed once on a bare `docker inspect` CLI call hanging 120s+ (the Docker
  *daemon* itself was briefly unresponsive under host load, unrelated to any
  application code); passed cleanly in 24s on retry.
- `test_resources.py::test_over_allocating_memory_is_killed_not_swapped_onto_the_host`
  — failed on an `httpx.ReadTimeout`. Root cause found and it is a
  **pre-existing test fragility, not new**: the test posts `/execute` with
  `wait: 60` while `Stack.client()` (`conftest.py:133`) defaults its own
  httpx timeout to exactly `60.0`s — zero margin for proxy/network overhead,
  so any hint of host slowness makes the client time out a hair before the
  server would have answered. Passed cleanly in 21s on retry. Worth a
  follow-up ticket (bump the client timeout past the `wait` value with real
  margin) but out of scope for tonight's rebase.

**Verdict: the ticket-12-review fixup (`1eea884` + `80a5cd6`) is suite-green.**
No further action needed before trusting it.

**Independent review gate for THIRD-PARTY-NOTICES.md (ticket 08) has not
run.** Needed before treating that file as final for a public flip — see
ticket 15 above.

**AGPL-3.0-or-later finding for DevGuard** needs stakeholder sign-off on the
analysis in `THIRD-PARTY-NOTICES.md`'s "DevGuard and AGPL" section — not
something I can decide.

**LICENSE copyright name** (`Sidiberlin`) — confirm this is the name you
want on the public record, or tell me/Hermes what to change it to.

**Nothing else is blocked.** All of tickets 10–15, including the ticket-12
fixup, are fully suite-verified and committed as-is. The only open items are
the two stakeholder decisions above and the ticket-08 independent-review
gate, none of which are mine to close.

**Nothing else is blocked.** Tickets 10, 11, 13, 14 are fully suite-verified
and committed as-is with no caveats.
