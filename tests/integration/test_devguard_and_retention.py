"""The last two v1 spec items: the DevGuard seam and R2 retention."""
import pytest

from conftest import env_value, inspect, runner_name_for, sh

pytestmark = pytest.mark.integration


# --- (1) DevGuard PIP_INDEX_URL seam ---------------------------------------
def test_pip_index_url_is_injected_at_create_time(api, stack, uid, cleanup_runners):
    """Runners have zero egress, so installs only work through a proxy joined
    to the same internal network. This is the seam that points at it."""
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    env = inspect(runner_name_for(uid), "{{range .Config.Env}}{{println .}}{{end}}")
    assert f"PIP_INDEX_URL={env_value('PIP_INDEX_URL')}" in env


def test_the_seam_opens_no_egress(api, stack, uid, cleanup_runners):
    """Setting it must not change the isolation posture — the proxy is
    reachable because it is inside the network, not because it was loosened."""
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    nets = inspect(runner_name_for(uid),
                   "{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}").split()
    assert nets == [env_value("RUNNERS_NETWORK")]
    code, _ = stack.curl_in(runner_name_for(uid), "--max-time", "5", "https://pypi.org")
    assert code == 0, "PIP_INDEX_URL must not come with egress"


# --- (2) R2 retention -------------------------------------------------------
def test_status_reports_the_retention_policy(api, stack):
    s = api.get("/_orch/status", headers=stack.orch_headers()).json()
    assert s["volume_retention_days"] == float(env_value("VOLUME_RETENTION_DAYS"))
    assert s["workspace_ceiling_mb"] > 0


def test_sweep_defaults_to_dry_run(api, stack):
    r = api.post("/_orch/retention/sweep", headers=stack.orch_headers())
    assert r.status_code == 200
    assert r.json()["dry_run"] is True, "a data-deleting endpoint must not default to acting"


def test_sweep_deletes_nothing_for_active_workspaces(
        api, stack, uid, cleanup_runners):
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    body = api.post("/_orch/retention/sweep?dry_run=true",
                    headers=stack.orch_headers()).json()
    assert body["enabled"] is True
    assert uid not in [v["uid"] for v in body["volumes"]]
    # and the volume is still there
    assert sh("docker", "volume", "ls", "-q", "-f", f"name=runner-ws-{uid}",
              check=False).strip()


def test_sweep_requires_the_orchestrator_key(api):
    assert api.post("/_orch/retention/sweep").status_code == 401


def test_a_live_runners_volume_is_never_swept(api, stack, uid, cleanup_runners):
    """Guard 2, through the real stack rather than a stub."""
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    body = api.post("/_orch/retention/sweep?dry_run=false",
                    headers=stack.orch_headers()).json()
    assert uid not in [v["uid"] for v in body["volumes"]]
    assert sh("docker", "volume", "ls", "-q", "-f", f"name=runner-ws-{uid}",
              check=False).strip(), "deleted a live runner's workspace"
