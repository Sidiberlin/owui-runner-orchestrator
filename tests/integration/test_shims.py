"""L3 shim tests (tickets 04/05/13). Hard rule: never fake output. A blocked
call gets a REAL failure plus an explanation on real stderr; an allowlisted
internal call gets the real binary's real response, untouched.

These exec straight into the runner container (the host's own docker, not
through the orchestrator's socket-proxy, exactly like conftest.curl_in), so
they see precisely what a driving agent's shell tool call would see.
"""
import subprocess
import time

import pytest

from conftest import runner_name_for

pytestmark = pytest.mark.integration


def _exec_in(container: str, *args: str, timeout: float = 30.0):
    p = subprocess.run(
        ["docker", "exec", container, *args],
        capture_output=True, text=True, timeout=timeout,
    )
    return p.returncode, p.stdout, p.stderr


def test_external_curl_is_blocked_fast_with_an_explanation(api, stack, uid, cleanup_runners):
    """L3-T1."""
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    container = runner_name_for(uid)

    start = time.monotonic()
    rc, out, err = _exec_in(container, "curl", "-s", "https://example.com")
    elapsed = time.monotonic() - start

    assert rc == 126
    assert elapsed < 2.0, f"blocked call took {elapsed:.2f}s under SANDBOX_EGRESS=BLOCKED"
    assert "sandbox:" in err
    assert out == "", "a blocked call must never produce a fake body"


def test_proxy_flag_fails_fast_regardless_of_target(api, stack, uid, cleanup_runners):
    """L3-T3: -x/--proxy bypasses the allowlist otherwise, so it gets no
    exception - instant refusal even before any destination is examined."""
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    container = runner_name_for(uid)

    start = time.monotonic()
    rc, out, err = _exec_in(
        container, "curl", "-s", "-x", "http://1.2.3.4:9", "http://example.com",
    )
    elapsed = time.monotonic() - start

    assert rc == 126
    assert elapsed < 2.0
    assert "sandbox:" in err


def test_apt_get_is_always_blocked(api, stack, uid, cleanup_runners):
    """L3-T6: apt-get has no internal target at all - always external."""
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    container = runner_name_for(uid)

    rc, out, err = _exec_in(container, "apt-get", "update")
    assert rc == 126
    assert "sandbox:" in err


def test_loopback_curl_is_never_blocked(api, stack, uid, cleanup_runners):
    """The image's own HEALTHCHECK calls curl against 127.0.0.1 - talking to
    yourself is not egress, and this must keep working under
    SANDBOX_EGRESS=BLOCKED like every other runner."""
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    container = runner_name_for(uid)

    rc, out, err = _exec_in(
        container, "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
        "http://127.0.0.1:8000/system",
    )
    assert rc == 0
    assert out.strip() in ("200", "401", "403")


def test_opencode_binary_is_absent_from_the_image(api, stack, uid, cleanup_runners):
    """Ticket 10: the opencode CLI was stripped - nothing on PATH resolves
    it, in the runner image or anywhere the shims might shadow it from."""
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    container = runner_name_for(uid)

    rc, out, _ = _exec_in(container, "sh", "-c", "command -v opencode")
    assert rc != 0
    assert out.strip() == ""
