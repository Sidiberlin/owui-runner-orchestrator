"""orientation.py's renderer (tickets 04/13): the env string and the
AGENTS.md service section must be produced from ONE list, so they cannot
independently drift. The integration suite's cross-render test
(test_orientation.py::test_cross_render_consistency_env_and_agents_md_agree)
only ever exercises the empty-list case, because DEVGUARD_ENABLED is never
true in the test stack - this file proves the populated-list case directly
against the renderer functions, no live stack required.
"""
from app import orientation
from app.config import Config


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
    assert "none configured" in orientation.render_agents_md(services)


def test_populated_services_appear_in_both_renders_identically():
    """The actual drift-proof: every hostport the env renderer emits must
    appear in the AGENTS.md renderer's output, from the SAME list object."""
    services = orientation.sandbox_services(_cfg(devguard_enabled=True))
    assert services, "expected the DevGuard entry when devguard_enabled=True"

    env_value = orientation.render_services_env(services)
    agents_md = orientation.render_agents_md(services)

    entries = [e for e in env_value.split(",") if e]
    assert entries, "render_services_env produced nothing for a non-empty list"
    for entry in entries:
        hostport = entry.split("=", 1)[0]
        assert hostport in agents_md, f"{hostport} in the env string but missing from AGENTS.md"


def test_sandbox_env_always_carries_all_three_vars():
    for enabled in (False, True):
        env = orientation.sandbox_env(_cfg(devguard_enabled=enabled))
        assert env["SANDBOX_MODE"] == "air-gapped"
        assert env["SANDBOX_EGRESS"] == "BLOCKED"
        assert "SANDBOX_INTERNAL_SERVICES" in env
