"""Doc test (ticket 14): README's 'What the agent sees' section must
grep-match what the code actually injects, not describe a design that
already drifted from the implementation.

Ticket 09 (v2.0 group policy profiles, docs/adr/0012) extends this same
discipline to the "## Policy profiles" section and .env.example's
GROUP_MAP/POLICY_<NAME>_* documentation.
"""
import os

from app import orientation
from app.config import (
    DEFAULT_EGRESS_STANCE,
    Config,
    build_profiles,
    parse_duration,
    parse_group_map,
    parse_size,
)

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
        ),
        DEFAULT_EGRESS_STANCE,
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


# --- Policy profiles doc-drift guard (ADR-0012, ticket 09) ------------------

def _env_example_value(key: str) -> str:
    with open(os.path.join(ROOT, ".env.example")) as fh:
        for line in fh:
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].split("#", 1)[0].strip()
    raise KeyError(key)


def test_policy_profiles_section_exists_and_uses_the_glossary_terms():
    section = _readme_section("## Policy profiles")
    assert section
    # CONTEXT.md's exact glossary terms (Policy profile, GROUP_MAP,
    # Groups (OWUI)) -- the ticket's own requirement.
    assert "Policy profile" in section
    assert "GROUP_MAP" in section
    assert "Groups (OWUI)" in section
    assert "first" in section.lower() and "wins" in section.lower(), \
        "first-match priority must be documented"
    assert "default" in section.lower(), "default-equals-today must be documented"
    assert "rename" in section.lower(), "the group-rename caveat must be documented"


def test_env_example_documents_group_map_and_the_policy_convention():
    with open(os.path.join(ROOT, ".env.example")) as fh:
        text = fh.read()
    assert "GROUP_MAP=" in text
    assert "POLICY_<NAME>_<FIELD>" in text


def test_readme_worked_example_boot_log_matches_the_real_parser():
    """The doc-drift guard the ticket asks for: this reads the worked
    example's OWN `.env` lines and its OWN claimed boot-log output straight
    out of the README section (never re-typing either here), runs the first
    through the real `build_profiles`/`parse_group_map`, and asserts the
    result is exactly the second -- a hand-typed example that silently drifts
    from the actual parser's output fails this test, not just a human review.
    """
    section = _readme_section("## Policy profiles")
    worked = section.split("### Worked example", 1)[1]
    blocks = worked.split("```")
    # blocks[1] is the ".env" fence, blocks[3] is the boot-log fence.
    env_block, log_block = blocks[1].strip(), blocks[3].strip()

    env_vars = dict(
        line.split("=", 1) for line in env_block.splitlines() if "=" in line
    )
    policy_env = {k: v for k, v in env_vars.items() if k.startswith("POLICY_")}

    profiles = build_profiles(
        default_nano_cpus=int(float(_env_example_value("RUNNER_CPUS")) * 1_000_000_000),
        default_memory=parse_size(_env_example_value("RUNNER_MEMORY")),
        default_idle_timeout=parse_duration(_env_example_value("IDLE_TIMEOUT")),
        default_exec_timeout=float(_env_example_value("OPEN_TERMINAL_EXECUTE_TIMEOUT")),
        default_image=_env_example_value("RUNNER_IMAGE"),
        default_egress=DEFAULT_EGRESS_STANCE,
        environ=policy_env,
    )
    group_map = parse_group_map(env_vars.get("GROUP_MAP", ""), profiles)
    assert group_map, "the worked example's own GROUP_MAP line failed to parse"

    expected_lines = []
    for name in sorted(profiles):
        p = profiles[name]
        expected_lines.append(
            (
                "policy profile %-12s cpus=%.2f memory=%dMiB idle=%.0fs "
                "exec=%.0fs image=%s egress=%s"
            )
            % (
                name, p.nano_cpus / 1_000_000_000, p.memory // 1024**2,
                p.idle_timeout, p.exec_timeout, p.image, p.egress,
            )
        )
    assert log_block.splitlines() == expected_lines
