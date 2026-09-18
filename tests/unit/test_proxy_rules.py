"""Denylist matching (Q5) and header hygiene.

Over-matching would block legitimate paths; under-matching would expose the
SSRF surface the denylist exists to close.
"""
import pytest

from app.proxy import _DROP_REQ, _DROP_RESP, is_denied

DENY = ("/proxy", "/ports", "/api/terminals")


@pytest.mark.parametrize("path", [
    "/proxy", "/ports", "/api/terminals",
    "/proxy/", "/proxy/http://evil", "/ports/8080", "/api/terminals/ws",
])
def test_denied(path):
    assert is_denied(path, DENY) is True


@pytest.mark.parametrize("path", [
    "/system", "/execute", "/execute/abc/status", "/files/read",
    "/files/serve/index.html",
    # Prefix matching must be segment-aware: these merely START with the text.
    "/proxyfoo", "/portscan", "/api/terminalsx", "/portsmouth",
])
def test_not_denied(path):
    assert is_denied(path, DENY) is False


def test_leading_slash_is_optional():
    assert is_denied("proxy", DENY) is True


def test_hop_by_hop_headers_are_stripped_both_ways():
    for h in ("connection", "keep-alive", "transfer-encoding", "upgrade", "te"):
        assert h in _DROP_REQ and h in _DROP_RESP


def test_client_authorization_never_reaches_the_runner():
    # K1 must be swapped for the runner's own derived key, never forwarded.
    assert "authorization" in _DROP_REQ


def test_content_encoding_is_preserved():
    # aiter_raw() yields still-encoded bytes; stripping this header would
    # leave the client unable to decode the body.
    assert "content-encoding" not in _DROP_RESP
