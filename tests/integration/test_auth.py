"""K1 + X-User-Id + role gating (Lane C auth chain)."""
import pytest

pytestmark = pytest.mark.integration


def test_missing_api_key_is_rejected(api, stack, uid):
    assert api.get("/system", headers={"X-User-Id": uid}).status_code == 401


def test_wrong_api_key_is_rejected(api, uid):
    r = api.get("/system", headers={
        "Authorization": "Bearer definitely-not-the-key", "X-User-Id": uid})
    assert r.status_code == 401


def test_valid_key_without_user_id_is_a_clear_400(api, stack):
    r = api.get("/system", headers=stack.orch_headers())
    assert r.status_code == 400
    # The message must point at the actual misconfiguration (a personal rather
    # than system-level OWUI connection), not just say "bad request".
    assert "x-user-id" in r.text.lower()


def test_pending_user_is_forbidden(api, stack):
    r = api.get("/system", headers=stack.user_headers("p-pending-user"))
    assert r.status_code == 403
    assert "pending" in r.text.lower()


def test_unknown_user_is_forbidden(api, stack):
    # OWUI answers 400 for USER_NOT_FOUND; that must surface as 403, not 500.
    r = api.get("/system", headers=stack.user_headers("nobody-at-all"))
    assert r.status_code == 403


def test_unrecognised_role_is_denied_not_guessed(api, stack):
    # A future OWUI role we have never heard of must fail closed.
    r = api.get("/system", headers=stack.user_headers("x-auditor-person"))
    assert r.status_code == 403


def test_orchestrator_admin_surface_requires_the_key(api, stack):
    assert api.get("/_orch/status").status_code == 401
    assert api.get("/_orch/status", headers=stack.orch_headers()).status_code == 200


def test_healthz_is_open_and_leaks_nothing(api):
    r = api.get("/_orch/healthz")
    assert r.status_code == 200 and r.text.strip() == "ok"


def test_interactive_docs_are_disabled(api):
    # This service is reachable from the runners network, where hostile agent
    # code runs. It must not publish its own schema there.
    for path in ("/docs", "/redoc", "/openapi.json"):
        # They must not return a schema; 401/403/404 are all acceptable.
        assert api.get(path).status_code != 200, path
