# Reference: environment variables

Every variable the orchestrator reads, grouped as `.env.example` groups them.
Defaults shown are what the orchestrator falls back to when a variable is
unset or blank — these match `orchestrator/app/config.py`'s `Config.from_env()`
exactly, so a missing var never silently produces different behavior than
what's documented here. Duration values accept a bare number of seconds or a
suffixed string (`30m`, `2h`, `1d`); size values accept a bare byte count or a
suffixed string (`768m`, `4g`).

## Required secrets

| Variable | Default | Effect |
|---|---|---|
| `ORCH_API_KEY` | *(required, no default)* | The bearer key ("K1") Open WebUI's integration sends on every request. Startup fails if unset or still holds the `.env.example` `CHANGEME` placeholder. |
| `ORCH_MASTER_SECRET` | *(required)* | Seed for per-runner Open Terminal key derivation: `key = HMAC-SHA256(ORCH_MASTER_SECRET, uid + ":" + nonce)`. Rotating this invalidates every live runner's key immediately — do it during a quiet window. |
| `OWUI_BASE_URL` | *(required)* | Base URL of your Open WebUI instance, used for `X-User-Id → role` resolution. |
| `OWUI_ADMIN_TOKEN` | *(required)* | Admin credential (API key or session JWT) for the `GET /api/v1/users/{uid}` call. See [How to rotate the OWUI admin key safely](../how-to/rotate-owui-admin-key-safely.md). |

These three secrets must all be **distinct values** — never reuse one for
another.

## Orchestrator bind

| Variable | Default | Effect |
|---|---|---|
| `ORCH_PORT` | `8080` | Port the orchestrator listens on inside its container. |
| `ORCH_BIND` | `0.0.0.0` (compose default `127.0.0.1`) | Host interface the published port binds to. |
| `ORCH_TAG` | `dev` | Image tag for the orchestrator build. |

## Role mapper (fail-closed)

<a id="role-mapper"></a>

| Variable | Default | Effect |
|---|---|---|
| `ROLE_CACHE_TTL` | `60` (seconds) | How long a resolved role/group-membership answer is served from cache before the next request re-fetches from OWUI. **This is also the practical bound on how fast a `GROUP_MAP` membership change takes effect for a given user** — combined with spawn-time binding (a *new* runner is also needed to actually apply a changed profile), the documented, live-verified semantics are: add a user to a mapped group, and their *next spawn* after this many seconds picks up the new profile; remove them, and a spawn within the TTL window still sees the old (cached) group membership. |
| `ROLE_CACHE_GRACE` | `600` (seconds) | If OWUI is unreachable, how long a *stale* cached role is still served before the orchestrator gives up and returns 503. Never "fails open" to a guessed role. |
| `OWUI_API_TIMEOUT` | `5` (seconds) | Hard timeout on each role-lookup call to OWUI's admin API. |

## Runner lifecycle

| Variable | Default | Effect |
|---|---|---|
| `RUNNER_IMAGE` | `owui-agent-runner:dev` | Image tag used for spawned runners (the `default` policy profile's `IMAGE`). |
| `RUNNERS_NETWORK` | `owui-runners-internal` | Docker network name runners attach to. Must be `internal: true` for the zero-egress guarantee to hold; the orchestrator refuses to serve a runner that ends up on any other/additional network. |
| `RUNNER_CPUS` | `1.5` | CPU limit per runner (fractional cores), for users under the `default` profile. |
| `RUNNER_MEMORY` | `1g` (compose default `768m`) | Memory limit per runner, for users under the `default` profile. |
| `RUNNER_PIDS` | `256` | `PidsLimit` on each runner container. |
| `MAX_CONTAINERS` | `6` (compose default `3`) | Hard ceiling on concurrently live runners. This, times `RUNNER_MEMORY`, is the deterministic memory bound the orchestrator actually enforces — not any `/proc/meminfo` reading. |
| `IDLE_TIMEOUT` | `30m` | How long a runner may go with no request **and** no running process before the idle sweep tears it down. Worst-case teardown latency is `IDLE_TIMEOUT + IDLE_SWEEP_INTERVAL`. |
| `RUNNER_SECURITY_OPT` | `no-new-privileges,apparmor=unconfined` | Comma-separated Docker `security_opt` list applied to every runner. Drop `apparmor=unconfined` only on a host where `docker-default` actually loads. |
| `RUNNER_CAP_ADD` | `CHOWN,DAC_OVERRIDE,FOWNER,SETUID,SETGID` | Capabilities added back after `cap_drop: [ALL]`. Needed for the entrypoint's root→`gosu`-drop sequence; trimming this breaks both the ownership fix and the privilege drop. |

## Disk

| Variable | Default | Effect |
|---|---|---|
| `RUNNER_DISK_SOFT` | `5g` | Above this, new spawns for that user are refused. Detected by polling, not a kernel quota. |
| `RUNNER_DISK_HARD` | `6g` | Above this, a *running* container is stopped. |
| `WORKSPACE_TOTAL_CEILING` | `60g` | Aggregate ceiling across every user's workspace, enforced at admission — once reached, new spawns get a clean 429 instead of filling the host. |
| `DISK_POLL_INTERVAL` | `60` (seconds) | How often disk usage is polled. Lower = smaller race window for a fast writer, more polling load. |
| `VOLUME_RETENTION_DAYS` | `0` | Days of inactivity before a user's workspace volume is deleted by the retention sweep. **`0` disables deletion entirely** — this destroys user data, so enabling it is an explicit opt-in. |
| `RETENTION_SWEEP_INTERVAL` | `3600` (seconds) | How often the retention sweep runs, when enabled. |
| `IDLE_SWEEP_INTERVAL` | `30` (seconds) | How often the idle-runner sweep runs. |

## Per-role policy

| Variable | Default | Effect |
|---|---|---|
| `ADMIN_RUNNER_CPUS` | *(blank → same as `RUNNER_CPUS`)* | CPU limit for `admin`-role users. Blank means admins get exactly user-level limits — a safe default so "admins get more" is opt-in, not an accidental capacity hole. |
| `ADMIN_RUNNER_MEMORY` | *(blank → same as `RUNNER_MEMORY`)* | Memory limit for `admin`-role users. |
| `ADMIN_RUNNER_DISK_SOFT` | *(blank → same as `RUNNER_DISK_SOFT`)* | Disk soft limit for `admin`-role users. |

These apply only when a caller's resolved policy profile is the implicit
`default` — a real mapped policy profile's `CPUS`/`MEMORY` fully replace
role-derived limits (admin or not). See
[How to create a policy profile](../how-to/create-a-policy-profile.md).

## Policy profiles (ADR-0012)

<a id="policy-profiles-adr-0012"></a>

| Variable | Default | Effect |
|---|---|---|
| `POLICY_<NAME>_CPUS` | *(inherits `RUNNER_CPUS`)* | CPU override for the named profile. |
| `POLICY_<NAME>_MEMORY` | *(inherits `RUNNER_MEMORY`)* | Memory override. |
| `POLICY_<NAME>_IDLE_TIMEOUT` | *(inherits `IDLE_TIMEOUT`)* | Idle-timeout override; this is what the runner was **created under** and is compared against for the life of that container, not re-read live from config on every sweep. |
| `POLICY_<NAME>_EXEC_TIMEOUT` | *(inherits `OPEN_TERMINAL_EXECUTE_TIMEOUT`)* | Per-runner `OPEN_TERMINAL_EXECUTE_TIMEOUT` override. |
| `POLICY_<NAME>_IMAGE` | *(inherits `RUNNER_IMAGE`)* | Image tag override. |
| `POLICY_<NAME>_EGRESS` | *(inherits `BLOCKED`)* | Value written to the runner's `SANDBOX_EGRESS` env var. **Changes shim retry-timing text shown to the agent only — never opens real network access.** See [Explanation](../explanation/sandbox-and-spawn-time-binding.md). |
| `GROUP_MAP` | *(blank)* | Ordered, comma-separated `groupname:profile` list. First match (left to right) wins; no match falls back to `default`. Blank is a byte-for-byte no-op. |

`<NAME>` is case-insensitive and reserved word `default` cannot be
redeclared (`POLICY_DEFAULT_*` is a startup error). Full grammar and a worked
example in [How to create a policy profile](../how-to/create-a-policy-profile.md).

## Proxy

| Variable | Default | Effect |
|---|---|---|
| `PROXY_DENY_PREFIXES` | `/proxy,/ports,/api/terminals` | Path prefixes the orchestrator refuses with 403 rather than forwarding to the runner. Everything **not** listed here is forwarded verbatim — this is a denylist, not an allowlist, by design (see [Explanation](../explanation/sandbox-and-spawn-time-binding.md)). |
| `FILES_SERVE_CSP` | `sandbox` | `Content-Security-Policy` value injected on `/files/serve` responses, mitigating a verified stored-XSS path through agent-authored HTML. Set to empty to disable (unsafe — previews with JS would then work). |

## Open Terminal containment (pushed into each runner)

| Variable | Default | Effect |
|---|---|---|
| `OPEN_TERMINAL_MAX_SESSIONS` | `8` | Max concurrent Open Terminal sessions per runner. |
| `OPEN_TERMINAL_EXECUTE_TIMEOUT` | `120` (seconds) | Default `/execute` timeout, overridden per-runner by a resolved profile's `EXEC_TIMEOUT` when one applies. `POST /execute` is synchronous — this bounds how long one proxied request can occupy the connection. |
| `OPEN_TERMINAL_SESSION_CWD_TTL` | `604800` (seconds = 7 days) | How long Open Terminal remembers a session's working directory. |

`OPEN_TERMINAL_ALLOWED_DOMAINS` is deliberately never set by this
orchestrator — see [Reference: runner environment](runner-environment.md).

## Package Seam (ADR-0008)

| Variable | Default | Effect |
|---|---|---|
| `DEVGUARD_ENABLED` | `false` | When `true`, derives `PIP_INDEX_URL`, `PIP_TRUSTED_HOST` and `NPM_CONFIG_REGISTRY` from `DEVGUARD_BASE_URL`/`PIP_SHIM_BASE_URL` if those are otherwise blank. An explicit value for any of the three always wins over the derived one. |
| `DEVGUARD_BASE_URL` | `http://devguard-api:8080` | DevGuard API base URL; drives the derived npm registry. |
| `PIP_SHIM_BASE_URL` | `http://pip-shim:8080` | pip-shim base URL; drives the derived pip index (pip needs the rewriting shim — npm does not; see ADR-0010). |
| `PIP_INDEX_URL` | *(blank)* | Explicit override, injected into every runner at create time. |
| `PIP_TRUSTED_HOST` | *(blank, auto-derived from `PIP_INDEX_URL`'s host when DevGuard is enabled)* | Must name the host pip actually contacts (the shim), or pip refuses the plain-HTTP index. |
| `NPM_CONFIG_REGISTRY` | *(blank)* | Explicit override for npm's registry. |

## DevGuard platform (ADR-0007, `--profile devguard`)

| Variable | Default | Effect |
|---|---|---|
| `DEVGUARD_VERSION` | `v1.14.0` | Image tag for all DevGuard services. |
| `DEVGUARD_DB_PASSWORD` | *(required for the `devguard` profile)* | Postgres password shared by DevGuard and Kratos. |
| `DEVGUARD_PROXY_CACHE_MB` | `2048` | Dependency-proxy cache size. |
| `DEVGUARD_API_MEMORY` / `DEVGUARD_API_GOMEMLIMIT` | `2048m` / `1024MiB` | DevGuard API container memory cap / Go runtime memory limit. |
| `DEVGUARD_PG_MEMORY` | `512m` (see caveat) | Postgres memory cap. **The vulndb import needs ≥4GB** (`DEVGUARD_PG_MEMORY=4096m`) — at the default, the import is OOM-killed partway through. |
| `DEVGUARD_KRATOS_MEMORY` / `DEVGUARD_WEB_MEMORY` | `256m` / `256m` | Memory caps for the remaining DevGuard services. |
| `DEVGUARD_KRATOS_LOG_LEVEL` | `warning` | Kratos log verbosity. |
| `DEVGUARD_ENVIRONMENT` | `prod` | DevGuard's own environment label. |
| `DEVGUARD_API_URL` / `DEVGUARD_FRONTEND_URL` / `DEVGUARD_INSTANCE_DOMAIN` | `http://devguard-api:8080` / `http://devguard-web:3000` / `http://devguard-api:8080` | Internal URLs DevGuard advertises to itself. Not published on the LAN by operator decision (ADR-0009). |

## Plumbing

| Variable | Default | Effect |
|---|---|---|
| `MEMORY_RESERVE` | `512m` | Memory left free on the host after admitting a runner, used only when `MEMORY_GATE` is on. |
| `MEMORY_GATE` | `off` | Free-memory admission gate. **Off by default** — inside Docker-on-LXC, `/proc/meminfo` under-reports by over a gigabyte, and this gate would refuse users while the host has plenty free. Turn on only on a full VM where `/proc/meminfo` is accurate. |
| `RUNNER_MEMORY_BUDGET` | *(blank → bounded only by `MAX_CONTAINERS × RUNNER_MEMORY`)* | Optional hard ceiling on total committed runner memory. |
| `RUNNER_VERSION` | `1` | Bump this to make every existing runner reapable on the next orchestrator restart — the mechanism for rolling out a new runner image without orphaning containers. |
| `DOCKER_API_VERSION` | `v1.44` | Docker Engine API version the orchestrator negotiates. Only change if the daemon's `MinAPIVersion` changes. |
| `LOG_LEVEL` | `INFO` | Orchestrator log verbosity. |
| `OWUI_NETWORK` | `open-webui_default` | Name of Open WebUI's own Docker network, which the orchestrator joins so OWUI can reach it by container name. |

## Related

- [Reference: `/_orch/*` endpoints](orch-endpoints.md) — where several of these knobs surface at runtime.
- [Reference: runner environment](runner-environment.md) — what actually gets injected *into* a runner, as opposed to what configures the orchestrator.
- [How to create a policy profile](../how-to/create-a-policy-profile.md) and [How to deploy on a fresh LXC](../how-to/deploy-on-a-fresh-lxc.md) for these knobs in context.
