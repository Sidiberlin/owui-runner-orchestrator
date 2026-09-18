"""Reverse-proxy behaviour (Q5 surface, C8 streaming, C7 stale ids)."""
import threading
import time

import pytest

from conftest import runner_name_for

pytestmark = pytest.mark.integration


@pytest.fixture
def runner(api, stack, uid, cleanup_runners):
    cleanup_runners.append(uid)
    assert api.get("/system", headers=stack.user_headers(uid)).status_code == 200
    return uid


def _run(api, stack, uid, command):
    """A command that finishes quickly. POST /execute is synchronous."""
    r = api.post("/execute", headers=stack.user_headers(uid),
                 json={"command": command})
    assert r.status_code == 200, r.text
    return r.json()


def _start_background(stack, uid, command):
    """Fire a long-running command WITHOUT waiting for the response.

    Measured against the real service: POST /execute blocks until the process
    completes, and the documented `wait` parameter does not cap it (wait=0, 1,
    2, 5 and omitted all blocked for the full 30s of a `sleep 30`). So the only
    way to have a genuinely running process is to leave the request in flight —
    which is exactly what OWUI's agent does when it kicks off a long build.

    Returns (process_id, thread) once the process is visible as running.
    """
    def _fire():
        try:
            with stack.client(timeout=300.0) as c:
                c.post("/execute", headers=stack.user_headers(uid),
                       json={"command": command})
        except Exception:
            pass

    th = threading.Thread(target=_fire, daemon=True)
    th.start()
    with stack.client() as c:
        for _ in range(40):
            r = c.get("/execute", headers=stack.user_headers(uid))
            if r.status_code == 200:
                procs = r.json()
                if isinstance(procs, dict):
                    procs = procs.get("processes") or procs.get("items") or []
                live = [p for p in procs
                        if isinstance(p, dict) and p.get("status") == "running"]
                if live:
                    return live[0]["id"], th
            time.sleep(1)
    raise AssertionError(f"process for {command!r} never showed up as running")


def test_all_five_execute_endpoints_are_reachable(api, stack, runner):
    """The briefed allowlist exposed only two of these. Losing DELETE meant no
    kill switch; losing GET /execute made the idle rule unanswerable.

    Ordering matters, and not for a tidy reason. Measured against the real
    service, BOTH `POST /execute` and `GET /execute/{id}/status` block until
    the process completes — `status` is not an offset poll for new output, and
    returned nothing for 25s even with output already emitted. So `status` can
    only be asked about a process that has finished, and a process blocked on
    stdin finishes only once stdin arrives.
    """
    h = stack.user_headers(runner)

    # 1. POST /execute - synchronous, so use something that finishes.
    done = _run(api, stack, runner, "echo quick")
    pid_done = done["id"]

    # 2. GET /execute/{id}/status - on the COMPLETED process.
    assert api.get(f"/execute/{pid_done}/status", headers=h).status_code == 200

    # 3. GET /execute - the process list the idle rule depends on.
    assert api.get("/execute", headers=h).status_code == 200

    # 4. POST /execute/{id}/input - stdin to a process waiting on it.
    pid_stdin, _th = _start_background(stack, runner, "read x; echo GOT:$x")
    assert api.post(f"/execute/{pid_stdin}/input", headers=h,
                    json={"input": "hello\n"}).status_code == 200

    # 5. DELETE /execute/{id} - the kill switch, proven against something that
    #    would otherwise run for five minutes.
    pid_kill, _th2 = _start_background(stack, runner, "sleep 300")
    assert api.delete(f"/execute/{pid_kill}", headers=h).status_code == 200


def test_files_round_trip(api, stack, runner):
    h = stack.user_headers(runner)
    w = api.post("/files/write", headers=h,
                 json={"path": "round.txt", "content": "trip\n"})
    assert w.status_code == 200
    assert w.json()["path"] == "/home/user/round.txt", "N7: must land on the volume"
    r = api.get("/files/read", headers=h, params={"path": "round.txt"})
    assert r.status_code == 200 and "trip" in r.text


def test_relative_paths_resolve_to_the_workspace(api, stack, runner):
    """N10: WorkingDir was /app (root-owned), so relative writes failed with
    'Permission denied' while absolute paths worked."""
    r = _run(api, stack, runner, "pwd")
    out = "".join(c.get("data", "") for c in r.get("output", []))
    assert out.strip() == "/home/user"


def test_session_id_gives_each_chat_tab_its_own_cwd(api, stack, runner):
    a = stack.user_headers(runner, session="tab-a")
    b = stack.user_headers(runner, session="tab-b")
    api.post("/execute", headers=a, json={"command": "mkdir -p subdir && cd subdir"})
    api.post("/execute", headers=a, json={"command": "cd subdir"})
    rb = api.post("/execute", headers=b, json={"command": "pwd"})
    out = "".join(c.get("data", "") for c in rb.json().get("output", []))
    assert out.strip() == "/home/user", "a cd in one tab leaked into another"


def test_upstream_errors_pass_through_unmangled(api, stack, runner):
    h = stack.user_headers(runner)
    # Wrong body shape -> the runner's own 422 plus its validation detail.
    r = api.post("/execute/nonexistent-id/input", headers=h, json={"data": "x"})
    assert r.status_code in (404, 422)
    if r.status_code == 422:
        assert "input" in r.text
    # Wrong method -> upstream 405, not a proxy 500.
    assert api.get("/files/archive", headers=h,
                   params={"path": "round.txt"}).status_code in (404, 405)


def test_large_response_is_streamed_not_buffered(api, stack, runner):
    """C8. Buffering would turn one big read into an orchestrator OOM."""
    h = stack.user_headers(runner)
    api.post("/execute", headers=h, json={
        "command": "head -c 12000000 /dev/urandom | base64 > big.txt"})
    total = 0
    with stack.client(timeout=120).stream(
            "GET", "/files/read", headers=h, params={"path": "big.txt"}) as resp:
        assert resp.status_code == 200
        for chunk in resp.iter_bytes():
            total += len(chunk)
    assert total > 10_000_000, f"only got {total} bytes"


def test_stale_process_id_after_replacement_is_explained(api, stack, runner):
    """C7: a bare upstream 404 tells the agent nothing actionable."""
    h = stack.user_headers(runner)
    pid, _th = _start_background(stack, runner, "sleep 120")
    api.delete(f"/_orch/runners/{runner}", headers=stack.orch_headers())
    r = api.get(f"/execute/{pid}/status", headers=h)
    assert r.status_code == 409, r.status_code
    body = r.json()
    assert body.get("reason") == "runner_replaced"
    assert "workspace" in body.get("detail", "").lower()


def test_orchestrator_routes_do_not_shadow_upstream_paths(api, stack, runner):
    """N17: everything the orchestrator owns lives under /_orch/."""
    r = api.get("/system", headers=stack.user_headers(runner))
    assert r.status_code == 200
    # /system is upstream's, and must not be intercepted.
    assert "_orch" not in r.text
