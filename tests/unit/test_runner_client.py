"""Busy-detection for the idle rule (C7).

The bias here is deliberate and load-bearing: when in doubt, report BUSY.
A false 'busy' wastes a container slot for one sweep. A false 'idle' kills a
user's running build. Those costs are not symmetric.
"""
from app.runner_client import has_running_process


def test_running_process_is_busy():
    assert has_running_process([{"id": "1", "status": "running"}]) is True


def test_all_terminal_states_are_idle():
    for s in ["done", "exited", "finished", "killed", "failed", "error", "terminated"]:
        assert has_running_process([{"id": "1", "status": s}]) is False, s


def test_empty_list_is_idle():
    assert has_running_process([]) is False


def test_one_live_process_among_finished_ones_is_busy():
    assert has_running_process([
        {"id": "1", "status": "done"},
        {"id": "2", "status": "done"},
        {"id": "3", "status": "running"},
    ]) is True


def test_unknown_status_is_treated_as_busy():
    assert has_running_process([{"id": "1", "status": "reticulating"}]) is True


def test_unparseable_entry_is_treated_as_busy():
    assert has_running_process(["not-a-dict"]) is True


def test_missing_status_without_exit_code_is_busy():
    assert has_running_process([{"id": "1"}]) is True


def test_missing_status_with_exit_code_is_finished():
    assert has_running_process([{"id": "1", "exit_code": 0}]) is False
