"""A8: the role cache fails CLOSED.

A role we cannot verify is not a role. The failure that matters is the quiet
one: falling open to "probably a user" would let a deleted or demoted account
keep driving a runner indefinitely while OWUI is down.
"""
import asyncio
import os
import socket
import subprocess
import sys
import time

import pytest

from app.config import Config, DEFAULT_PROFILE_NAME, build_profiles, parse_group_map
from app.roles import AccessDenied, Policy, RoleMapper
from conftest import HERE

pytestmark = [pytest.mark.integration, pytest.mark.slow]

# env.test: ROLE_CACHE_TTL=5, ROLE_CACHE_GRACE=30
TTL = 5
GRACE = 30


def _warm(api, stack, uid):
    """Spawn the runner and then take a FRESH cache entry.

    Spawning takes ~11s, which would otherwise be charged against the grace
    window and make these assertions race the clock. The runner must already
    exist before the cache timing starts mattering.
    """
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    time.sleep(TTL + 1)          # force the next call to re-resolve
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200


@pytest.fixture
def owui_restored(stack):
    yield
    stack.start_owui()
    time.sleep(2)


def test_cached_role_survives_a_brief_owui_outage(
        api, stack, uid, cleanup_runners, owui_restored):
    cleanup_runners.append(uid)
    _warm(api, stack, uid)

    stack.stop_owui()
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200, \
        "fresh cache should still serve"

    time.sleep(TTL + 3)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200, \
        "stale-but-within-grace should still serve"


def test_access_is_refused_once_the_grace_window_expires(
        api, stack, uid, cleanup_runners, owui_restored):
    cleanup_runners.append(uid)
    _warm(api, stack, uid)
    stack.stop_owui()
    time.sleep(GRACE + TTL + 5)
    r = api.get("/system", headers=stack.user_headers(uid))
    assert r.status_code == 503, f"expected fail-closed 503, got {r.status_code}"


def test_an_unknown_user_never_gets_in_during_an_outage(api, stack, owui_restored):
    """No cache entry exists, so there is nothing to fall back on. The only
    safe answer is refusal — never a hopeful 200."""
    unseen = "u-never-seen-before"
    stack.stop_owui()
    r = api.get("/system", headers=stack.user_headers(unseen))
    assert r.status_code == 503
    assert r.status_code != 200


def test_recovery_is_automatic(api, stack, uid, cleanup_runners, owui_restored):
    cleanup_runners.append(uid)
    api.get("/system", headers=stack.user_headers(uid))
    stack.stop_owui()
    time.sleep(GRACE + TTL + 5)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 503
    stack.start_owui()
    time.sleep(3)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200


# ---------------------------------------------------------------------------
# Ticket 02 (v2.0 group policy profiles, docs/adr/0012): group NAMES on the
# resolved Policy.
#
# RoleMapper is pure httpx — it needs a real OWUI-shaped HTTP endpoint to
# prove the parse, but nothing Docker provides. `stack`'s stub runs inside
# the compose network under a name (OWUI_BASE_URL=http://stub-owui-test:...)
# that only resolves from inside that network, so these tests run a second,
# throwaway instance of the exact same tests/stub_owui.py directly as a host
# subprocess and drive app.roles.RoleMapper against it. That keeps this the
# same documented-contract stand-in the rest of the suite trusts, without
# requiring the full stack for a prefactor that changes no external
# behaviour (groups are not surfaced anywhere yet — see NIGHT-REPORT/ticket
# 02: they will not be until the profile-resolution tickets that follow).
# ---------------------------------------------------------------------------
GROUP_STUB_PORT = 8199
GROUP_STUB_TOKEN = "roles-prefactor-stub-token"  # noqa: S105 - test-only, throwaway


@pytest.fixture(scope="module")
def group_stub():
    env = {**os.environ, "STUB_TOKEN": GROUP_STUB_TOKEN,
           "STUB_PORT": str(GROUP_STUB_PORT)}
    proc = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "stub_owui.py")], env=env,
    )
    try:
        deadline = time.time() + 15
        up = False
        while time.time() < deadline:
            try:
                with socket.create_connection(
                        ("127.0.0.1", GROUP_STUB_PORT), timeout=0.5):
                    up = True
                    break
            except OSError:
                time.sleep(0.2)
        if not up:
            raise RuntimeError("local OWUI stub for group tests never came up")
        yield f"http://127.0.0.1:{GROUP_STUB_PORT}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


def _cfg(base_url: str, *, group_map_raw: str = "", extra_policy_env: dict | None = None) -> Config:
    """Just enough Config for RoleMapper; every other field is unused here.

    ticket 04: `profiles` must be populated the same way `Config.from_env()`
    populates it (via `build_profiles`) -- `RoleMapper._policy()` now always
    calls `resolve_profile()`, which assumes `profiles[DEFAULT_PROFILE_NAME]`
    exists. `group_map_raw`/`extra_policy_env` let a test declare an extra
    named profile and a GROUP_MAP that references it, same as an operator
    would via POLICY_<NAME>_* + GROUP_MAP env vars.
    """
    profiles = build_profiles(
        default_nano_cpus=500_000_000,
        default_memory=320 * 1024**2,
        default_idle_timeout=60.0,
        default_exec_timeout=120.0,
        default_image="unused:dev",
        default_egress="BLOCKED",
        environ=extra_policy_env or {},
    )
    group_map = parse_group_map(group_map_raw, profiles)
    return Config(
        orch_api_key="unused",
        master_secret="unused",
        owui_base_url=base_url,
        owui_admin_token=GROUP_STUB_TOKEN,
        role_cache_ttl=60,
        role_cache_grace=30,
        owui_api_timeout=5.0,
        runner_image="unused:dev",
        runners_network="unused-net",
        runner_nano_cpus=500_000_000,
        runner_memory=320 * 1024**2,
        runner_pids=256,
        max_containers=3,
        idle_timeout=60.0,
        admin_nano_cpus=500_000_000,
        admin_memory=384 * 1024**2,
        admin_disk_soft=5 * 1024**3,
        disk_soft=5 * 1024**3,
        profiles=profiles,
        group_map=group_map,
    )


def _resolve(cfg: Config, uid: str) -> Policy:
    async def _run() -> Policy:
        mapper = RoleMapper(cfg)
        try:
            return await mapper.resolve(uid)
        finally:
            await mapper.aclose()
    return asyncio.run(_run())


def test_group_names_resolve_for_a_grouped_user(group_stub):
    policy = _resolve(_cfg(group_stub), "u-grouped-1")
    assert policy.groups == ("devs",)
    assert policy.group_ids == ("g-devs",), \
        "ids should remain available for diagnostics alongside names"


def test_an_ungrouped_user_resolves_to_an_empty_set(group_stub):
    policy = _resolve(_cfg(group_stub), "u-nogroups-1")
    assert policy.groups == ()
    assert policy.group_ids == ()


def test_a_user_in_several_groups_gets_every_name(group_stub):
    policy = _resolve(_cfg(group_stub), "u-multigroup-1")
    assert policy.groups == ("devs", "qa")
    assert policy.group_ids == ("g-devs", "g-qa")


def test_malformed_group_entries_are_skipped_not_raised(group_stub):
    """A dict missing `id`, a dict missing `name`, and a non-dict entry are
    all mixed in with two well-formed groups; only the well-formed ones
    should survive, and nothing should raise."""
    policy = _resolve(_cfg(group_stub), "u-messygroups-1")
    assert policy.groups == ("devs", "qa")
    assert policy.group_ids == ("g-devs", "g-qa")


def test_cached_resolution_carries_groups_too(group_stub):
    """The TTL-hit branch of resolve() (a fresh cache entry, second call
    within role_cache_ttl) must return the same groups as the fetch that
    populated the cache — not just the same role."""
    cfg = _cfg(group_stub)

    async def _run():
        mapper = RoleMapper(cfg)
        try:
            first = await mapper.resolve("u-multigroup-cache")
            second = await mapper.resolve("u-multigroup-cache")  # cache hit
            return first, second
        finally:
            await mapper.aclose()

    first, second = asyncio.run(_run())
    assert first.groups == second.groups == ("devs", "qa")
    assert first.group_ids == second.group_ids == ("g-devs", "g-qa")


def test_a_pending_account_is_still_denied_even_with_group_membership(group_stub):
    """Fail-closed is unchanged by this prefactor: groups are attached to the
    Policy object, but AccessDenied is raised before a Policy is ever built
    for a role _gate() refuses (spec.md: "group membership never grants or
    removes access")."""
    with pytest.raises(AccessDenied):
        _resolve(_cfg(group_stub), "p-withgroups-1")


def test_an_unrecognised_role_is_still_denied_even_with_group_membership(group_stub):
    with pytest.raises(AccessDenied):
        _resolve(_cfg(group_stub), "x-withgroups-1")


def test_an_unknown_user_is_still_denied(group_stub):
    with pytest.raises(AccessDenied):
        _resolve(_cfg(group_stub), "nobody-this-stub-has-never-heard-of")


# ---------------------------------------------------------------------------
# Ticket 04 (v2.0 group policy profiles, docs/adr/0012): GROUP_MAP resolution
# attached to Policy, and the best-effort unknown-mapped-group boot check.
# Same stub, same "genuine HTTP round trip against the documented-contract
# stand-in" discipline as ticket 02 above -- groups are still not applied to
# any container in this slice (that is ticket 05), only resolved and carried
# on Policy.profile.
# ---------------------------------------------------------------------------

def test_policy_resolves_to_the_mapped_profile(group_stub):
    cfg = _cfg(group_stub, group_map_raw="devs:heavy",
               extra_policy_env={"POLICY_HEAVY_CPUS": "4"})
    policy = _resolve(cfg, "u-grouped-1")  # -> devs (see groups_for's default)
    assert policy.groups == ("devs",)
    assert policy.profile.name == "heavy"
    assert policy.profile.nano_cpus == 4_000_000_000


def test_policy_falls_back_to_default_for_an_unmapped_group(group_stub):
    cfg = _cfg(group_stub, group_map_raw="qa:heavy",
               extra_policy_env={"POLICY_HEAVY_CPUS": "4"})
    policy = _resolve(cfg, "u-grouped-1")  # devs, not qa -- not mapped
    assert policy.profile.name == DEFAULT_PROFILE_NAME


def test_policy_falls_back_to_default_with_no_group_map_configured(group_stub):
    policy = _resolve(_cfg(group_stub), "u-grouped-1")
    assert policy.profile.name == DEFAULT_PROFILE_NAME


def test_policy_falls_back_to_default_for_an_ungrouped_user(group_stub):
    cfg = _cfg(group_stub, group_map_raw="devs:heavy",
               extra_policy_env={"POLICY_HEAVY_CPUS": "4"})
    policy = _resolve(cfg, "u-nogroups-1")
    assert policy.profile.name == DEFAULT_PROFILE_NAME


def test_a_user_in_several_groups_resolves_by_mapping_priority(group_stub):
    cfg = _cfg(
        group_stub, group_map_raw="qa:light,devs:heavy",
        extra_policy_env={"POLICY_HEAVY_CPUS": "4", "POLICY_LIGHT_CPUS": "1"},
    )
    policy = _resolve(cfg, "u-multigroup-1")  # devs + qa
    assert policy.profile.name == "light", "qa:light is listed first in GROUP_MAP"


def test_a_pending_account_in_a_mapped_group_is_still_denied(group_stub):
    """Group membership never grants access -- a mapped group only selects a
    profile once admission is already decided (spec.md: "group membership
    never grants or removes access")."""
    cfg = _cfg(group_stub, group_map_raw="devs:heavy",
               extra_policy_env={"POLICY_HEAVY_CPUS": "4"})
    with pytest.raises(AccessDenied):
        _resolve(cfg, "p-withgroups-1")


def test_an_unrecognised_role_in_a_mapped_group_is_still_denied(group_stub):
    cfg = _cfg(group_stub, group_map_raw="devs:heavy",
               extra_policy_env={"POLICY_HEAVY_CPUS": "4"})
    with pytest.raises(AccessDenied):
        _resolve(cfg, "x-withgroups-1")


def _unknown_groups(cfg: Config) -> list:
    async def _run():
        mapper = RoleMapper(cfg)
        try:
            return await mapper.unknown_mapped_groups()
        finally:
            await mapper.aclose()
    return asyncio.run(_run())


def test_unknown_mapped_groups_flags_a_group_the_roster_does_not_know(group_stub):
    cfg = _cfg(group_stub, group_map_raw="devs:heavy,ghost-team:heavy",
               extra_policy_env={"POLICY_HEAVY_CPUS": "4"})
    assert _unknown_groups(cfg) == ["ghost-team"]


def test_unknown_mapped_groups_is_empty_when_every_mapped_group_is_known(group_stub):
    cfg = _cfg(group_stub, group_map_raw="devs:heavy,qa:heavy",
               extra_policy_env={"POLICY_HEAVY_CPUS": "4"})
    assert _unknown_groups(cfg) == []


def test_unknown_mapped_groups_is_empty_with_no_group_map(group_stub):
    """No OWUI round trip is needed -- or made -- when GROUP_MAP is unset."""
    assert _unknown_groups(_cfg(group_stub)) == []


def test_unknown_mapped_groups_is_best_effort_against_an_unreachable_owui():
    """Never raises: an OWUI the orchestrator cannot currently reach is a
    reason to skip the check, not to fail the boot sequence."""
    cfg = _cfg("http://127.0.0.1:1", group_map_raw="devs:heavy",
               extra_policy_env={"POLICY_HEAVY_CPUS": "4"})
    assert _unknown_groups(cfg) == []
