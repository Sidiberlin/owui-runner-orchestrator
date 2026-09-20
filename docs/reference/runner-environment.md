# Reference: runner environment

Every environment variable the orchestrator injects into a runner container
at creation time (`orchestrator/app/runners.py:_runner_env`). None of these
are set by the runner image itself at build time except as inert defaults —
the orchestrator always overrides them per-runner.

## SANDBOX_* — agent orientation (the "data channel")

These exist so the driving agent (the LLM in the OWUI chat) understands its
own environment without guessing from failed network calls. See
[Explanation](../explanation/sandbox-and-spawn-time-binding.md) for why this
exists at all.

| Variable | Values | Meaning |
|---|---|---|
| `SANDBOX_MODE` | always `air-gapped` | Describes the network **topology** — `internal: true`, no capabilities added. Constant across every policy profile; per-profile networking is out of scope for this version. |
| `SANDBOX_EGRESS` | `BLOCKED` (default profile) or whatever a mapped profile's `EGRESS` field is set to | **Not a real network permission.** It only changes the sandbox shim's timing: `BLOCKED` refuses instantly with no network touched; any other value lets the shim attempt the real call for up to 2 seconds before failing the same way. Every value, including anything a policy profile sets, results in the same outcome — no route out — because the network topology (`internal: true`) enforces that regardless of this variable. |
| `SANDBOX_INTERNAL_SERVICES` | `name:port=description,...` comma-joined, or empty | Every internal service this runner can actually reach. Empty unless `DEVGUARD_ENABLED=true`, in which case it lists `devguard-api:8080=package proxy: pip/npm packages, malware-checked`. The exact same list also renders into `AGENTS.md` (see below) — one source of truth (`orchestrator/app/orientation.py:sandbox_services`), so the two can never disagree. |

A runner always has all three set, even with an empty services list — an
agent running `env | grep SANDBOX` should never find nothing.

## AGENTS.md — the prose channel

Seeded into the workspace root (`/home/user/AGENTS.md`) on first spawn,
**only if the file is absent** — a user's own file, or one deeper in their
project, is never touched, and nothing auto-loads it; it's a read-me-first
artifact for the agent, not something wired into the toolchain. Written
through the runner's own `/files/write` API (there's no exec path into a
runner from the orchestrator side — the socket proxy denies `EXEC`), so a
failure to seed it is logged and never blocks the spawn.

Content: states the runner is air-gapped by design, that pip/npm already
work through `$PIP_INDEX_URL`/`$NPM_CONFIG_REGISTRY`, lists the same
`SANDBOX_INTERNAL_SERVICES` entries in prose, and describes the current
profile's egress behavior in one sentence (the same "instant refusal" vs.
"attempt then fail" distinction as `SANDBOX_EGRESS` above, in words instead
of a flag).

## Open Terminal containment knobs (pushed at create time)

| Variable | Source | Meaning |
|---|---|---|
| `OPEN_TERMINAL_API_KEY` | Derived per-runner (`HMAC-SHA256(ORCH_MASTER_SECRET, uid:nonce)`) | The credential this specific runner's Open Terminal server checks incoming requests against. Never the orchestrator's own `ORCH_API_KEY`. Rotates on every respawn. |
| `OPEN_TERMINAL_MULTI_USER` | always `false` | One user per container by design — Open Terminal's own multi-user account provisioning would shell out to `sudo`, which this image doesn't ship. |
| `OPEN_TERMINAL_FILE_BROWSER_ROOT` | always `home` | Sidebar file browser roots at `$HOME`, i.e. the mounted persistent volume — see ADR-0004. |
| `OPEN_TERMINAL_MAX_SESSIONS` | `OPEN_TERMINAL_MAX_SESSIONS` env (global) | Passed straight through; not currently profile-tunable. |
| `OPEN_TERMINAL_EXECUTE_TIMEOUT` | The resolved policy profile's `EXEC_TIMEOUT` (rounded to the nearest second), or the global default | Bounds how long one `/execute` call may run before Open Terminal itself cuts it off. |
| `OPEN_TERMINAL_SESSION_CWD_TTL` | `OPEN_TERMINAL_SESSION_CWD_TTL` env (global) | How long a session's working directory is remembered; not currently profile-tunable. |

`OPEN_TERMINAL_ALLOWED_DOMAINS` is **deliberately never set**. Setting it —
even to an empty string — activates the base image entrypoint's
`iptables`/`dnsmasq` firewall, which needs `CAP_NET_ADMIN`, a capability this
orchestrator does not grant any runner. The `internal: true` network is the
actual, stronger control; this variable would only add a redundant,
capability-hungry layer on top of it.

## Package Seam (ADR-0008)

| Variable | Present when | Meaning |
|---|---|---|
| `PIP_INDEX_URL` | `PIP_INDEX_URL` is non-empty (directly, or derived when `DEVGUARD_ENABLED=true`) | pip's package index. Points at `pip-shim`, not DevGuard directly — see ADR-0010 for why pip needs a rewriting hop that npm does not. |
| `PIP_TRUSTED_HOST` | Same condition, when a host is resolved | The host pip actually contacts (the shim), required for pip to accept a plain-HTTP index. |
| `NPM_CONFIG_REGISTRY` | `NPM_CONFIG_REGISTRY` is non-empty | npm's registry, pointed straight at DevGuard — npm's own `replace-registry-host` default rewrites the tarball host for you, so no shim is needed on this side. |

None of these three are set at all when the Package Seam is unconfigured —
there is no second, forgotten path by which a runner could reach a public
registry; the seam is the only one.

## What is NOT injected (and why)

- **No egress-opening variable of any kind.** Nothing in this list, at any
  policy profile's settings, opens a route to the public internet. The only
  network a runner is ever attached to is `RUNNERS_NETWORK`
  (`internal: true`), asserted at spawn time
  (`RunnerManager._assert_single_network`) — a runner that ends up on more
  than exactly that one network is refused rather than served.
- **No secret shared across runners.** Every runner's `OPEN_TERMINAL_API_KEY`
  is unique and derived fresh per spawn; a runner can read its own
  environment (any process inside it can), so a shared key would be
  readable by every runner (ADR-0002).

## Related

- [Reference: environment variables](environment-variables.md) for what configures the *orchestrator's* side of these values.
- [Reference: `/_orch/*` endpoints](orch-endpoints.md).
- [Explanation: why runners can't reach the internet](../explanation/sandbox-and-spawn-time-binding.md).
- `runner/shims/sandbox-shim.sh` and `orchestrator/app/orientation.py` for the exact implementation these values feed.
