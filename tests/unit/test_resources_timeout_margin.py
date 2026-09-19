"""Ticket 16: guards the fix for a zero-margin timeout race in
tests/integration/test_resources.py.

The client's own httpx read timeout for
test_over_allocating_memory_is_killed_not_swapped_onto_the_host used to
equal the server-side `wait` value exactly (both 60s), so ANY overhead -
network, the orchestrator's proxy hop, GC, a loaded host - made the client
give up a moment before the server would have answered: a false failure
with no real bug behind it (confirmed during the night-shift suite runs:
passed cleanly on every retry). This is a static, no-docker check, so it
fails loudly on a plain `pytest unit` run if the margin is ever narrowed
back to zero, without needing to reproduce host-load flakiness to catch
the regression.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SOURCE_PATH = os.path.join(ROOT, "tests", "integration", "test_resources.py")

_WAIT_RE = re.compile(r"^WAIT_SECONDS\s*=\s*(\d+)\s*$", re.MULTILINE)
_MARGIN_RE = re.compile(r"^TIMEOUT_MARGIN_SECONDS\s*=\s*(\d+)\s*$", re.MULTILINE)


def _read_source() -> str:
    with open(_SOURCE_PATH) as fh:
        return fh.read()


def test_client_timeout_has_a_real_margin_over_the_server_side_wait():
    source = _read_source()
    wait_match = _WAIT_RE.search(source)
    assert wait_match, "expected a WAIT_SECONDS constant in test_resources.py"
    margin_match = _MARGIN_RE.search(source)
    assert margin_match, (
        "no TIMEOUT_MARGIN_SECONDS constant found - the client timeout has "
        "no margin over the server-side wait at all (zero-margin race, "
        "ticket 16)"
    )
    margin = int(margin_match.group(1))
    assert margin >= 15, (
        f"TIMEOUT_MARGIN_SECONDS={margin}s is too tight to survive real "
        "network/proxy overhead under host load (ticket 16)"
    )


def test_the_over_allocation_call_actually_uses_the_wider_timeout():
    """The constants existing is not enough - confirm the api.post() call
    they exist for actually passes the widened timeout, not just the
    client's untouched (and separately zero-margin) default."""
    source = _read_source()
    assert "timeout=WAIT_SECONDS + TIMEOUT_MARGIN_SECONDS" in source, (
        "the widened timeout constants exist but are not wired into the "
        "api.post() call they were added for"
    )
