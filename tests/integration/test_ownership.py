"""Cross-stack runner ownership.

Found in production, not in review: a second orchestrator on the same Docker
host adopted the LIVE stack's runner (reconcile filtered on the managed label
alone) and then reaped it 60 seconds later under its own shorter IDLE_TIMEOUT.
Container names are `runner-<uid>` and therefore identical across deployments,
so the name is no defence either.
"""
import pytest

from conftest import env_value, inspect, sh

pytestmark = pytest.mark.integration

FOREIGN = "some-other-orchestrator-net"


def test_runners_are_stamped_with_their_owning_network(
        api, stack, uid, cleanup_runners):
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    owner = inspect(f"runner-{uid}",
                    '{{index .Config.Labels "io.owui.runner.network"}}')
    assert owner == env_value("RUNNERS_NETWORK")


def test_a_foreign_runner_is_neither_adopted_nor_reaped(api, stack):
    """The exact production failure, inverted into an assertion."""
    name = "runner-foreign-probe"
    sh("docker", "rm", "-f", name, check=False)
    sh("docker", "create", "--name", name,
       # N5: this LXC host cannot load AppArmor profiles, so every container
       # needs this or it fails to start.
       "--security-opt", "apparmor=unconfined",
       "--label", "io.owui.runner.managed=1",
       "--label", "io.owui.runner.uid=foreign-probe",
       "--label", "io.owui.runner.key-nonce=deadbeef",
       "--label", "io.owui.runner.version=1",
       f"--label=io.owui.runner.network={FOREIGN}",
       "--entrypoint", "sleep", env_value("RUNNER_IMAGE"), "300")
    sh("docker", "start", name)
    try:
        stack.restart_orchestrator()
        rows = api.get("/_orch/runners", headers=stack.orch_headers()).json()
        assert "foreign-probe" not in [r["uid"] for r in rows], \
            "adopted a runner belonging to another orchestrator"
        # and it must still be alive - reaping someone else's runner is the
        # failure that killed a live user's session.
        assert sh("docker", "ps", "-q", "-f", f"name=^{name}$", check=False).strip(), \
            "reaped a runner belonging to another orchestrator"
    finally:
        sh("docker", "rm", "-f", name, check=False)
