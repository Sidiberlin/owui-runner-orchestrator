"""Agent orientation (tickets 04/05/13): the data channel (SANDBOX_* env)
and the prose channel (AGENTS.md) must never drift, AGENTS.md must survive
teardown/recreate without clobbering a user's own edits, and it must be
re-seeded on a genuinely fresh volume.
"""
import pytest

from conftest import container_exists, inspect, runner_name_for, sh

pytestmark = pytest.mark.integration


def _env_of(container: str) -> dict[str, str]:
    out = inspect(container, "{{range .Config.Env}}{{println .}}{{end}}")
    env: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            env[k] = v
    return env


def test_sandbox_env_is_present_on_every_runner(api, stack, uid, cleanup_runners):
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200

    env = _env_of(runner_name_for(uid))
    assert env.get("SANDBOX_MODE") == "air-gapped"
    assert env.get("SANDBOX_EGRESS") == "BLOCKED"
    assert "SANDBOX_INTERNAL_SERVICES" in env


def test_agents_md_is_seeded_on_first_spawn(api, stack, uid, cleanup_runners):
    cleanup_runners.append(uid)
    h = stack.user_headers(uid)
    assert api.get("/system", headers=h).status_code == 200

    r = api.get("/files/read", headers=h, params={"path": "AGENTS.md"})
    assert r.status_code == 200
    assert "AIR-GAPPED BY DESIGN" in r.text
    assert "SANDBOX_INTERNAL_SERVICES" in r.text


def test_cross_render_consistency_env_and_agents_md_agree(api, stack, uid, cleanup_runners):
    """One renderer produces both (orchestrator/app/orientation.py). This
    test stack never enables DevGuard, so this only ever exercises the
    empty-list case here (env empty, AGENTS.md says "none configured") -
    unit/test_orientation.py proves the populated-list case directly
    against the renderer, no live stack required."""
    cleanup_runners.append(uid)
    h = stack.user_headers(uid)
    assert api.get("/system", headers=h).status_code == 200

    env = _env_of(runner_name_for(uid))
    services_env = env.get("SANDBOX_INTERNAL_SERVICES", "")
    agents_md = api.get("/files/read", headers=h, params={"path": "AGENTS.md"}).text

    entries = [e for e in services_env.split(",") if e]
    if not entries:
        assert "none configured" in agents_md
    for entry in entries:
        hostport = entry.split("=", 1)[0]
        assert hostport in agents_md, f"{hostport} is in the env but missing from AGENTS.md"


def test_agents_md_survives_teardown_and_recreate_without_being_clobbered(
        api, stack, uid, cleanup_runners):
    cleanup_runners.append(uid)
    h = stack.user_headers(uid)
    assert api.get("/system", headers=h).status_code == 200

    custom = "# my own notes\nDo not overwrite this.\n"
    w = api.post("/files/write", headers=h, json={"path": "AGENTS.md", "content": custom})
    assert w.status_code == 200

    api.delete(f"/_orch/runners/{uid}", headers=stack.orch_headers())
    assert not container_exists(runner_name_for(uid))

    assert api.get("/system", headers=h).status_code == 200  # respawns onto the same volume
    r = api.get("/files/read", headers=h, params={"path": "AGENTS.md"})
    assert r.status_code == 200
    assert r.json()["content"] == custom, "the seed step clobbered the user's own AGENTS.md"


def test_agents_md_is_reseeded_on_a_fresh_volume(api, stack, uid, cleanup_runners):
    cleanup_runners.append(uid)
    h = stack.user_headers(uid)
    assert api.get("/system", headers=h).status_code == 200

    api.delete(f"/_orch/runners/{uid}", headers=stack.orch_headers())
    assert not container_exists(runner_name_for(uid))
    sh("docker", "volume", "rm", "-f", f"runner-ws-{uid}")

    assert api.get("/system", headers=h).status_code == 200  # fresh volume this time
    r = api.get("/files/read", headers=h, params={"path": "AGENTS.md"})
    assert r.status_code == 200
    assert "AIR-GAPPED BY DESIGN" in r.text
