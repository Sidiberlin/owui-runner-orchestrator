"""The Package Seam, measured against a LIVE DevGuard (ADR-0008, ADR-0010).

These are fleet-verification tests, not hermetic ones, and they deliberately
do not use the `stack` fixture. The normal suite runs an isolated project
whose RUNNERS_NETWORK is `owui-runners-test` and whose PIP_INDEX_URL points at
`devguard-test:3141`, a host that does not exist -- it asserts the variable is
injected, never that a package arrives. Everything below is the other half:
does a package actually get through, and does a malicious one actually not.

Opt in explicitly, against a host running the devguard profile:

    ORCH_BASE_URL=http://127.0.0.1:8080 \
    ORCH_API_KEY=... SEAM_UID=<an Open WebUI user id> \
    DEVGUARD_LIVE=1 ./.venv/bin/python -m pytest integration/test_package_seam.py

Every claim here was wrong at least once when reasoned about instead of run:
the npm URLs were assumed broken and work, the pip URL was assumed good and
could not fetch a single wheel, and the firewall itself blocked nothing at all
until the malicious feed was imported.
"""
import os

import httpx
import pytest

from conftest import sh

pytestmark = [pytest.mark.integration, pytest.mark.devguard]

PIP_PKG = "requests"
NPM_PKG = "left-pad"
# Both are in DevGuard's malicious feed AND still served by their registry, so
# an upstream 404 cannot masquerade as a firewall block. Most flagged packages
# are withdrawn quickly; re-pick from malicious_affected_components joined to
# malicious_packages ordered by published desc when these finally disappear.
MALICIOUS_NPM = "ac-polyfills"
MALICIOUS_PIP = "index-forum"

ORCH_BASE_URL = os.getenv("ORCH_BASE_URL", "http://127.0.0.1:8080")
ORCH_API_KEY = os.getenv("ORCH_API_KEY", "")
SEAM_UID = os.getenv("SEAM_UID", "")

pytestmark.append(pytest.mark.skipif(
    os.getenv("DEVGUARD_LIVE") != "1",
    reason="live DevGuard fleet test; set DEVGUARD_LIVE=1 to run"))


def _container(name_filter: str) -> str:
    out = sh("docker", "ps", "--filter", f"name={name_filter}",
             "--format", "{{.Names}}", check=False).strip()
    return out.splitlines()[0] if out else ""


@pytest.fixture(scope="module")
def runner() -> str:
    """Spawn a runner through the live orchestrator and return its name."""
    for var, val in (("ORCH_API_KEY", ORCH_API_KEY), ("SEAM_UID", SEAM_UID)):
        if not val:
            pytest.skip(f"{var} is not set")
    with httpx.Client(base_url=ORCH_BASE_URL, timeout=120.0) as c:
        c.get("/system", headers={"Authorization": f"Bearer {ORCH_API_KEY}",
                                  "X-User-Id": SEAM_UID})
    name = _container(f"runner-{SEAM_UID}")
    if not name:
        pytest.fail("the live orchestrator did not spawn a runner")
    return name


def _run(runner: str, cmd: str) -> str:
    """Run a command as the unprivileged `user`, the way an agent does."""
    return sh("docker", "exec", "-u", "user", runner, "sh", "-lc", cmd,
              check=False, timeout=300)


def _env(runner: str) -> dict[str, str]:
    raw = sh("docker", "inspect", runner,
             "--format", "{{range .Config.Env}}{{println .}}{{end}}")
    out = {}
    for line in raw.splitlines():
        k, _, v = line.partition("=")
        out[k] = v
    return out


# --- the seam reaches the container, pointed somewhere usable --------------
def test_both_seam_variables_are_injected(runner):
    env = _env(runner)
    assert env.get("PIP_INDEX_URL"), "PIP_INDEX_URL missing"
    assert env.get("NPM_CONFIG_REGISTRY"), "NPM_CONFIG_REGISTRY missing"


def test_pip_trusts_the_host_it_actually_contacts(runner):
    """pip refuses a plain-http index unless the host it talks to is trusted.
    That host is the shim (ADR-0010), not DevGuard, so deriving this from
    DEVGUARD_BASE_URL silently breaks every install."""
    env = _env(runner)
    host = env["PIP_INDEX_URL"].split("//", 1)[1].split("/", 1)[0].split(":", 1)[0]
    assert env.get("PIP_TRUSTED_HOST") == host


def test_the_runner_has_the_package_managers_the_seam_configures(runner):
    """Configuring PIP_INDEX_URL and NPM_CONFIG_REGISTRY in an image with
    neither pip nor npm is what this stack shipped with until it was run."""
    assert "pip" in _run(runner, "python3 -m pip --version").lower()
    assert _run(runner, "npm --version").strip()


# --- benign packages arrive, through the firewall --------------------------
def test_benign_pip_install_succeeds_through_the_proxy(runner):
    _run(runner, f"python3 -m pip install --no-cache-dir --user -q {PIP_PKG}")
    assert "OK" in _run(runner, f"python3 -c 'import {PIP_PKG}; print(\"OK\")'"), \
        "pip could not install through DevGuard"


def test_benign_npm_install_succeeds_through_the_proxy(runner):
    """This works only because npm's own replace-registry-host default
    rewrites the npmjs.org tarball host onto our registry -- DevGuard serves
    the packument unrewritten. replace-registry-host=never would break it."""
    _run(runner, f"cd ~ && npm install {NPM_PKG} --no-audit --no-fund")
    assert "OK" in _run(runner, f"test -d ~/node_modules/{NPM_PKG} && echo OK"), \
        "npm could not install through DevGuard"


# --- malicious packages do not ---------------------------------------------
def test_malicious_npm_package_is_blocked(runner):
    out = _run(runner, f"cd ~ && npm install {MALICIOUS_NPM} --no-audit --no-fund 2>&1 || true")
    assert "403" in out, f"malicious npm package was not blocked:\n{out}"
    assert "ABSENT" in _run(
        runner, f"test -d ~/node_modules/{MALICIOUS_NPM} && echo PRESENT || echo ABSENT")


def test_malicious_pip_package_is_blocked(runner):
    out = _run(runner,
               f"python3 -m pip install --no-cache-dir --user {MALICIOUS_PIP} 2>&1 || true")
    assert "No matching distribution" in out or "403" in out, \
        f"malicious pip package was not blocked:\n{out}"


def test_the_malicious_feed_is_not_empty():
    """The firewall checks a table. An empty table blocks nothing and looks
    exactly like a working firewall from the outside -- which is how this
    fleet ran until `devguard-cli vulndb import` was finally executed."""
    pg = _container("devguard-postgres")
    assert pg, "devguard-postgres is not running"
    n = sh("docker", "exec", pg, "psql", "-U", "devguard", "-d", "devguard",
           "-tAc", "SELECT count(*) FROM malicious_packages", check=False)
    assert int(n.strip()) > 0, \
        "malicious feed is empty; run `devguard-cli vulndb import`"


# --- and none of it opened a way out ---------------------------------------
@pytest.mark.parametrize("host", [
    "https://1.1.1.1",
    "https://registry.npmjs.org",
    "https://files.pythonhosted.org",
])
def test_package_access_did_not_open_egress(runner, host):
    """The whole point of the seam: runners reach registries ONLY through
    DevGuard. files.pythonhosted.org is listed because ADR-0010's shim exists
    precisely to avoid ever needing a route to it."""
    out = _run(runner, f"curl -sS -m 6 -o /dev/null -w '%{{http_code}}' {host} 2>&1 || true")
    assert "000" in out or "not resolve" in out or "Could not connect" in out, \
        f"{host} is reachable from a runner: {out}"


def test_the_runner_is_only_on_the_runners_network(runner):
    nets = sh("docker", "inspect", runner,
              "--format", "{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}").split()
    assert len(nets) == 1, f"runner is on more than the runners network: {nets}"
