"""Fixtures for the runner-orchestrator suite.

The integration tests drive a REAL stack: real containers, a real socket proxy,
a real internal network. That is deliberate. Every finding this suite guards
came from behaviour that only appears when the pieces are actually wired
together — a mocked Docker API would have passed every one of them.

The stack runs under its own compose project (`owui-runner-test`), its own
network name, and its own port, so it never touches a production stack on the
same host. It reads env.test, never the operator's .env.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass

import httpx
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROJECT = "owui-runner-test"
ENV_FILE = os.path.join(HERE, "env.test")
STUB_NAME = "stub-owui-test"

# Unit tests import the application directly.
sys.path.insert(0, os.path.join(ROOT, "orchestrator"))


# --------------------------------------------------------------------------
# shell helpers
# --------------------------------------------------------------------------
def sh(*args: str, check: bool = True, timeout: int = 120) -> str:
    p = subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, cwd=ROOT
    )
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed ({p.returncode}): {p.stderr[-800:]}")
    return p.stdout.strip()


def compose(*args: str, check: bool = True, timeout: int = 240) -> str:
    return sh("docker", "compose", "--env-file", ENV_FILE, "-p", PROJECT,
              *args, check=check, timeout=timeout)


def env_value(key: str) -> str:
    with open(ENV_FILE) as fh:
        for line in fh:
            if line.strip().startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    raise KeyError(key)


def service_container(service: str) -> str:
    """Compose derives container names from the project, so they must be looked
    up rather than hardcoded — that is what lets a test stack and a production
    stack coexist on one host."""
    return compose("ps", "-q", service).splitlines()[0].strip()


def inspect(name: str, fmt: str) -> str:
    return sh("docker", "inspect", "-f", fmt, name)


def container_exists(name: str) -> bool:
    out = sh("docker", "ps", "-aq", "-f", f"name=^{name}$", check=False)
    return bool(out.strip())


def runner_containers() -> list[str]:
    """Only runners on the TEST network.

    The managed label alone is not enough: a production stack on the same host
    labels its runners identically, so an unscoped purge would delete a real
    user's container mid-session. Scoping by the test network is what keeps the
    suite safe to run next to a live deployment.
    """
    out = sh("docker", "ps", "-aq",
             "--filter", "label=io.owui.runner.managed=1",
             "--filter", f"network={env_value('RUNNERS_NETWORK')}", check=False)
    return [c for c in out.splitlines() if c.strip()]


# Test uids are minted by the `uid`/`admin_uid` fixtures (u-/a- prefixes) or
# are explicit u-<name> literals. A production uid is an OWUI UUID.
_TEST_UID_PREFIXES = ("u-", "a-", "p-", "x-")


def _is_test_volume(name: str) -> bool:
    suffix = name[len("runner-ws-"):] if name.startswith("runner-ws-") else ""
    return suffix.startswith(_TEST_UID_PREFIXES)


def runner_name_for(uid: str) -> str:
    return f"runner-{uid}"


def remove_runner(uid: str) -> None:
    sh("docker", "rm", "-f", runner_name_for(uid), check=False)
    sh("docker", "volume", "rm", "-f", f"runner-ws-{uid}", check=False)


def purge_runners() -> None:
    ids = runner_containers()
    if ids:
        sh("docker", "rm", "-f", *ids, check=False, timeout=180)
    # Volumes carry no network, so only remove those whose runner we just
    # removed, plus the test suite's own uid shapes. Never a blanket purge:
    # a production workspace volume is a user's data.
    vols = sh("docker", "volume", "ls", "-q", "--filter",
              "label=io.owui.runner.managed=1", check=False)
    names = [v for v in vols.splitlines()
             if v.strip() and _is_test_volume(v.strip())]
    if names:
        sh("docker", "volume", "rm", "-f", *names, check=False, timeout=180)


# --------------------------------------------------------------------------
# stack lifecycle
# --------------------------------------------------------------------------
@dataclass
class Stack:
    base_url: str
    key: str
    master_secret: str

    def client(self, timeout: float = 60.0) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=timeout)

    def orch_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.key}"}

    def user_headers(self, uid: str, session: str = "s-default") -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.key}",
            "X-User-Id": uid,
            "X-Session-Id": session,
        }

    def runner_key(self, uid: str) -> str:
        """Re-derive a runner's key exactly as the orchestrator does (N1)."""
        import hashlib
        import hmac
        nonce = inspect(runner_name_for(uid),
                        '{{index .Config.Labels "io.owui.runner.key-nonce"}}')
        return hmac.new(self.master_secret.encode(),
                        f"{uid}:{nonce}".encode(), hashlib.sha256).hexdigest()

    def wait_healthy(self, timeout: float = 90.0) -> None:
        deadline = time.time() + timeout
        last = ""
        while time.time() < deadline:
            try:
                r = httpx.get(f"{self.base_url}/_orch/healthz", timeout=5)
                if r.status_code == 200:
                    return
                last = f"status {r.status_code}"
            except Exception as exc:  # noqa: BLE001
                last = str(exc)
            time.sleep(1)
        raise RuntimeError(f"orchestrator never became healthy: {last}")

    # -- talking to runners directly ---------------------------------------
    # The runners network is `internal: true`, so it is unreachable from the
    # host by design. Anything that needs to speak to a runner (or to test
    # whether one runner can reach another) has to originate INSIDE a
    # container on that network.
    #
    # /usr/bin/curl explicitly, NOT the PATH-resolved `curl`: this is a raw
    # network-topology probe (used by test_egress/test_isolation to measure
    # what the network actually permits), not a simulated agent tool call.
    # The ticket-13 sandbox shim shadows plain `curl` in PATH and would
    # otherwise refuse a sibling/gateway probe before it ever touched the
    # network, which is a different (and correct) behavior for an agent but
    # would make this helper measure the shim instead of the topology.
    # test_shims.py exercises the shim itself via PATH-resolved `curl`.
    def curl_in(self, container: str, *args: str) -> tuple[int, str]:
        out = sh("docker", "exec", container, "/usr/bin/curl", "-s",
                 "-w", "\n%{http_code}", "--max-time", "20", *args,
                 check=False, timeout=60)
        if "\n" not in out:
            return 0, out
        body, _, code = out.rpartition("\n")
        return (int(code) if code.strip().isdigit() else 0), body

    def runner_request(self, uid: str, path: str, *extra: str,
                       key: str | None = None) -> tuple[int, str]:
        """Hit a runner's Open Terminal directly, bypassing the proxy."""
        k = key if key is not None else self.runner_key(uid)
        return self.curl_in(
            runner_name_for(uid), "-H", f"Authorization: Bearer {k}",
            *extra, f"http://{runner_name_for(uid)}:8000{path}",
        )

    def cross_request(self, from_uid: str, to_uid: str, path: str,
                      key: str | None = None) -> tuple[int, str]:
        """Reach OUT of one runner INTO a sibling on the shared network.

        This is the lateral-movement probe: it is exactly what a
        prompt-injected agent inside a runner could attempt.
        """
        k = key if key is not None else self.runner_key(from_uid)
        return self.curl_in(
            runner_name_for(from_uid), "-H", f"Authorization: Bearer {k}",
            f"http://{runner_name_for(to_uid)}:8000{path}",
        )

    def restart_orchestrator(self) -> None:
        compose("restart", "orchestrator")
        self.wait_healthy()

    def stop_owui(self) -> None:
        sh("docker", "stop", STUB_NAME)

    def start_owui(self) -> None:
        sh("docker", "start", STUB_NAME)
        time.sleep(2)


def _ensure_owui_network() -> str:
    """`owui` is declared `external: true` (ADR-0006: the orchestrator joins
    OWUI's own docker network by name), so compose will not create it. This
    box runs no real OWUI, so the suite owns a throwaway stand-in network
    under a test-only name and is responsible for its lifecycle."""
    name = env_value("OWUI_NETWORK")
    existing = sh("docker", "network", "ls", "-q", "--filter", f"name=^{name}$",
                  check=False)
    if not existing.strip():
        sh("docker", "network", "create", name)
    return name


def _docker_available() -> bool:
    try:
        sh("docker", "version", "--format", "{{.Server.Version}}", timeout=20)
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="session")
def stack() -> Stack:
    if not _docker_available():
        pytest.skip("docker is not available")
    if not sh("docker", "images", "-q", env_value("RUNNER_IMAGE"), check=False):
        pytest.skip(
            f"runner image {env_value('RUNNER_IMAGE')} not built; "
            "run tests/run.sh which builds it first"
        )

    owui_net = _ensure_owui_network()
    compose("up", "-d", timeout=300)
    sh("docker", "rm", "-f", STUB_NAME, check=False)
    sh("docker", "run", "-d", "--name", STUB_NAME, "--network", owui_net,
       "--security-opt", "apparmor=unconfined",
       "-v", f"{HERE}:/t:ro", "-e", f"STUB_TOKEN={env_value('OWUI_ADMIN_TOKEN')}",
       "python:3.12-slim", "python", "/t/stub_owui.py", timeout=300)
    time.sleep(3)

    st = Stack(
        base_url=f"http://127.0.0.1:{env_value('ORCH_PORT')}",
        key=env_value("ORCH_API_KEY"),
        master_secret=env_value("ORCH_MASTER_SECRET"),
    )
    # The stub starts after the orchestrator, so the first role lookup may have
    # failed. Restart so the suite begins from a known-good state.
    st.restart_orchestrator()
    yield st

    if os.getenv("KEEP_STACK") == "1":
        # Debugging affordance: leave everything up so logs and containers can
        # be inspected after a failure.
        print(f"\nKEEP_STACK=1: stack left running at {st.base_url}")
        return
    purge_runners()
    sh("docker", "rm", "-f", STUB_NAME, check=False)
    compose("down", "-v", check=False, timeout=240)
    sh("docker", "network", "rm", owui_net, check=False)


@pytest.fixture
def api(stack: Stack):
    with stack.client() as c:
        yield c


@pytest.fixture
def uid() -> str:
    """A unique `user`-role uid per test, so tests never share a runner."""
    return f"u-{uuid.uuid4().hex[:10]}"


@pytest.fixture
def admin_uid() -> str:
    return f"a-{uuid.uuid4().hex[:10]}"


@pytest.fixture
def cleanup_runners():
    """Remove any runner a test created, even if it failed."""
    created: list[str] = []
    yield created
    for u in created:
        remove_runner(u)
