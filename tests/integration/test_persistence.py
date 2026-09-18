"""Brief test (c), plus the writability assertion it was missing.

The briefed test only checked that the volume survived. It would have passed
while N7 was broken (files landing on the ephemeral layer) and while C5 was
broken (volume present but not writable by the runner user).
"""
import pytest

from conftest import container_exists, inspect, runner_name_for, sh

pytestmark = pytest.mark.integration


def test_workspace_survives_teardown_and_stays_writable(
        api, stack, uid, cleanup_runners):
    cleanup_runners.append(uid)
    h = stack.user_headers(uid)

    assert api.get("/system", headers=h).status_code == 200
    api.post("/files/write", headers=h,
             json={"path": "keepme.txt", "content": "survives\n"})

    api.delete(f"/_orch/runners/{uid}", headers=stack.orch_headers())
    assert not container_exists(runner_name_for(uid))

    assert api.get("/system", headers=h).status_code == 200  # respawn
    r = api.get("/files/read", headers=h, params={"path": "keepme.txt"})
    assert r.status_code == 200 and "survives" in r.text

    # The part the briefed test omitted: can the runner user still WRITE?
    w = api.post("/files/write", headers=h,
                 json={"path": "after.txt", "content": "still writable\n"})
    assert w.status_code == 200, "workspace survived but became read-only"


def test_fresh_volume_is_chowned_to_the_runner_user(api, stack, uid, cleanup_runners):
    """C5/N8: Docker creates named volumes root-owned. The entrypoint's
    `chown -R user:user $HOME` is what fixes it, and that needs CAP_CHOWN."""
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    owner = sh("docker", "exec", runner_name_for(uid), "stat", "-c", "%U:%G",
               "/home/user")
    assert owner == "user:user"


def test_volume_is_mounted_at_home_not_workspace(api, stack, uid, cleanup_runners):
    """N7: the entrypoint hardcodes HOME=/home/user, so a volume at /workspace
    would silently leave the agent's real state on the ephemeral layer."""
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    dest = inspect(runner_name_for(uid),
                   "{{range .Mounts}}{{.Destination}}{{end}}")
    assert dest == "/home/user"


def test_agent_state_also_persists(api, stack, uid, cleanup_runners):
    """Because HOME is the volume, openCode's own config survives a teardown
    too — which is the reason N7 chose /home/user over /workspace."""
    cleanup_runners.append(uid)
    h = stack.user_headers(uid)
    assert api.get("/system", headers=h).status_code == 200
    api.post("/execute", headers=h, json={
        "command": "mkdir -p ~/.config/demo && echo pref > ~/.config/demo/settings",
        "wait": 15})
    api.delete(f"/_orch/runners/{uid}", headers=stack.orch_headers())
    api.get("/system", headers=h)
    r = api.get("/files/read", headers=h, params={"path": ".config/demo/settings"})
    assert r.status_code == 200 and "pref" in r.text
