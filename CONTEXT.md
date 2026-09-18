# Agent Runner Fleet (owui-runner-orchestrator)

Containerized per-user execution for Open WebUI agents: the orchestrator spawns isolated runners on demand, agents work inside them, and users see and edit the same files from the Open WebUI sidebar.

## Language

**Runner**:
A per-user container where an agent executes commands and keeps its files.
_Avoid_: sandbox, worker, pod

**Orchestrator**:
The authenticated service that decides when runners exist, attaches them to the right networks, and proxies Open WebUI's requests to them.
_Avoid_: router, gateway, supervisor

**Workspace**:
A user's persistent file area; it is their home directory and the sidebar root — one and the same thing.
_Avoid_: home, volume, scratch

**Budget**:
The fixed promise of host memory the fleet may commit across all runners; new runners are refused, never swapped, when it is exhausted.
_Avoid_: pool, quota, limit

**DevGuard**:
The supply-chain security platform standing between runners and public package registries, blocking known-malicious packages before they are served.
_Avoid_: proxy, mirror (these name mechanisms, not the product)

**Dependency Proxy**:
DevGuard's component that intercepts package-manager requests, checks them against the malicious-package feed, and caches verified artifacts.

**Package Seam**:
The single configuration surface through which all runner package traffic is directed; empty by default, pointed at DevGuard in production.
_Avoid_: mirror config, registry override

**Zero-egress**:
The topology invariant that a runner has no route to the outside world except through DevGuard; enforced by network topology and proven by tests, not asserted.
_Avoid_: firewalled, restricted

**Owner label**:
The container label marking which orchestrator instance owns a runner, so a second stack can never adopt or reap foreign runners.
_Avoid_: ownership tag

**Verify**:
Open WebUI's probe of a terminal-server configuration; the orchestrator answers it, proving the route end to end without touching runners.
