"""Ticket 01 (v2.0 group policy profiles, docs/adr/0012): the no-op guard.

ADR-0012's stated consequence is unambiguous: "Deploying with an empty
GROUP_MAP must be a no-op - the orchestrator behaves byte-for-byte as v1
(guard test required)." This file is that guard.

It is written against current `main`, BEFORE any group-policy-profiles
production change lands: `GROUP_MAP` and `POLICY_*` are not even fields on
`Config` yet, and tests/env.test sets neither, so "no mapping configured"
already holds with zero fixture changes. What captures real v1 behaviour
here - rather than the behaviour of a half-built feature - is that fact.
Every later ticket in the chain re-runs this file unmodified; a failure in
it blocks that ticket rather than being reconciled after the fact (spec.md,
"Testing Decisions").

Every expected value below is hand-written from tests/env.test and the
current source (config.py, runners.py, orientation.py, roles.py) - never
read back from the container under test - so this cannot become a
self-fulfilling "compare to whatever the code produced" assertion. The one
exception is OPEN_TERMINAL_API_KEY, which is impossible to hardcode (it is
minted per spawn from a random nonce): that is independently RE-DERIVED via
stack.runner_key(), the same HMAC(master_secret, uid:nonce) reimplementation
already used by conftest.py to prove key re-derivation elsewhere (N1) -
never read back from the runner's own environment.
"""
from __future__ import annotations

import json
import time

import pytest

from conftest import container_exists, env_value, inspect, runner_name_for, sh

pytestmark = pytest.mark.integration

# --- v1 baseline: container resource shape --------------------------------
# env.test: RUNNER_CPUS=0.5, RUNNER_MEMORY=320m, RUNNER_PIDS=256,
# ADMIN_RUNNER_MEMORY=384m, ADMIN_RUNNER_CPUS is UNSET (config.py falls back
# to RUNNER_CPUS), ADMIN_RUNNER_DISK_SOFT is UNSET (disk_soft never reaches
# Docker HostConfig anyway - it is quota-only, not a container config value).
USER_NANO_CPUS = 500_000_000
USER_MEMORY = 320 * 1024**2
ADMIN_NANO_CPUS = 500_000_000  # same as user: ADMIN_RUNNER_CPUS is unset
ADMIN_MEMORY = 384 * 1024**2
PIDS_LIMIT = 256  # not role-derived in v1: RUNNER_PIDS has no admin override

# env.test: RUNNER_SECURITY_OPT / RUNNER_CAP_ADD. Neither is role-derived.
SECURITY_OPT = {"no-new-privileges", "apparmor=unconfined"}
CAP_ADD = {"CHOWN", "DAC_OVERRIDE", "FOWNER", "SETUID", "SETGID"}
CAP_DROP = {"ALL"}  # runners.py: HostConfig.CapDrop is hardcoded, not env-driven

NETWORK_NAME = env_value("RUNNERS_NETWORK")
RUNNER_IMAGE = env_value("RUNNER_IMAGE")  # not role- or profile-derived in v1

# --- v1 baseline: effective idle timeout -----------------------------------
# Ticket 16 lesson (tests/integration/test_resources.py, commit b232c6f
# "widen the zero-margin timeout race"): a wait with zero margin over the
# window it is proving is a false-failure machine under host load. Reusing
# test_idle.py's own already-proven, non-zero-margin SETTLE window here
# rather than inventing a tighter one.
# env.test: IDLE_TIMEOUT=60s, IDLE_SWEEP_INTERVAL=5s
IDLE_TIMEOUT = 60
SWEEP = 5
SETTLE = IDLE_TIMEOUT + SWEEP * 3


def _gone_within(name: str, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not container_exists(name):
            return True
        time.sleep(2)
    return not container_exists(name)


# --- capture helpers ---------------------------------------------------------
def _container_env(name: str) -> dict[str, str]:
    """The runner's own environment, as the Docker API reports it (the same
    pattern test_orientation.py, test_isolation.py and test_package_seam.py
    already use as ground truth for a runner's env)."""
    out = inspect(name, "{{range .Config.Env}}{{println .}}{{end}}")
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def _image_baked_env() -> dict[str, str]:
    """What the IMAGE itself bakes in via its own Dockerfile ENV lines -
    inspected on the immutable image, never on a spawned container, so this
    is independent of the code path under test. A runner's actual env is
    this dict overlaid by whatever the orchestrator explicitly injects at
    create time (verified empirically: Docker's own container-create env
    merge overrides an image key by name, never duplicates it)."""
    raw = sh("docker", "image", "inspect", RUNNER_IMAGE, "--format",
              "{{json .Config.Env}}")
    return dict(p.split("=", 1) for p in json.loads(raw))


def _expected_injected_env(api_key: str) -> dict[str, str]:
    """Exactly what runners.py's _runner_env() injects on today's `main`,
    with no GROUP_MAP/POLICY_* seam to widen it. An added or renamed key
    here - e.g. a future ticket leaking POLICY_NAME or group data into the
    runner's own env by mistake - must fail this comparison, not just a
    changed value."""
    return {
        "OPEN_TERMINAL_API_KEY": api_key,
        "OPEN_TERMINAL_MULTI_USER": "false",
        "OPEN_TERMINAL_FILE_BROWSER_ROOT": "home",
        # env.test: OPEN_TERMINAL_MAX_SESSIONS=8
        "OPEN_TERMINAL_MAX_SESSIONS": "8",
        # env.test: OPEN_TERMINAL_EXECUTE_TIMEOUT=120 - the effective exec
        # timeout a runner's Open Terminal enforces. Global today, not yet
        # role- or group-derived; this is the value ticket 03 (spawn-time
        # application) will widen to a per-profile one.
        "OPEN_TERMINAL_EXECUTE_TIMEOUT": "120",
        # env.test: OPEN_TERMINAL_SESSION_CWD_TTL=604800
        "OPEN_TERMINAL_SESSION_CWD_TTL": "604800",
        # env.test: PIP_INDEX_URL is set explicitly and DEVGUARD_ENABLED is
        # unset, so the Package Seam's "explicit value always wins" rule
        # passes it through unrewritten (config.py:_package_seam).
        "PIP_INDEX_URL": "http://devguard-test:3141/root/pypi/+simple/",
        # orientation.py sandbox_env(): always present on every runner.
        # DEVGUARD_ENABLED is unset here, so sandbox_services() is empty and
        # SANDBOX_INTERNAL_SERVICES renders as "".
        "SANDBOX_MODE": "air-gapped",
        "SANDBOX_EGRESS": "BLOCKED",
        "SANDBOX_INTERNAL_SERVICES": "",
        # Deliberately NOT present, and their absence is part of the
        # baseline: NPM_CONFIG_REGISTRY (empty - NPM_CONFIG_REGISTRY unset
        # and DEVGUARD_ENABLED unset) and PIP_TRUSTED_HOST (empty - only
        # derived when DEVGUARD_ENABLED is true). runners.py only adds
        # either key when its value is non-empty.
    }


def _assert_v1_container_shape(
        name: str, uid: str, stack, role: str, nano_cpus: int, memory: int) -> None:
    assert inspect(name, "{{.Config.Image}}") == RUNNER_IMAGE
    assert inspect(name, "{{.HostConfig.NanoCpus}}") == str(nano_cpus)
    assert inspect(name, "{{.HostConfig.Memory}}") == str(memory)
    assert inspect(name, "{{.HostConfig.PidsLimit}}") == str(PIDS_LIMIT)

    sec = set(json.loads(inspect(name, "{{json .HostConfig.SecurityOpt}}")))
    assert sec == SECURITY_OPT
    cap_add = set(json.loads(inspect(name, "{{json .HostConfig.CapAdd}}")))
    assert cap_add == CAP_ADD
    cap_drop = set(json.loads(inspect(name, "{{json .HostConfig.CapDrop}}")))
    assert cap_drop == CAP_DROP

    # A6: exactly one network, and it must be the runners network by name -
    # not merely "a" network. Create-then-attach would pass a looser check.
    nets = json.loads(inspect(name, "{{json .NetworkSettings.Networks}}"))
    assert list(nets.keys()) == [NETWORK_NAME], (
        f"expected exactly one network [{NETWORK_NAME!r}], got {list(nets.keys())}"
    )

    role_label = inspect(name, '{{index .Config.Labels "io.owui.runner.role"}}')
    assert role_label == role, "role-derived limits must be pinned to the role they came from"

    key = stack.runner_key(uid)
    expected_env = {**_image_baked_env(), **_expected_injected_env(key)}
    actual_env = _container_env(name)
    assert actual_env == expected_env


def test_normal_user_runner_matches_the_v1_baseline(api, stack, uid, cleanup_runners):
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    _assert_v1_container_shape(
        runner_name_for(uid), uid, stack, "user", USER_NANO_CPUS, USER_MEMORY,
    )


def test_admin_runner_matches_the_v1_baseline(api, stack, admin_uid, cleanup_runners):
    """A8/roles.py: admin gets its own resource profile via cfg.admin_* -
    the pre-existing per-role special case this feature widens. Everything
    else (image, security posture, network, injected env keys) must be
    identical to the normal-user path; only nano_cpus/memory differ."""
    cleanup_runners.append(admin_uid)
    assert api.get("/system", headers=stack.user_headers(admin_uid)).status_code == 200
    _assert_v1_container_shape(
        runner_name_for(admin_uid), admin_uid, stack, "admin",
        ADMIN_NANO_CPUS, ADMIN_MEMORY,
    )


@pytest.mark.slow
def test_effective_idle_timeout_is_the_same_global_value_for_user_and_admin(
        api, stack, uid, admin_uid, cleanup_runners):
    """workers.py's idle sweep compares every runner against one global
    cfg.idle_timeout; there is no per-role (let alone per-profile) override
    in v1. This pins that both paths are reclaimed on the SAME window today
    - the fact ticket 06 (lifecycle/idle) will widen to a per-runner value
    read from the resolved profile instead of the global config."""
    cleanup_runners.extend([uid, admin_uid])
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    assert api.get("/system", headers=stack.user_headers(admin_uid)).status_code == 200

    assert _gone_within(runner_name_for(uid), SETTLE), (
        "user runner was not reclaimed within the effective idle timeout"
    )
    assert _gone_within(runner_name_for(admin_uid), SETTLE), (
        "admin runner was not reclaimed within the effective idle timeout"
    )
