# Getting started: stand up the orchestrator and run your first command

You'll bring up the orchestrator stack, wire it into your existing Open WebUI
instance, and get a real shell command running inside a per-user sandboxed
runner — all from one LAN box. By the end you'll have a working `docker compose`
stack, a verified `/_orch/status` reading, and a chat message that actually
executes.

## What you'll need

- Docker Engine + the `docker compose` plugin, on the same host (or LAN) as
  your Open WebUI instance.
- An existing Open WebUI deployment you can reach, plus an admin credential
  for it (see [Reference: environment variables](../reference/environment-variables.md#owui_admin_token)
  if you're not sure which kind you have).
- `openssl` (for generating secrets) and `curl` (for the checks below).
- This repo, checked out on the host that will run the orchestrator.

If your host is a Proxmox LXC container rather than a full VM, read
[How to deploy on a fresh LXC host](../how-to/deploy-on-a-fresh-lxc.md) first —
there are three host constraints (no AppArmor, no loop devices, no disk
quotas) that change how you build the runner image.

## Step 1: configure the four required secrets

```bash
cp .env.example .env
openssl rand -hex 32   # run this twice, for the two secrets below
```

Edit `.env` and fill in:

```
ORCH_API_KEY=<first random hex string>
ORCH_MASTER_SECRET=<second random hex string>
OWUI_BASE_URL=http://<your-owui-host>:8080
OWUI_ADMIN_TOKEN=<your OWUI admin credential>
```

`ORCH_API_KEY` is the bearer key Open WebUI will send on every request — this
is the value you'll paste into OWUI's integration settings in Step 4.
`ORCH_MASTER_SECRET` seeds per-runner key derivation; nothing outside the
orchestrator ever needs to know it. **Never reuse one value for the other** —
each secret has a distinct job, and the whole security story in
[Explanation: why runners can't reach the internet](../explanation/sandbox-and-spawn-time-binding.md)
depends on that.

The stock resource limits in `.env.example` (`RUNNER_CPUS=1.5`,
`RUNNER_MEMORY=1g`, `MAX_CONTAINERS=6`) are a starting point, not a
measurement of your host. Watch `/_orch/status`'s `committed_memory_mb` once
you're up (Step 3) and turn them down if you're on a small box — see
[Reference: environment variables](../reference/environment-variables.md)
for what each knob actually does.

## Step 2: build the runner image and bring the stack up

```bash
docker compose --profile build build runner-image   # builds owui-agent-runner
docker compose config                                # sanity-check the compose file
docker compose up -d                                 # socket proxy + orchestrator
```

The first command builds the per-user sandbox image (Open Terminal + a pinned
Node toolchain). The third starts the Docker API broker
(`docker-socket-proxy`) and the orchestrator itself — runners are **not**
started here; the orchestrator creates them on demand, one per user, the
first time that user makes a request.

## Step 3: confirm it's alive

```bash
curl -s localhost:8080/_orch/healthz
```

You should see `ok`. That's the container healthcheck endpoint, and it needs
no credential. Now check the authenticated status endpoint, which is where
you'll come back to any time you want to know what the fleet is actually
doing:

```bash
K=$(grep ^ORCH_API_KEY= .env | cut -d= -f2)
curl -s -H "Authorization: Bearer $K" localhost:8080/_orch/status
```

You'll get back a JSON block showing `runners_live: 0`, your `max_containers`
and `runner_memory_mb` settings, and a `policy_profiles` table with one entry
— `default` — because you haven't configured any policy profiles yet (that's
[a separate how-to](../how-to/create-a-policy-profile.md)). Full field list in
[Reference: `/_orch/*` endpoints](../reference/orch-endpoints.md).

If either command hangs or refuses the connection, check
`docker compose logs orchestrator` — a missing or placeholder secret in
`.env` (the app refuses to start on any value still prefixed `CHANGEME`) is
the most common first-boot failure.

## Step 4: point Open WebUI at it

In Open WebUI: **Admin Settings → Integrations → Open Terminal**, add a new
connection with:

- **URL**: `http://<this-host>:8080` (or `http://orchestrator:8080` if OWUI
  and the orchestrator share a Docker network — see
  [How to deploy on a fresh LXC](../how-to/deploy-on-a-fresh-lxc.md))
- **Auth Type**: Bearer
- **Key**: your `ORCH_API_KEY` value

Save it, and OWUI immediately probes the connection
(`POST /api/v1/configs/terminal_servers/verify`) — you should see
`{"status":true,"type":"terminal"}`. If instead you get *"Failed to connect to
the terminal server"*, the orchestrator isn't answering `GET /api/config`;
check that the container is actually up and reachable from OWUI's network.

**This connection starts Private with zero access grants** — only its
creator (you, as admin) can use it. Every other user gets a 403 until you
explicitly grant access. That's covered in
[How to entitle users](../how-to/entitle-users.md) — do that next if you want
anyone besides yourself to reach a runner.

## Step 5: run something

As the admin account that created the connection, start a new chat, pick a
model, and ask it to run a shell command — e.g. "run `env | grep SANDBOX` and
show me the output." Open WebUI's chat model calls the connection's
`run_command`/exec tool, which lands on:

```
your browser -> OWUI backend -> orchestrator (K1 + your X-User-Id) -> your runner
```

The orchestrator spawns a container named `runner-<your-owui-uid>` on its
first request from you — cold start takes a few seconds — then proxies the
command straight through. You should see real output, something like:

```
SANDBOX_MODE=air-gapped
SANDBOX_EGRESS=BLOCKED
```

Ask it to `curl https://example.com` and you'll get a clean, instant refusal
(exit 126) with an explanation, not a hang or a stack trace — that's
deliberate; see
[Explanation: why runners can't reach the internet](../explanation/sandbox-and-spawn-time-binding.md).

## What you built

You now have a working orchestrator that spawns an isolated, zero-egress
container per Open WebUI user, proxies their terminal tool calls into it, and
tears it down after it's been idle. From here:

- [How to entitle users via `runner-users` + access grants](../how-to/entitle-users.md)
  so non-admin users can reach it at all.
- [How to create a policy profile](../how-to/create-a-policy-profile.md) to
  give one OWUI group different resource limits without touching code.
- [Reference: environment variables](../reference/environment-variables.md)
  and [Reference: `/_orch/*` endpoints](../reference/orch-endpoints.md) for
  the full knob and API surface.
- [Explanation: no internet, spawn-time binding, and the `terminal:true`
  story](../explanation/sandbox-and-spawn-time-binding.md) for the "why"
  behind what you just saw.
