"""OWUI's discovery probe and /files/serve hardening, against a live stack.

Both were found only by connecting to a real OWUI. The first live attempt
failed with "Failed to connect to the terminal server" because the probe
carries no X-User-Id; the second is a stored-XSS path that was verified on the
wire before being closed.
"""
import pytest

pytestmark = pytest.mark.integration


def test_discovery_probe_answers_without_a_user(api, stack):
    """OWUI's verify has no user in scope yet, so it sends only the key."""
    r = api.get("/api/config", headers=stack.orch_headers())
    assert r.status_code == 200, r.text
    assert "features" in r.json()


def test_discovery_probe_still_requires_the_key(api):
    assert api.get("/api/config").status_code == 401


def test_discovery_probe_does_not_spawn_a_runner(api, stack):
    """A verify click must not cost a container slot."""
    before = len(api.get("/_orch/runners", headers=stack.orch_headers()).json())
    api.get("/api/config", headers=stack.orch_headers())
    after = len(api.get("/_orch/runners", headers=stack.orch_headers()).json())
    assert after == before


def test_policies_probe_is_never_2xx(api, stack):
    """A 2xx on /api/v1/policies makes OWUI classify this as an enterprise
    orchestrator and drive it with a policy/lifecycle API v1 does not have."""
    r = api.get("/api/v1/policies", headers=stack.orch_headers())
    assert not (200 <= r.status_code < 300), r.status_code


def test_terminal_is_advertised_true_and_pty_is_still_denied(api, stack):
    """v2.0 QA finding (2026-09-20): OWUI gates the model's exec/run_command
    tool call on `features.terminal`, not only the PTY pane. Advertising
    `terminal:false` (the v1 behaviour this replaces) silently broke exec for
    every user. `terminal` is now always True; the actual PTY-pane guarantee
    -- /api/terminals still 403s -- is covered independently by
    test_denylist.py, unaffected by this advertisement."""
    feats = api.get("/api/config", headers=stack.orch_headers()).json()["features"]
    assert feats["terminal"] is True


def test_files_serve_is_sandboxed(api, stack, uid, cleanup_runners):
    """N25: agent-authored HTML comes back through OWUI's own origin."""
    cleanup_runners.append(uid)
    h = stack.user_headers(uid)
    assert api.get("/system", headers=h).status_code == 200
    api.post("/files/write", headers=h, json={
        "path": "probe.html",
        "content": "<html><body><script>1</script></body></html>",
    })
    r = api.get("/files/serve/home/user/probe.html", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers.get("content-security-policy") == "sandbox"
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_ordinary_file_reads_are_not_sandboxed(api, stack, uid, cleanup_runners):
    cleanup_runners.append(uid)
    h = stack.user_headers(uid)
    assert api.get("/system", headers=h).status_code == 200
    api.post("/files/write", headers=h,
             json={"path": "plain.txt", "content": "hi\n"})
    r = api.get("/files/read", headers=h, params={"path": "plain.txt"})
    assert r.status_code == 200
    assert "content-security-policy" not in {k.lower() for k in r.headers}
