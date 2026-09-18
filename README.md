# OWUI Agent Runner Orchestrator

Per-user ephemeral coding-agent containers driven by Open WebUI's native
Open Terminal integration. Self-hosted replacement for the Enterprise-licensed
"Terminals" orchestrator.

Decision records: [`docs/adr/`](docs/adr/) · glossary: [`CONTEXT.md`](CONTEXT.md).

## Status

| Lane | Contents | State |
|------|----------|-------|
| A | `runner/Dockerfile` | **done, built and functionally tested** |
| D | `docker-compose.yml`, `.env.example`, networks, socket proxy | **done, validated** |
| B | `orchestrator/` lifecycle, volumes, quota, keys, reconciliation | **done, built and verified end to end** |
| C | `orchestrator/` proxy router, auth, role mapper | **done, built and verified** |
| E | `tests/` | **done — 120 tests, 57 unit + 63 integration** |
| — | Live OWUI integration | **verified end to end against OWUI .101 (v0.11.1)** |

`docker compose up` brings up a complete, OWUI-drivable orchestrator. Fill in
`OWUI_BASE_URL` and `OWUI_ADMIN_TOKEN`, point OWUI at it, and it works end to end.

Resource limits are already sized to this host (N13): `MAX_CONTAINERS=3`,
`RUNNER_MEMORY=768m`. The briefed 6 x 1g did not fit in the measured 0.6-2.1 GiB
available and every spawn was refused with a 429.

## Bring-up

```bash
cp .env.example .env
# fill the four secrets:  openssl rand -hex 32
docker compose --profile build build runner-image   # builds owui-agent-runner
docker compose config                               # validate
docker compose up -d                                # socket proxy + orchestrator
```

## Routes

Everything the orchestrator owns lives under `/_orch/`. The entire rest of the
URL space is proxied verbatim to the user's runner. That prefix is reserved so
an orchestrator route can never shadow an upstream Open Terminal path (N17).

```bash
K=$(grep ^ORCH_API_KEY= .env | cut -d= -f2)
curl -s localhost:8080/_orch/healthz                              # unauthenticated
curl -s -H "Authorization: Bearer $K" localhost:8080/_orch/status
curl -s -H "Authorization: Bearer $K" localhost:8080/_orch/runners
curl -s -X DELETE -H "Authorization: Bearer $K" localhost:8080/_orch/runners/<uid>

# user traffic: K1 + X-User-Id, exactly as OWUI sends it
curl -s -H "Authorization: Bearer $K" -H "X-User-Id: <owui-user-id>" \
     -H "X-Session-Id: <chat-id>" localhost:8080/system
```

`/proxy`, `/ports` and `/api/terminals` return 403 by design (Q5). Everything
else reaches the runner, including all five `/execute` endpoints.

## Live OWUI integration (verified 2026-09-17)

Wired to the real instance at `http://<owui-host>` (v0.11.1) as a
**system-level** connection. The whole chain is proven on the wire:

```
user JWT -> OWUI backend -> /api/v1/terminals/orch-lxc64/<path>
         -> orchestrator (K1 + X-User-Id) -> per-user runner
```

### Configure it entirely over the API

The Admin UI is not required. OWUI exposes the integration config directly:

```bash
T=<owui admin jwt>          # never echo these
K=$(grep ^ORCH_API_KEY= .env | cut -d= -f2)
O=http://<owui-host>

# 1. confirm OWUI can reach and classify this orchestrator
curl -s -X POST -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
  -d "{\"url\":\"http://<orch-host>:8080\",\"key\":\"$K\",\"auth_type\":\"bearer\"}" \
  "$O/api/v1/configs/terminal_servers/verify"
# -> {"status":true,"type":"terminal"}

# 2. read the current list, append this orchestrator, POST the whole list back
curl -s -H "Authorization: Bearer $T" "$O/api/v1/configs/terminal_servers"
# POST /api/v1/configs/terminal_servers with
#   {"TERMINAL_SERVER_CONNECTIONS":[ ...existing..., {
#      "id":"orch-lxc64","name":"Runner Orchestrator","enabled":true,
#      "url":"http://<orch-host>:8080","key":"<ORCH_API_KEY>",
#      "auth_type":"bearer","server_type":"terminal","path":"/openapi.json",
#      "config":{"access_grants":[]},"policy_id":null }]}
```

**The POST replaces the entire list** — read it first and append, or you will
delete every other terminal server the instance has.

### Exercise it as a user

```bash
curl -H "Authorization: Bearer $T" "$O/api/v1/terminals/orch-lxc64/system"
curl -H "Authorization: Bearer $T" "$O/api/v1/terminals/orch-lxc64/files/list?path=."
```

OWUI's backend adds `X-User-Id` (and `X-Session-Id` when a chat is in scope)
and the connection's bearer key. Verify on this box with
`docker compose logs orchestrator` — each proxied call logs
`METHOD /path uid=<owui user id> role=<role> -> <runner>`.

### What had to change to make the first live connection work

Four fixes, none of which the stub suite could have surfaced:

| Fix | Why |
|---|---|
| `GET /api/config` discovery probe | OWUI's `verify` calls the server with the key but **no `X-User-Id`**. Both probe paths hit the `X-User-Id` requirement and 400'd, so OWUI reported *"Failed to connect to the terminal server"*. |
| Advertise `terminal: false` | Open Terminal answers `{"features":{"terminal":true,…}}`. `terminal` means the PTY widget backed by `/api/terminals`, which the Q5 denylist blocks — copying it verbatim would render a pane that 403s. The advertisement is derived from the denylist so it stays true. |
| Answer only `/api/config`, never `/api/v1/policies` | OWUI probes `/api/v1/policies` first; a 2xx there makes it classify the server as an **enterprise orchestrator** and drive it with the policy/lifecycle API this v1 does not implement. Presenting as one plain terminal is the design. |
| `Content-Security-Policy: sandbox` on `/files/serve` | See Accepted Risks / closed risks below. |

Plus two smaller ones: proxied requests are now logged (there was no
operational visibility at all), and the runner's role is carried on a label so
an adopted runner still reports the role it was created under instead of
silently becoming `user` after a restart.

## Live operation

Verified against OWUI **v0.11.1** on the private deployment host. Everything here was
measured on the wire, not inferred.

### Configured connections

| id | url | origin |
|---|---|---|
| `orch-lxc64` | `http://<orch-host>:8080` | created during the original integration — **URL now historical, see below** |
| `lxc101-terminal` | `http://open-terminal:8000` | pre-existing, untouched |

> **Consolidated onto one host (ADR-0006).** The orchestrator no longer runs
> on the original build host; that stack was torn down after its workspace volumes were
> migrated. Everything now runs on the OWUI host, where OWUI reaches the
> orchestrator over the shared `owui` network by name
> (`http://orchestrator:8080`) with no LAN hop and no published port. The
> connection's stored URL is repointed separately from this repo — the old
> address above is kept only so the original integration record still reads
> correctly. The `id` is unchanged, so the route prefix below still applies.

`orch-lxc64`'s stored key matches this repo's `.env` `ORCH_API_KEY`. The
`lxc101-terminal` entry is a separate plain Open Terminal on the OWUI host and
has nothing to do with this stack — it is listed only so nobody deletes it.
**`POST /api/v1/configs/terminal_servers` replaces the whole list**: read,
append, write back.

### How OWUI verifies us — and what it does *not* probe

```
POST /api/v1/configs/terminal_servers/verify  ->  {"status":true,"type":"terminal"}
```

The probe order is `GET /api/v1/policies` (→ classify as enterprise
orchestrator) then `GET /api/config` (→ classify as plain terminal). It accepts
anything `resp.ok`, i.e. **status < 400**.

> **The connection's `path: "/openapi.json"` field is NOT the probe path.**
> It is an inert attribute inherited from the tool-server schema. Our
> `/openapi.json` returns **400** with the key and **401** without — neither is
> `resp.ok` — so it cannot be what satisfies verify. Verify passes because we
> answer `/api/config` with 200. Proof: before `/api/config` was implemented,
> verify returned *"Failed to connect to the terminal server"* while
> `/openapi.json` behaved exactly as it does now.

Two rules follow, and both are load-bearing:

- **Do not delete the `/api/config` handler.** It is the entire reason the
  integration verifies. It answers without `X-User-Id` because OWUI's probe has
  no user in scope yet.
- **Do not enable FastAPI's docs/OpenAPI** (`docs_url`/`openapi_url` stay
  `None`). Not because verify needs them — it does not — but because this app
  is reachable from the runners network, where hostile agent code runs. It must
  not publish its own schema there.

We also deliberately never answer `/api/v1/policies` with a 2xx: that would
make OWUI drive us with the enterprise policy/lifecycle API this build does not
implement.

### Chain proven live

| Route (all via `/api/v1/terminals/orch-lxc64/…`) | Result |
|---|---|
| `GET /system` | 200, real runner prompt; **~6-7s cold start**, ~60ms warm |
| `POST /execute` | exit 0, runs as `user` in `/home/user` |
| `POST /files/write` → `GET /files/read` → `GET /files/list` | all 200 |
| `GET /files/serve/...` | 200 + `Content-Security-Policy: sandbox` |
| `/proxy`, `/ports`, `/api/terminals` | 403 from **our** layer |

Written files land in `/home/user`, which is the persistent volume. Runner
containers are named `runner-<owui-user-uuid>` — the deterministic-name rule
(A5) applied to the uid OWUI puts on the wire.

### The filesystem layout is intentional — do not "fix" it

**The volume mounts at `/home/user`. `/workspace` does not exist.** This is
Q2 variant **C**, not the originally-specified A, and it is deliberate:

- `entrypoint-slim.sh` **hardcodes `HOME=/home/user`** (N7). A volume at
  `/workspace` would be silently bypassed — the agent's real state, including
  openCode's own config and auth, would land on the ephemeral layer and be
  destroyed on teardown.
- `OPEN_TERMINAL_FILE_BROWSER_ROOT=home`, so the **sidebar root is the volume**.
- `WORKDIR /home/user` (N10) makes relative-path writes work. The base image
  sets `WorkingDir=/app`, which is root-owned, so without this every relative
  `files/write` failed `Permission denied` while absolute paths worked — a
  silent half-broken state.

Anyone "restoring" `/workspace` to match the original spec reintroduces silent
data loss on teardown. The persistence test guards this.

### Ops: the admin token expires

`ENABLE_API_KEY` is **disabled** on this instance:

```
POST /api/v1/auths/api_key  ->  403
{"detail":"API key creation is not allowed in the environment."}
```

So `OWUI_ADMIN_TOKEN` is a **session JWT** (HS256, claims `exp/iat/id/jti`),
not a durable API key. Measured expiry: **2026-10-16 10:54:31 UTC**.

**When it expires, role resolution fails closed and every user gets 503** —
by design (A8), but it will look like a total outage. Pick one:

1. **Enable API keys** on OWUI and swap in a non-expiring key. Preferred.
2. **Refresh the JWT** before expiry:

```bash
curl -s -X POST -H 'Content-Type: application/json'   -d '{"email":"<service-account>","password":"<password>"}'   "$O/api/v1/auths/signin"
# take .token, rewrite OWUI_ADMIN_TOKEN in .env, then:
docker compose up -d orchestrator
```

Check remaining life by decoding the `exp` claim. Put a reminder in before
2026-10-16.

### Ops: size IDLE_TIMEOUT against your longest command

`POST /execute` is **synchronous** — the documented `wait` parameter does not
cap it, and `GET /execute/{id}/status` blocks until completion too (N20). An
agent tool call therefore occupies the request for the full command duration,
bounded by `OPEN_TERMINAL_EXECUTE_TIMEOUT` (**default 120s**).

**`IDLE_TIMEOUT` must comfortably exceed your longest expected command.** The
in-flight guard stops the sweep reclaiming a runner mid-call, but a timeout
shorter than real work still churns containers pointlessly. See the Runbook for
the measurements.

## Runbook

### Reading `/_orch/status`

```bash
K=$(grep ^ORCH_API_KEY= .env | cut -d= -f2)
curl -s -H "Authorization: Bearer $K" localhost:8080/_orch/status
```

Two memory numbers, and they will not agree:

| Field | Meaning |
|---|---|
| `committed_memory_mb` | What the orchestrator has actually promised the kernel: the sum of live runners' limits. **This is the number to trust.** |
| `host_memory_available_mb` | `MemAvailable` as read from inside the container. Diagnostic only. |

They diverge badly on this host class. Measured simultaneously on the LXC box:
the host reported **1908 MiB** available while the orchestrator container's own
`/proc/meminfo` reported **534 MiB** — `/proc` is virtualised inside
Docker-on-LXC and under-reports by over a gigabyte.

An admission gate built on that reading refuses users while the host has
gigabytes free, so it is **off by default** (`MEMORY_GATE=off`). The real bound
is `MAX_CONTAINERS x RUNNER_MEMORY`, which is deterministic. Turn the gate on
only on a full VM where `/proc/meminfo` is accurate. If users report spurious
429s, check `memory_gate_enabled` first.

### Sizing `IDLE_TIMEOUT` against command length

`POST /execute` is **synchronous** and the documented `wait` parameter does not
cap it. Measured directly against the runner:

```
sleep 30, wait=0   -> 200 in 30.05s      echo quick, wait=1 -> 200 in 0.01s
sleep 30, wait=1   -> 200 in 30.01s
sleep 30, omitted  -> 200 in 30.03s
```

`GET /execute/{id}/status` behaves the same way — it blocks until the process
completes rather than polling for new output, so it can only be asked about a
process that has already finished. A process blocked on stdin finishes only
once stdin arrives.

Consequences:
- An agent tool call blocks for the entire command duration, bounded by
  `OPEN_TERMINAL_EXECUTE_TIMEOUT` (default 120s).
- **`IDLE_TIMEOUT` must comfortably exceed your longest expected command.**
- A long build holds the proxied request open the whole time, which is why the
  in-flight guard below is load-bearing rather than a rare-race nicety.

### Teardown and in-flight requests

A runner is idle only when **both** hold: no request for `IDLE_TIMEOUT`, and
`GET /execute` reports no running process. On top of that, any runner with a
request in flight (`in_flight > 0`) is skipped by the sweep entirely — without
that, the sweep could tear a runner down between admission and connection and
hand the user a 502 mid-call.

Worst-case teardown latency is `IDLE_TIMEOUT + IDLE_SWEEP_INTERVAL`.

A runner that is genuinely running a runaway process is never reclaimed by
design. `RUNNER_CPUS` caps the damage; `DELETE /execute/{id}` is the kill
switch. The sweep logs it rather than killing work that may be real.

### Phantom slots

If users get *"all N runner slots are in use"* while `docker ps` shows fewer
containers, a runner died out of band (OOM kill, crash, manual `docker rm`).
Entries like that are pruned before admission and on every idle sweep, so the
slot returns within one sweep. `/_orch/runners` is the authority on what the
orchestrator believes; `docker ps --filter label=io.owui.runner.managed=1` is
the ground truth. A persistent disagreement between them is a bug.

### Running two stacks on one host

Runners are stamped `io.owui.runner.network=<runners network>` and each
orchestrator only reconciles or adopts its own. This is load-bearing: before it
existed, a second orchestrator adopted the other's runners and reaped them under
its own `IDLE_TIMEOUT`, killing live sessions (N27). If you run a second stack,
give it a distinct `RUNNERS_NETWORK` — the compose default already does.

A runner with **no** owner label is treated as legacy and reaped so a labelled
one replaces it. Workspace volumes are untouched.

### Dependency installs without egress (the DevGuard Package Seam)

Runners have zero egress, so `pip install` and `npm install` cannot reach
PyPI or npmjs. `PIP_INDEX_URL` and `NPM_CONFIG_REGISTRY` are injected into
every runner at **create time** — empty by default, so the seam is inert until
you turn DevGuard on. They are reachable because DevGuard sits inside the
isolated network, not because the network was loosened. **No egress hole is
ever opened.** Changes take effect on each runner's next spawn.

Turn it on with one variable:

```
DEVGUARD_ENABLED=true
```

Both URLs are then derived, and both are verified live rather than taken from
upstream's docs:

| | URL | |
|---|---|---|
| npm | `http://devguard-api:8080/api/v1/dependency-proxy/npm` | straight to DevGuard |
| pip | `http://pip-shim:8080/api/v1/dependency-proxy/pypi/simple` | via the shim (ADR-0010) |

**Why pip takes a detour and npm does not.** DevGuard serves both registries'
metadata verbatim, so npm's `dist.tarball` still points at
`registry.npmjs.org` and PyPI's index links still point at
`files.pythonhosted.org` — neither resolvable from a runner. npm rescues
itself: its `replace-registry-host` default rewrites that host onto the
configured registry, landing exactly on DevGuard's tarball route. pip has no
equivalent and follows the links literally, so the index resolves and every
download dies in DNS. `pip-shim` rewrites those links onto DevGuard's own
`pypi/packages` route. Consequences worth knowing:

- Setting `replace-registry-host=never` in a runner breaks npm installs.
- Pointing `PIP_INDEX_URL` straight at `devguard-api` looks like it works —
  metadata resolves — and then downloads nothing.
- `PIP_TRUSTED_HOST` must name the host pip actually contacts (the shim), or
  pip refuses the plain-http index.

### Bringing DevGuard up

Order matters, and compose enforces it — the API auto-creates a `casbin_rule`
table if it starts first, after which the migration chain cannot proceed
without dropping it.

```
docker compose --profile devguard up -d
```

That runs postgres → kratos-migrate → devguard-migrate →
encryption-migration → cache-init → api, kratos, web, pip-shim.

**The firewall blocks nothing until you import the feed.** A fresh install has
an empty `malicious_packages` table, and an empty table looks exactly like a
working firewall from the outside. Import it:

```
docker compose --profile devguard --profile devguard-import \
  run --rm devguard-vulndb-import
```

Notes, all measured:

- **It is all-or-nothing.** `--limitedToTables=malicious_packages` looks like
  it would import just the feed; the flag is plumbed through and then only
  logged. It filters nothing. Expect the whole vulndb: ~13M rows, 3.6GB of
  database, about 7½ minutes.
- **Postgres needs ≥4GB for it.** At 512m the backend is OOM-killed partway
  through (`terminated by signal 9`). `DEVGUARD_PG_MEMORY` defaults to 4096m.
- The import service carries its own `/tmp` volume and `FRONTEND_URL`; the
  image is distroless, so without them the import dies on `stat /tmp` or
  panics with `FRONTEND_URL is not set`.
- Re-run it periodically — the feed is only as current as the last import.

Check it took:

```
docker compose --profile devguard exec devguard-postgres \
  psql -U devguard -d devguard -tAc 'SELECT count(*) FROM malicious_packages'
```

### Verifying the seam actually works

Assertions, not assumptions. Against a host running the devguard profile:

```
cd tests
DEVGUARD_LIVE=1 ORCH_BASE_URL=http://127.0.0.1:8080 \
ORCH_API_KEY=... SEAM_UID=<an Open WebUI user id> \
  ./.venv/bin/python -m pytest integration/test_package_seam.py
```

That spawns a real runner and checks a benign pip and npm install both
succeed, a flagged package is refused by the firewall in both ecosystems, the
feed is non-empty, and `1.1.1.1`, `registry.npmjs.org` and
`files.pythonhosted.org` all remain unreachable from inside the runner.

### Workspace retention (R2)

Two independent controls:

| Knob | Effect |
|---|---|
| `WORKSPACE_TOTAL_CEILING` | Enforced at **admission**. Once the known total reaches it, new spawns get a clean **429** rather than filling the host. |
| `VOLUME_RETENTION_DAYS` | Periodic sweep deleting workspaces for users inactive beyond it. **`0` = never delete (default).** |

Retention is off by default because it destroys user data. When enabled, the
sweep has three guards and logs every deletion with the uid, idle days and size:

1. Scoped to this orchestrator's `RUNNERS_NETWORK` — it can never touch another
   stack's volumes (see N27 for why that guard is not theoretical).
2. Never a uid with a live runner.
3. Never a uid it has no activity record for — it starts that uid's clock and
   skips. A fresh orchestrator or restored state file cannot delete on first
   sight; worst case that grants one extra retention period.

### Rolling the runner image

Bump `RUNNER_VERSION`. Reconciliation reaps every runner carrying the old
version on the next restart instead of orphaning them. User workspaces are
named volumes and survive.

## What the agent sees

The driving agent is the LLM in the OWUI chat, not a process inside the
runner — it never sees a stack trace from in here, only what we put in its
environment, its workspace, and its tool output. Without help, a model that
hits a dead network call concludes "network bug" and burns a session
debugging DNS. Four independent channels tell it otherwise:

**Data — env vars, injected at every runner create:**

```
SANDBOX_MODE=air-gapped
SANDBOX_EGRESS=BLOCKED
SANDBOX_INTERNAL_SERVICES=devguard-api:8080=package proxy: pip/npm packages, malware-checked
```

`SANDBOX_INTERNAL_SERVICES` is `name:port=description` pairs, comma-joined,
one entry per service actually reachable on this deployment — empty unless
`DEVGUARD_ENABLED=true`. One renderer (`orchestrator/app/orientation.py`)
produces this string and the AGENTS.md service list below from the same
source, so the two cannot list different services.

**Prose — `AGENTS.md`, seeded into the workspace root on first spawn, only
if absent** (a user's own file, or one deeper in their project, is never
touched — nothing auto-loads this one, it is a read-me-first artifact):
states the sandbox is by design, that pip/npm already work through
`$PIP_INDEX_URL`/`$NPM_CONFIG_REGISTRY`, and lists the same internal
services as the env var above.

**Enforcement — unchanged:** the `internal: true` runners network, no
capabilities added. This is what actually makes egress impossible; the
other three channels exist so the agent stops trying before it wastes a
session finding that out the hard way.

**Feedback — curl/wget/apt-get shims** in `/usr/local/bin` (PATH-first,
outside the workspace volume, baked into the image): a call to an
allowlisted internal `host:port` always gets the real binary's real
response. Anything else — including `-x`/`--proxy`, which bypass the
allowlist otherwise — gets a real failure and a short explanation on
stderr, exit 126: instant (<100ms) when `SANDBOX_EGRESS=BLOCKED`, otherwise
a real attempt with a 2-second budget first. Never a fake success, never
mimicked output. `pip`/`npm` need no shim — they are already pointed at the
internal mirror and cannot reach a public registry regardless.

The orchestrator also DNS-checks every name in `SANDBOX_INTERNAL_SERVICES`
against the runners network once at boot and logs a warning (never fails
startup) if one does not resolve — config drift should be loud, not silent.

## Accepted risks

These are known, deliberate, and **not** closed. Do not read the hardening
elsewhere in this document as covering them.

**The socket proxy is a speed bump, not a wall.** `tecnativa/docker-socket-proxy`
filters by API path, not request body. With `CONTAINERS=1` and `POST=1` — both
required for the orchestrator to function — an attacker with code execution in
the orchestrator can still `POST /containers/create` with
`HostConfig.Binds: ["/:/host"]` and reach host root. It closes the easy paths
(exec into any container, inspecting unrelated containers' secrets). Closing it
properly needs a payload-validating proxy. Measured detail: `EXEC=0` returns 403
on `POST /exec/{id}/start` but **not** on `POST /containers/{id}/exec`, which is
gated by `CONTAINERS` and returns 201 — an exec instance can be created but
never started.

**`apparmor=unconfined` on every container.** This host is a Proxmox LXC
container and cannot load AppArmor profiles (`apparmor_parser: Access denied`).
`docker build` fails outright for the same reason. `no-new-privileges` and the
capability set still apply and carry most of the weight. Fix host-side with
`lxc.apparmor.profile: unconfined` on the Proxmox container, or move to a full
VM — which also restores kernel-level disk quotas.

**One shared runner network.** Runners can reach each other; network-per-runner
was rejected for v1. What makes that survivable is per-runner derived keys —
an agent can read its own key out of `/proc/self/environ`, and that key is
useless against any sibling. If key derivation is ever weakened, the network
will not save you. The socket proxy sits on a separate `control` network that
runners are not attached to.

**K1 crosses the LAN in plaintext.** No TLS on the LAN hop (explicitly out of
scope for v1). Anyone who can read traffic between OWUI and the orchestrator,
or who obtains K1, can impersonate **any user** by setting `X-User-Id` — the
header is trusted precisely because K1 validated. Keep K1 distinct from the
OWUI admin token and from every runner key.

**Disk is monitored, not quota'd.** No loop devices and no project quotas on
this host, so `RUNNER_DISK_SOFT`/`_HARD` are enforced by polling every
`DISK_POLL_INTERVAL`. A writer faster than the poll wins the race. Accepted on
the host's free-space margin.

### Closed during live integration

**`/files/serve` same-origin execution — was real, now mitigated.** Verified on
the wire: an agent can write `evil.html` into its own workspace, and OWUI's
terminal proxy returned it as `text/html; charset=utf-8` **from OWUI's own
origin** with no CSP, no `X-Frame-Options` and no `X-Content-Type-Options`,
script intact. That is a stored-XSS path to the OWUI session token, reachable
by prompt injection through a cloned repo.

The orchestrator now injects `Content-Security-Policy: sandbox` and
`X-Content-Type-Options: nosniff` on `/files/serve` responses. OWUI strips only
`transfer-encoding`, `connection`, `content-encoding` and `content-length`, so
these survive to the browser — confirmed live. `sandbox` drops the response
into an opaque origin: static previews still render, scripts do not run, and
OWUI's storage is unreachable. Set `FILES_SERVE_CSP=` to disable (previews with
JS would then work, unsafely).

Note this is a mitigation on our side of an OWUI-side behaviour. Any other
terminal server wired into the same instance has the same exposure and is not
covered by this.

## Testing without OWUI

`tests/stub_owui.py` mirrors the real OWUI admin contract (including its
400-for-unknown-user behaviour) with fixed users `alice` (user), `adam` (admin),
`pat` (pending), `weird` (unknown role):

```bash
docker compose up -d
docker run -d --name stub-owui --network owui-runner_edge \
  --security-opt apparmor=unconfined -v "$PWD/tests:/t:ro" \
  -e STUB_TOKEN=stub-admin-token python:3.12-slim python /t/stub_owui.py
# then set OWUI_BASE_URL=http://stub-owui:8099, OWUI_ADMIN_TOKEN=stub-admin-token
```

Then in OWUI: **Admin Settings → Integrations → Open Terminal**, URL
`http://<orch-host>:8080`, Auth Type `Bearer`, key = `ORCH_API_KEY`.

## Tests

```bash
cd tests
./run.sh              # unit + integration, skipping timing-sensitive tests
./run.sh --all        # everything (~22 min; adds idle and cache-grace waits)
./run.sh --unit       # unit only, no Docker required
NO_BUILD=1 ./run.sh   # reuse existing images (the 840MB runner export is
                      # memory-hungry and can be OOM-killed on a small host)
KEEP_STACK=1 ...      # leave the stack up after a failure so logs survive
```

The suite found three production bugs — phantom budget slots, idle teardown
racing in-flight requests, and a memory gate that refused users while the host
had 1.9 GiB free. See REVIEW OUTCOMES v1.5 (N18-N22) in the brief.

## Host prerequisites discovered during Lane A/D

This orch host is a Proxmox **LXC container**, which constrains three things.
All three are recorded in v1.2; the short version:

1. **AppArmor profiles cannot be loaded** (N5). Every container needs
   `apparmor=unconfined`, and `docker build` fails outright because the build
   sandbox cannot apply a profile either. Workaround in use:

   ```bash
   docker run -d --name owui-buildkitd --privileged \
     --security-opt apparmor=unconfined moby/buildkit:latest
   docker buildx create --name owui-bk --driver remote \
     docker-container://owui-buildkitd
   docker buildx build --builder owui-bk --load -t owui-agent-runner:dev runner/
   ```

   The builder persists across sessions; start/stop it with:

   ```bash
   docker start owui-buildkitd    # before building
   docker stop  owui-buildkitd    # it is privileged — stop it when idle
   ```

   Permanent fix is host-side: set `lxc.apparmor.profile: unconfined` on the
   container in Proxmox, or move the orch to a full VM.

2. **No loop devices** → the agreed loopback-ext4 disk quota (Q6=A) is not
   implementable. Running monitor-and-enforce instead (N4).

3. **Docker uses the containerd snapshotter** with an ext4 rootfs and no
   `prjquota`, so `--storage-opt size=` is unavailable too.

## Layout

```
runner/Dockerfile      Lane A — Open Terminal base + pinned openCode glibc build
docker-compose.yml     Lane D — 3 networks, socket proxy, orchestrator, build helper
.env.example           all knobs, with the reasoning for the non-obvious ones
orchestrator/          Lane B + C (empty)
tests/                 Lane E (empty)
data/                  orchestrator state (gitignored)
```
