"""Streaming reverse proxy to a runner's Open Terminal (Q5 denylist, C8).

DENYLIST, NOT ALLOWLIST (Q5)
    The original spec allowlisted four paths and silently 404'd everything
    else — including three of the five /execute endpoints, so there was no way
    to cancel a runaway process, answer a stdin prompt, or ask "is this runner
    busy?" (which the idle rule needs). It would also break any sidebar call
    nobody predicted, invisibly.

    So: forward everything, deny three prefixes loudly.

        /proxy          pure SSRF surface
        /ports          same
        /api/terminals  WebSocket PTY, explicitly out of scope for v1

NEVER BUFFER (C8)
    Request bodies stream in via request.stream(); responses stream out via
    aiter_raw() with stream=True. Buffering would turn one /files/archive of a
    large workspace into an orchestrator OOM, and would break the long-poll
    shape of /execute.

    Client disconnect propagates: Starlette cancels the streaming task, the
    BackgroundTask fires resp.aclose(), and httpx tears down the upstream
    connection instead of leaking it.
"""
from __future__ import annotations

import logging
import re

import httpx
from fastapi import Request, Response
from starlette.background import BackgroundTask
from starlette.responses import JSONResponse, StreamingResponse

log = logging.getLogger(__name__)

# Hop-by-hop headers must not be forwarded (RFC 9110 7.6.1). `host` is dropped
# so httpx sets it for the upstream, and `content-length` because we re-stream.
_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}
_DROP_REQ = _HOP | {"host", "content-length", "authorization"}
# content-encoding is deliberately KEPT: aiter_raw() yields the still-encoded
# bytes, so stripping it would leave the client unable to decode them.
_DROP_RESP = _HOP

_PROCESS_PATH = re.compile(r"^/execute/[^/]+(?:/|$)")
_SERVE_PATH = re.compile(r"^/files/serve(?:/|$)")


def harden_served_content(path: str, headers: dict[str, str], csp: str) -> None:
    """Neutralise agent-authored HTML served back through OWUI's origin.

    VERIFIED LIVE, not theorised. An agent can write any file into its own
    workspace; /files/serve returns it with the file's own content-type, and
    OWUI's terminal proxy passes that straight through from OWUI's origin:

        GET http://<owui>/api/v1/terminals/<id>/files/serve/home/user/x.html
        -> 200  content-type: text/html; charset=utf-8
           no CSP, no X-Frame-Options, no X-Content-Type-Options, script intact

    That is a stored-XSS path into the OWUI session: prompt injection in a
    cloned repo writes the file, and anything that opens the URL runs script
    with access to OWUI's cookies and localStorage.

    `Content-Security-Policy: sandbox` drops the response into an opaque
    origin, so scripts do not run and OWUI's storage is unreachable, while
    static previews still render. OWUI strips only transfer-encoding,
    connection, content-encoding and content-length, so these survive to the
    browser — confirmed on the wire.
    """
    if not csp or not _SERVE_PATH.match(path if path.startswith("/") else "/" + path):
        return
    headers["content-security-policy"] = csp
    headers["x-content-type-options"] = "nosniff"


def denied_prefix(path: str, deny_prefixes: tuple[str, ...]) -> str | None:
    """Return the denylist entry that blocks `path`, or None."""
    p = path if path.startswith("/") else "/" + path
    for d in deny_prefixes:
        if p == d or p.startswith(d.rstrip("/") + "/"):
            return d
    return None


def is_denied(path: str, deny_prefixes: tuple[str, ...]) -> bool:
    return denied_prefix(path, deny_prefixes) is not None


def _request_headers(request: Request, runner_key: str) -> dict[str, str]:
    headers = {
        k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQ
    }
    # The runner authenticates with its own derived key, never K1 (N1).
    headers["authorization"] = f"Bearer {runner_key}"
    # X-User-Id / X-Session-Id pass through verbatim: Open Terminal keys its
    # session-aware cwd off X-Session-Id, so a `cd` in one chat tab must not
    # leak into another.
    return headers


def _response_headers(resp: httpx.Response) -> dict[str, str]:
    return {k: v for k, v in resp.headers.items() if k.lower() not in _DROP_RESP}


# Bodies at or under this are read into memory so the request can be retried
# once if the upstream connection dies. Anything larger streams straight
# through and is not retryable — the C8 guarantee wins over retryability for
# big uploads, because buffering those is what would OOM the orchestrator.
RETRYABLE_BODY_LIMIT = 1024 * 1024


async def _body_for_retry(request: Request) -> bytes | None:
    """Return the body if it is small enough to replay, else None (stream it)."""
    raw_len = request.headers.get("content-length")
    if raw_len is not None:
        try:
            if int(raw_len) > RETRYABLE_BODY_LIMIT:
                return None
        except ValueError:
            return None
        return await request.body()
    # No content-length (chunked or empty). Peek up to the limit.
    chunks, total = [], 0
    async for chunk in request.stream():
        chunks.append(chunk)
        total += len(chunk)
        if total > RETRYABLE_BODY_LIMIT:
            return None  # too big, and already partly consumed - see caller
    return b"".join(chunks)


async def forward(
    request: Request,
    client: httpx.AsyncClient,
    base_url: str,
    runner_key: str,
    path: str,
    replaced_reason: str | None = None,
    serve_csp: str = "",
) -> Response:
    target = f"{base_url}/{path.lstrip('/')}"
    if request.url.query:
        target = f"{target}?{request.url.query}"

    headers = _request_headers(request, runner_key)
    declared = request.headers.get("content-length")
    stream_body = declared is not None and int(declared) > RETRYABLE_BODY_LIMIT
    body: bytes | None = None
    if not stream_body:
        body = await _body_for_retry(request)
        stream_body = body is None

    async def _send() -> httpx.Response:
        content = request.stream() if stream_body else (body or b"")
        req = client.build_request(
            request.method, target, headers=headers, content=content
        )
        return await client.send(req, stream=True)

    try:
        resp = await _send()
    except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError) as exc:
        # A connection-level failure, not an application error. The usual cause
        # is a pooled connection the runner closed (or a container that was
        # replaced behind the same DNS name). Retry once when the body can be
        # replayed; a streamed body has already been consumed and cannot be.
        if stream_body:
            log.warning("upstream %s failed mid-stream, cannot retry: %s", target, exc)
            return JSONResponse(
                {"detail": f"runner is not reachable: {exc}"}, status_code=502
            )
        log.info("retrying %s after connection-level failure: %s", target, exc)
        try:
            resp = await _send()
        except httpx.HTTPError as exc2:
            log.warning("upstream %s failed on retry: %s", target, exc2)
            return JSONResponse(
                {"detail": f"runner is not reachable: {exc2}"}, status_code=502
            )
    except httpx.HTTPError as exc:
        log.warning("upstream %s failed: %s", target, exc)
        return JSONResponse(
            {"detail": f"runner is not reachable: {exc}"}, status_code=502
        )

    # C7: a process id from a previous incarnation is gone, and a bare 404 does
    # not tell the agent why. If this runner replaced a torn-down one, say so.
    if (
        resp.status_code == 404
        and replaced_reason
        and _PROCESS_PATH.match("/" + path.lstrip("/"))
    ):
        await resp.aclose()
        return JSONResponse(
            {
                "detail": (
                    "This process belonged to a previous runner session that was "
                    f"ended ({replaced_reason}). Its output is gone. Re-run the "
                    "command; your files in the workspace are unaffected."
                ),
                "reason": "runner_replaced",
            },
            status_code=409,
        )

    out_headers = _response_headers(resp)
    harden_served_content(path, out_headers, serve_csp)
    return StreamingResponse(
        resp.aiter_raw(),
        status_code=resp.status_code,
        headers=out_headers,
        background=BackgroundTask(resp.aclose),
    )
