"""Q5: denylist posture, not allowlist."""
import pytest

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("path", ["/proxy", "/ports", "/api/terminals"])
def test_denied_prefixes_are_forbidden(api, stack, uid, path):
    r = api.get(path, headers=stack.user_headers(uid))
    assert r.status_code == 403


@pytest.mark.parametrize("path", ["/proxy/http://169.254.169.254/", "/ports/8080"])
def test_denial_covers_subpaths(api, stack, uid, path):
    assert api.get(path, headers=stack.user_headers(uid)).status_code == 403


def test_denial_happens_without_spawning_a_runner(api, stack, uid):
    """A blocked path must not cost a container slot."""
    from conftest import container_exists, runner_name_for
    api.get("/proxy", headers=stack.user_headers(uid))
    assert not container_exists(runner_name_for(uid))
