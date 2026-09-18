"""Cross-user isolation — the property the original review called untested.

The threat is not a malicious operator. It is LLM-generated code running in a
runner: a prompt injected through a cloned repo's README is enough to get
arbitrary commands executed. So the question these tests answer is:

    given arbitrary code execution inside one runner, what can it reach?

The v1 answer (Q7) is a deliberate bargain: keep ONE shared internal network
for simplicity and for the future DevGuard proxy, and make lateral movement
useless with per-runner derived keys (N1/A3) plus a socket proxy on a separate
network (N2). These tests hold that bargain to account — including the part
that documents what is intentionally still reachable.
"""
import pytest

from conftest import inspect, runner_name_for

pytestmark = pytest.mark.integration


@pytest.fixture
def two_users(api, stack, uid, admin_uid, cleanup_runners):
    a, b = uid, admin_uid
    cleanup_runners.extend([a, b])
    assert api.get("/system", headers=stack.user_headers(a)).status_code == 200
    assert api.get("/system", headers=stack.user_headers(b)).status_code == 200
    return a, b


def test_each_user_gets_their_own_container_and_volume(two_users):
    a, b = two_users
    assert inspect(runner_name_for(a), "{{.Id}}") != inspect(runner_name_for(b), "{{.Id}}")
    vol = "{{range .Mounts}}{{.Name}}{{end}}"
    assert inspect(runner_name_for(a), vol) != inspect(runner_name_for(b), vol)


def test_one_users_files_are_invisible_to_another(api, stack, two_users):
    a, b = two_users
    api.post("/files/write", headers=stack.user_headers(a),
             json={"path": "secret.txt", "content": "alice private data\n"})
    # Through the proxy, as B:
    r = api.get("/files/read", headers=stack.user_headers(b),
                params={"path": "secret.txt"})
    assert r.status_code != 200 or "alice private data" not in r.text
    # And on B's actual filesystem:
    code, body = stack.runner_request(b, "/files/read?path=secret.txt")
    assert "alice private data" not in body


def test_a_runners_key_does_not_work_on_a_sibling_runner(stack, two_users):
    """The core of the Q7 bargain (N1/A3).

    If runners shared one OPEN_TERMINAL_API_KEY, any agent could read it from
    its own environment and then drive every other user's workspace. Per-runner
    derived keys make the shared network survivable.
    """
    a, b = two_users
    code, _ = stack.cross_request(a, b, "/system")
    assert code == 401, f"runner {a} authenticated against runner {b} (got {code})"


def test_every_runner_gets_a_distinct_key(stack, two_users):
    """An agent can trivially read its OWN key out of /proc/self/environ. That
    is fine — and only fine — because the key is scoped to one container."""
    a, b = two_users
    assert stack.runner_key(a) != stack.runner_key(b)


def test_siblings_are_reachable_on_the_network_by_design(stack, two_users):
    """Documents the ACCEPTED risk rather than pretending it away.

    Network-per-runner was rejected for v1. If someone later weakens the key
    derivation, this test is the reminder that the network will not save them:
    the runners can absolutely see each other.
    """
    a, b = two_users
    code, _body = stack.cross_request(a, b, "/system")
    # 401 means the TCP connection succeeded and Open Terminal answered. A
    # connection failure would surface as 0. The distinction is the whole
    # point: the network is flat, the key is the control.
    assert code == 401, (
        f"expected reachable-but-unauthorised (401), got {code}. "
        "If this is 0 the network topology changed and the Q7 reasoning "
        "should be revisited."
    )


def test_a_runner_cannot_reach_the_docker_socket_proxy(stack, two_users):
    """N2: a socket proxy reachable by runners would be worse than none.

    With CONTAINERS=1 and POST=1 the proxy can create a container with an
    arbitrary bind mount, so runner -> proxy would be a direct path to host
    root. It lives on `control`, which runners are not attached to.
    """
    a, _ = two_users
    code, _body = stack.curl_in(
        runner_name_for(a), "http://docker-socket-proxy:2375/_ping")
    assert code == 0, f"runner reached the socket proxy (HTTP {code})"


def test_a_runner_cannot_reach_the_docker_socket_directly(stack, two_users):
    a, _ = two_users
    code, body = stack.curl_in(
        runner_name_for(a), "--unix-socket", "/var/run/docker.sock",
        "http://localhost/_ping")
    assert code != 200, "runner has direct access to the Docker socket"


def test_a_runner_does_not_hold_the_orchestrator_api_key(stack, two_users):
    """K1 must never be injected into a runner: it would let agent code
    impersonate any user via X-User-Id."""
    a, _ = two_users
    env = inspect(runner_name_for(a), "{{range .Config.Env}}{{println .}}{{end}}")
    assert stack.key not in env
    assert "ORCH_API_KEY" not in env
    assert stack.master_secret not in env, "the key-derivation seed leaked into a runner"
