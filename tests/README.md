# Lane E — test suite

Two layers.

**`unit/`** — pure logic, no Docker, sub-second. Key derivation, size/duration
parsing, container-name sanitising, denylist matching, busy-detection.

**`integration/`** — a real stack: real containers, real socket proxy, real
`internal: true` network. Every finding this suite guards came from behaviour
that only appears once the pieces are wired together; a mocked Docker API would
have passed all of them.

The integration stack runs under its own compose project (`owui-runner-test`),
its own network name and its own port (8081), reading `env.test` rather than the
operator's `.env`. It never touches a production stack on the same host.

## Running

```bash
./run.sh            # unit + integration, skipping timing-sensitive tests
./run.sh --all      # everything (adds ~3 min of idle/grace-window waits)
./run.sh --unit     # unit only, no Docker required
./run.sh -k egress  # anything else is passed through to pytest
```

## What each file guards

| File | Finding |
|------|---------|
| `unit/test_keys.py` | N1 — key derivable from master + label nonce alone |
| `unit/test_naming.py` | container-name sanitising; distinct uids must not collide |
| `unit/test_proxy_rules.py` | Q5 denylist must not over- or under-match |
| `unit/test_runner_client.py` | C7 — unknown process state must read as BUSY |
| `unit/test_config.py` | a typo'd limit must raise, never silently default |
| `integration/test_isolation.py` | **cross-user isolation + lateral movement (Q7/N1/N2)** |
| `integration/test_egress.py` | zero egress incl. LAN and gateway; exactly one network (A6) |
| `integration/test_lifecycle.py` | spawn, restart adoption (A4×N1), spawn race (A5), budget (R3) |
| `integration/test_idle.py` | C7 — busy ≠ idle |
| `integration/test_persistence.py` | brief test (c) **plus** the writability assertion it lacked |
| `integration/test_proxy.py` | five `/execute` endpoints, streaming (C8), stale ids (C7) |
| `integration/test_roles.py` | A8 — fail closed, never open |
| `integration/test_resources.py` | brief test (b) in the cgroup and by effect |
| `integration/test_quota.py` | N4 accounting; N14 cache survives restart |
| `integration/test_noop_guard.py` | ADR-0012 — empty `GROUP_MAP`/no `POLICY_*` is byte-for-byte v1: exact env, resources, image, security posture, network and idle timeout, for user and admin alike |

## Stub OWUI

`stub_owui.py` mirrors the real admin contract from
`open-webui/backend/open_webui/routers/users.py`, including its **400 (not 404)**
for an unknown user. Roles resolve by uid prefix so each test gets a unique
user and never shares a runner: `u-` user, `a-` admin, `p-` pending, `x-`
unknown role.
