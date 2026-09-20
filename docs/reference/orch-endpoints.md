# Reference: `/_orch/*` endpoints

Everything the orchestrator owns lives under the `/_orch/` prefix. That
prefix is reserved so an orchestrator route can never collide with (and
silently shadow) an upstream Open Terminal path. Every other path is proxied
verbatim to the caller's runner — see
[Everything else: the runner proxy](#everything-else-the-runner-proxy) below.

Endpoints that require the orchestrator's own bearer key expect:

```
Authorization: Bearer <ORCH_API_KEY>
```

## `GET /_orch/healthz`

Unauthenticated — this is the container healthcheck. Leaks nothing but
liveness.

```bash
curl -s localhost:8080/_orch/healthz
```

**Response**: `ok` (plain text, `200`).

## `GET /_orch/status`

Requires `ORCH_API_KEY`. The primary operational read — check this before
reading logs or exec-ing into anything.

```bash
K=$(grep ^ORCH_API_KEY= .env | cut -d= -f2)
curl -s -H "Authorization: Bearer $K" localhost:8080/_orch/status
```

**Response fields**:

| Field | Meaning |
|---|---|
| `runners_live` | Count of currently tracked runner containers. |
| `max_containers` | Configured `MAX_CONTAINERS`. |
| `runner_memory_mb` | Configured `RUNNER_MEMORY`, in MiB. |
| `host_memory_available_mb` | `MemAvailable` as read from inside the orchestrator container. **Diagnostic only** — under Docker-on-LXC this is virtualized and can under-report by over a gigabyte. |
| `memory_gate_enabled` | Whether `MEMORY_GATE` is on. |
| `committed_memory_mb` | Sum of live runners' memory limits — what the orchestrator has actually promised the kernel. **This is the number to trust** for capacity questions. |
| `workspace_total_known_mb` | Aggregate known workspace usage across all volumes. |
| `workspace_ceiling_mb` | Configured `WORKSPACE_TOTAL_CEILING`. |
| `volume_retention_days` | Configured `VOLUME_RETENTION_DAYS`. |
| `devguard_enabled` | Whether the Package Seam is pointed at DevGuard. |
| `package_seam.pip_index_url` / `.npm_registry` | Resolved package-seam URLs, or `null` if unset. |
| `idle_timeout_s` | Configured global `IDLE_TIMEOUT`, in seconds. |
| `deny_prefixes` | The active `PROXY_DENY_PREFIXES` list. |
| `runner_image` | Configured `RUNNER_IMAGE`. |
| `policy_profiles` | The full resolved profile table (ADR-0012) — one entry per profile, each with `cpus`, `memory_mb`, `idle_timeout_s`, `exec_timeout_s`, `image`, `egress`. Recomputed live on every call, not cached from boot. |
| `unknown_mapped_groups` | `GROUP_MAP` group names that Open WebUI's current group roster does **not** contain — a live signal that a mapped group was renamed or deleted, checked fresh on every call so a rename shows up on the next request, not only at the last restart. |

## `GET /_orch/runners`

Requires `ORCH_API_KEY`. Lists every runner the orchestrator currently
tracks.

```bash
curl -s -H "Authorization: Bearer $K" localhost:8080/_orch/runners
```

**Response**: a JSON array, one object per runner:

| Field | Meaning |
|---|---|
| `uid` | The OWUI user id this runner belongs to. |
| `name` | Container name (`runner-<safe-uid>`). |
| `role` | `user` or `admin`, as resolved at spawn time. |
| `container_id` | First 12 characters of the Docker container ID. |
| `idle_s` | Seconds since this runner last saw a request. |
| `workspace_mb` | Last-known workspace disk usage. |
| `replaced_reason` | If this runner replaced a torn-down one, why — otherwise `null`. |
| `profile` | The policy profile this runner was created under (survives an orchestrator restart via a durable label — restart-adopted runners report their real profile, not `default`). |

`/_orch/runners` is the authority on what the orchestrator *believes* exists;
`docker ps --filter label=io.owui.runner.managed=1` is ground truth. A
persistent disagreement between the two is a bug — see the README's "Phantom
slots" section.

## `POST /_orch/retention/sweep`

Requires `ORCH_API_KEY`. Runs one workspace-retention sweep on demand.
Defaults to `dry_run=true` so you can see what a policy *would* delete before
trusting it.

```bash
curl -s -X POST -H "Authorization: Bearer $K" \
  "localhost:8080/_orch/retention/sweep?dry_run=true"
```

**Response**:

```json
{"retention_days": 90.0, "enabled": true, "dry_run": true, "count": 2, "volumes": [...]}
```

Set `dry_run=false` to actually delete. This never touches a live runner's
volume, never acts outside this orchestrator's own `RUNNERS_NETWORK`, and
never deletes a uid it has no recorded activity for (it starts that uid's
clock instead) — see ADR/README "Workspace retention" for the full guard
list.

## `DELETE /_orch/runners/{uid}`

Requires `ORCH_API_KEY`. Force-tears-down a specific user's runner
immediately, regardless of idle state. Their workspace volume is untouched —
their next request spawns a fresh container against the same volume.

```bash
curl -s -X DELETE -H "Authorization: Bearer $K" \
  localhost:8080/_orch/runners/<uid>
```

**Response**: `{"uid": "<uid>", "torn_down": true}`.

Use this to force a policy-profile change to take effect immediately instead
of waiting for the runner to idle out (see
[How to create a policy profile](../how-to/create-a-policy-profile.md)) or as
the kill switch for a runaway process an idle sweep would otherwise never
reclaim.

## `GET /api/config` — the OWUI discovery probe

Not under `/_orch/`, and not a general-purpose endpoint — this exact path is
special-cased. Open WebUI's connection "verify" step calls it **with the
connection's bearer key but no `X-User-Id`** (no user is in scope yet during
verification), and the orchestrator answers only when both conditions hold:

```bash
curl -s -H "Authorization: Bearer $K" localhost:8080/api/config
```

**Response**:

```json
{"features": {"terminal": true, "notebooks": <bool>, "system": <bool>}}
```

`terminal` is unconditionally `true` — advertising `false` was found live to
also disable Open WebUI's chat-model exec tool for the connection, not just
hide a PTY pane (see
[Explanation](../explanation/sandbox-and-spawn-time-binding.md) for the full
story). `notebooks` and `system` are derived from whether `/notebooks` and
`/system` are in `PROXY_DENY_PREFIXES` — neither is denied by default, so
both are `true` out of the box.

**This endpoint is why the orchestrator's `verify` step succeeds.** The
connection's `path: "/openapi.json"` field is a red herring — it's an inert
field inherited from the tool-server schema, not the actual probe path, and
this app returns FastAPI docs disabled (`docs_url`/`openapi_url` are `None`)
deliberately, since the runners network can reach this app and must not be
handed its own API schema.

Any request to `/api/config` that *does* carry `X-User-Id` is **not** this
probe — it falls through to the general proxy path below like any other
request.

## Everything else: the runner proxy

Any path not matched above, and not one of the three denied prefixes, is
authenticated (`ORCH_API_KEY` + a required `X-User-Id` header) and forwarded
verbatim to that user's runner, spawning one on demand:

```bash
curl -s -H "Authorization: Bearer $K" -H "X-User-Id: <owui-user-id>" \
     -H "X-Session-Id: <chat-id>" localhost:8080/system
```

`X-Session-Id` is optional but should be passed when a chat is in scope —
Open Terminal keys its session-aware working directory off it, so omitting
it can leak one chat tab's `cd` into another.

**Denied by default** (`PROXY_DENY_PREFIXES`, `403`):

| Prefix | Why |
|---|---|
| `/proxy` | Pure SSRF surface. |
| `/ports` | Same. |
| `/api/terminals` | WebSocket PTY, explicitly out of scope. Blocked here **independently** of the `/api/config` `terminal:true` advertisement above — advertising `true` does not reopen this. |

Everything else — all five `/execute` endpoints, `/files/*`, `/system`,
etc. — is forwarded, streamed in both directions (never buffered, so a large
`/files/archive` can't OOM the orchestrator, and a long `/execute` long-poll
isn't cut short).

A `404` on an `/execute/{id}/...` path whose runner was recently replaced
returns a `409` with `"reason": "runner_replaced"` instead of a bare 404 —
the process id belonged to a torn-down container, not a bug.

## Related

- [Reference: environment variables](environment-variables.md) for what configures the values these endpoints report.
- [Reference: runner environment](runner-environment.md) for what a runner itself sees.
- [Explanation: spawn-time binding and the `terminal:true` story](../explanation/sandbox-and-spawn-time-binding.md).
