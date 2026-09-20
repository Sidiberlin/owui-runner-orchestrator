"""orientation.py's renderer (tickets 04/13): the env string and the
AGENTS.md service section must be produced from ONE list, so they cannot
independently drift. The integration suite's cross-render test
(test_orientation.py::test_cross_render_consistency_env_and_agents_md_agree)
only ever exercises the empty-list case, because DEVGUARD_ENABLED is never
true in the test stack - this file proves the populated-list case directly
against the renderer functions, no live stack required.
"""
from app import orientation
from app.config import DEFAULT_EGRESS_STANCE, Config


def _cfg(devguard_enabled: bool) -> Config:
    return Config(
        orch_api_key="x", master_secret="x", owui_base_url="x",
        owui_admin_token="x", role_cache_ttl=1, role_cache_grace=1,
        owui_api_timeout=1.0, runner_image="x", runners_network="x",
        runner_nano_cpus=1, runner_memory=1, runner_pids=1,
        max_containers=1, idle_timeout=1.0, devguard_enabled=devguard_enabled,
    )


def test_empty_services_render_consistently():
    services = orientation.sandbox_services(_cfg(devguard_enabled=False))
    assert services == []
    assert orientation.render_services_env(services) == ""
    assert "none configured" in orientation.render_agents_md(
        services, DEFAULT_EGRESS_STANCE,
    )


def test_populated_services_appear_in_both_renders_identically():
    """The actual drift-proof: every hostport the env renderer emits must
    appear in the AGENTS.md renderer's output, from the SAME list object."""
    services = orientation.sandbox_services(_cfg(devguard_enabled=True))
    assert services, "expected the DevGuard entry when devguard_enabled=True"

    env_value = orientation.render_services_env(services)
    agents_md = orientation.render_agents_md(services, DEFAULT_EGRESS_STANCE)

    entries = [e for e in env_value.split(",") if e]
    assert entries, "render_services_env produced nothing for a non-empty list"
    for entry in entries:
        hostport = entry.split("=", 1)[0]
        assert hostport in agents_md, f"{hostport} in the env string but missing from AGENTS.md"


def test_sandbox_env_always_carries_all_three_vars():
    for enabled in (False, True):
        env = orientation.sandbox_env(_cfg(devguard_enabled=enabled), DEFAULT_EGRESS_STANCE)
        assert env["SANDBOX_MODE"] == "air-gapped"
        assert env["SANDBOX_EGRESS"] == DEFAULT_EGRESS_STANCE
        assert "SANDBOX_INTERNAL_SERVICES" in env


# --- per-profile egress stance (ADR-0012, ticket 06) ------------------------

def test_sandbox_env_carries_the_resolved_stance_verbatim():
    """The one value ticket 06 actually threads through -- SANDBOX_MODE
    stays the constant "air-gapped" (topology is single for every profile in
    v2.0); SANDBOX_EGRESS is whatever the caller resolved."""
    cfg = _cfg(devguard_enabled=False)
    assert orientation.sandbox_env(cfg, "BLOCKED")["SANDBOX_EGRESS"] == "BLOCKED"
    assert orientation.sandbox_env(cfg, "RELAXED")["SANDBOX_EGRESS"] == "RELAXED"
    assert orientation.sandbox_env(cfg, "BLOCKED")["SANDBOX_MODE"] == "air-gapped"
    assert orientation.sandbox_env(cfg, "RELAXED")["SANDBOX_MODE"] == "air-gapped"


def test_blocked_stance_is_byte_identical_to_the_v1_prose():
    """Ticket 06's own checklist: the strict stance's AGENTS.md text must be
    unchanged from what ticket 01's baseline expects (see
    tests/integration/test_noop_guard.py, which pins the env side of this
    same no-op)."""
    services = orientation.sandbox_services(_cfg(devguard_enabled=False))
    md = orientation.render_agents_md(services, "BLOCKED")
    assert "fail instantly (exit 126), no network touched." in md


def test_a_non_blocked_stance_describes_the_real_shim_behaviour():
    """runner/shims/sandbox-shim.sh (unmodified by this ticket): anything
    other than SANDBOX_EGRESS=BLOCKED gets a real attempt before failing --
    the prose must not claim an instant fail for a stance where that is not
    what actually happens."""
    services = orientation.sandbox_services(_cfg(devguard_enabled=False))
    md = orientation.render_agents_md(services, "RELAXED")
    assert "fail instantly" not in md
    assert "attempt" in md
    assert "exit 126" in md, "must still say the call ultimately fails"


def test_the_two_channels_agree_per_profile():
    """The ticket's own requirement: env and prose stay a single source of
    truth for whichever stance was resolved, not just for the default."""
    cfg = _cfg(devguard_enabled=False)
    services = orientation.sandbox_services(cfg)
    for stance in ("BLOCKED", "RELAXED"):
        env = orientation.sandbox_env(cfg, stance)
        md = orientation.render_agents_md(services, stance)
        assert env["SANDBOX_EGRESS"] == stance
        if stance == "BLOCKED":
            assert "instantly" in md
        else:
            assert "instantly" not in md
