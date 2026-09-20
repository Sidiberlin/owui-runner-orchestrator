# How to deploy on a fresh LXC host

Bring the orchestrator stack up on a fresh Proxmox LXC container, working
around the three constraints an LXC host imposes that a full VM does not.

## Prerequisites

- A Proxmox LXC container with Docker Engine and the `docker compose` plugin
  installed.
- Root or sudo access on the LXC host (needed once, to work around AppArmor).
- This repo checked out on the host.

## Steps

### 1. Confirm you're actually constrained

An LXC container cannot load AppArmor profiles, has no loop devices, and (on
an ext4 rootfs with the containerd snapshotter) no `prjquota` support. Check:

```bash
apparmor_parser --version   # if this errors "Access denied", you're affected
ls /dev/loop*               # if this is empty, you're affected
```

If both come back clean on your box (a full VM, for instance), you can drop
`apparmor=unconfined` from every service in `docker-compose.yml` and skip
straight to the normal bring-up in
[Getting started](../tutorials/getting-started.md).

### 2. Work around the AppArmor restriction for building

`docker build` fails outright on an LXC host that can't apply an AppArmor
profile to the build sandbox — you'll need a privileged BuildKit container
instead:

```bash
docker run -d --name owui-buildkitd --privileged \
  --security-opt apparmor=unconfined moby/buildkit:latest
docker buildx create --name owui-bk --driver remote \
  docker-container://owui-buildkitd
docker buildx build --builder owui-bk --load -t owui-agent-runner:dev runner/
```

The builder persists across sessions. Start it before you need to build an
image and stop it when you're done — it's privileged, so it shouldn't sit
running unnecessarily:

```bash
docker start owui-buildkitd    # before building
docker stop  owui-buildkitd    # when idle
```

The permanent fix, if you'd rather not carry this workaround, is host-side:
set `lxc.apparmor.profile: unconfined` on the container in Proxmox, or move
the orchestrator to a full VM.

### 3. Configure secrets and bring the stack up

Follow [Getting started](../tutorials/getting-started.md) Steps 1–3 (`cp
.env.example .env`, fill the four secrets, `docker compose up -d`). Every
service in `docker-compose.yml` already carries `apparmor=unconfined` in its
`security_opt`, so this part needs no changes on an LXC host.

### 4. Size resource limits against what the LXC host actually reports

`/proc/meminfo` inside a Docker-on-LXC container is virtualized and
under-reports available memory — measured on the reference deployment host,
the orchestrator's own view showed 534 MiB available while the host actually
had 1908 MiB free. Two consequences:

- Leave `MEMORY_GATE=off` (the default). Turning it on on an LXC host will
  refuse spawns while the host has plenty of free RAM. The real, reliable
  bound is `MAX_CONTAINERS × RUNNER_MEMORY`, which the orchestrator tracks
  exactly (`committed_memory_mb` in `/_orch/status`) rather than reading from
  `/proc`.
- Size `MAX_CONTAINERS` and `RUNNER_MEMORY` against what you actually measure
  free under load, not against `MemTotal`. The reference host (7.6 GiB total,
  0.6–2.1 GiB available under load) runs `MAX_CONTAINERS=3` and
  `RUNNER_MEMORY=768m` — the originally-planned `6 × 1g` didn't fit and every
  spawn over budget was refused with a 429.

### 5. Accept (don't fight) the disk-quota gap

No loop devices means no loopback-ext4 disk quota, and no `prjquota` on this
rootfs class means `--storage-opt size=` isn't available either. The
orchestrator falls back to monitor-and-enforce: `DISK_POLL_INTERVAL` (default
60s) polls each runner's usage against `RUNNER_DISK_SOFT`/`RUNNER_DISK_HARD`.
This is detection, not prevention — a writer faster than the poll interval
can outrun it. There's nothing to configure here beyond accepting the
default poll interval, or shortening it if you want a smaller race window at
the cost of more polling load.

## Verification

```bash
curl -s localhost:8080/_orch/healthz                 # -> ok
K=$(grep ^ORCH_API_KEY= .env | cut -d= -f2)
curl -s -H "Authorization: Bearer $K" localhost:8080/_orch/status
```

Confirm `host_memory_available_mb` in the response looks implausibly low
compared to what you know the host has free — that's the LXC `/proc`
virtualization described in Step 4, and it's expected. `committed_memory_mb`
is the number to trust.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `docker build` fails immediately with an AppArmor error | LXC can't load AppArmor profiles for the build sandbox | Use the BuildKit workaround in Step 2 |
| Runners are refused with 429 even though the host looks idle | `MEMORY_GATE=on` reading a virtualized `/proc/meminfo` | Set `MEMORY_GATE=off`; trust `committed_memory_mb` instead |
| A runner keeps growing past `RUNNER_DISK_HARD` | The disk poll interval didn't catch a fast writer in time | Lower `DISK_POLL_INTERVAL`; there is no hard kernel-level quota available on this host class |
| `docker run` for `owui-buildkitd` fails with a privilege error | The LXC container itself isn't allowed to run privileged containers | Check the Proxmox container's own privilege/nesting settings; this is a prerequisite of the workaround, not the orchestrator |

## Related

- [Getting started](../tutorials/getting-started.md) for the full first-boot walkthrough.
- [Reference: environment variables](../reference/environment-variables.md) for every sizing knob.
- ADR-0003 (committed-memory accounting) and ADR-0006 (single-LXC consolidation) in [`docs/adr/`](../adr/) for the design rationale.
