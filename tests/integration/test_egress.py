"""Zero egress (brief test (a), hardened per v1.1).

`curl 1.1.1.1` was the briefed test and it is the least interesting case. The
real threat is a runner reaching OWUI on the LAN to hit its admin API, or the
Docker host itself. `internal: true` does not obviously block the bridge
gateway, so that is asserted explicitly.
"""
import pytest

from conftest import inspect, runner_name_for, sh

pytestmark = pytest.mark.integration


@pytest.fixture
def runner(api, stack, uid, cleanup_runners):
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    return uid


def _unreachable(stack, uid, target):
    code, _ = stack.curl_in(runner_name_for(uid), "--max-time", "5", target)
    return code == 0


def test_public_internet_is_unreachable(stack, runner):
    assert _unreachable(stack, runner, "https://1.1.1.1")


def test_the_lan_is_unreachable(stack, runner):
    """The actual threat: reaching OWUI to abuse its admin API."""
    for target in ("http://192.168.1.101:8080", "http://192.168.0.1",
                   "http://10.0.0.1"):
        assert _unreachable(stack, runner, target), target


def test_the_docker_host_gateway_is_unreachable(stack, runner):
    gw = sh("sh", "-c", "ip route | awk '/default/{print $3; exit}'")
    if gw:
        assert _unreachable(stack, runner, f"http://{gw}")


def test_dns_resolution_is_dead(stack, runner):
    out = sh("docker", "exec", runner_name_for(runner), "sh", "-c",
             "getent hosts github.com >/dev/null 2>&1 && echo RESOLVED || echo DEAD",
             check=False)
    assert "DEAD" in out


def test_attached_to_exactly_one_internal_network(stack, runner):
    """A6: assert on container config, not just a probe from inside.

    A runner that kept the default bridge would still fail a curl test only by
    luck of ordering. This is the deterministic check.
    """
    nets = inspect(runner_name_for(runner),
                   "{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}").split()
    assert len(nets) == 1, f"expected exactly one network, got {nets}"
    assert inspect(nets[0], "{{.Internal}}") == "true"

