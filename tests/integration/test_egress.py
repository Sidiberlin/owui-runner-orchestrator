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


# ---------------------------------------------------------------------------
# Ticket 06 (v2.0 group policy profiles, docs/adr/0012): "a stance is an
# explanation to the agent, not a hole in the topology" -- proven here by
# effect, the same way every other zero-egress guarantee in this file is.
# env.test maps GROUP_MAP=ops:heavy (POLICY_HEAVY_EGRESS=RELAXED) to a group
# only a uid containing "opsgroup" ever carries (see test_lifecycle.py's own
# ticket-05 section for why this cannot perturb any other test).
# ---------------------------------------------------------------------------
def test_a_relaxed_stance_still_has_zero_real_egress(api, stack, cleanup_runners):
    """SANDBOX_EGRESS=RELAXED changes only whether the SHIM fast-refuses or
    lets the real binary attempt first (runner/shims/sandbox-shim.sh,
    unmodified by this ticket) -- the network topology enforces zero egress
    either way. `curl_in` calls /usr/bin/curl directly, the same bypass
    every other test in this file uses to prove topology rather than shim
    behaviour."""
    heavy_uid = "u-opsgroup-egress-topology"
    cleanup_runners.append(heavy_uid)
    assert api.get("/system", headers=stack.user_headers(heavy_uid)).status_code == 200
    assert _unreachable(stack, heavy_uid, "https://1.1.1.1")


def test_attached_to_exactly_one_internal_network(stack, runner):
    """A6: assert on container config, not just a probe from inside.

    A runner that kept the default bridge would still fail a curl test only by
    luck of ordering. This is the deterministic check.
    """
    nets = inspect(runner_name_for(runner),
                   "{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}").split()
    assert len(nets) == 1, f"expected exactly one network, got {nets}"
    assert inspect(nets[0], "{{.Internal}}") == "true"

