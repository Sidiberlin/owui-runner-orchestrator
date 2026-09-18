"""Doc test (ticket 14): README's 'What the agent sees' section must
grep-match what the code actually injects, not describe a design that
already drifted from the implementation.
"""
import os

from app import orientation
from app.config import Config

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _readme_section(heading: str) -> str:
    with open(os.path.join(ROOT, "README.md")) as fh:
        text = fh.read()
    start = text.index(heading)
    nxt = text.index("\n## ", start + len(heading))
    return text[start:nxt]


def test_what_the_agent_sees_section_exists():
    section = _readme_section("## What the agent sees")
    assert section


def test_static_sandbox_vars_match_the_renderer():
    section = _readme_section("## What the agent sees")

    # The two constant vars never depend on config - assert the literal
    # values in the doc match the renderer's literal values, not just that
    # some SANDBOX_* text exists.
    devguard_off = orientation.sandbox_env(
        Config(
            orch_api_key="x", master_secret="x", owui_base_url="x",
            owui_admin_token="x", role_cache_ttl=1, role_cache_grace=1,
            owui_api_timeout=1.0, runner_image="x", runners_network="x",
            runner_nano_cpus=1, runner_memory=1, runner_pids=1,
            max_containers=1, idle_timeout=1.0,
        )
    )
    assert f"SANDBOX_MODE={devguard_off['SANDBOX_MODE']}" in section
    assert f"SANDBOX_EGRESS={devguard_off['SANDBOX_EGRESS']}" in section
    assert "SANDBOX_INTERNAL_SERVICES=" in section


def test_devguard_service_description_matches_the_renderer():
    """When DevGuard is the only configured service, its description in the
    README must be the literal string the renderer emits - not a paraphrase
    that can quietly go stale."""
    cfg = Config(
        orch_api_key="x", master_secret="x", owui_base_url="x",
        owui_admin_token="x", role_cache_ttl=1, role_cache_grace=1,
        owui_api_timeout=1.0, runner_image="x", runners_network="x",
        runner_nano_cpus=1, runner_memory=1, runner_pids=1,
        max_containers=1, idle_timeout=1.0, devguard_enabled=True,
    )
    services = orientation.sandbox_services(cfg)
    assert services, "expected the DevGuard entry when devguard_enabled=True"
    section = _readme_section("## What the agent sees")
    for s in services:
        assert f"{s.hostport}={s.description}" in section
