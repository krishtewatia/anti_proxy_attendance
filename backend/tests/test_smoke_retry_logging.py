"""Retries in scripts/smoke_e2e.py must say which check they belong to and why.

A flake that is silently retried teaches nothing. Every retry prints the name
of the check, the attempt number and the HTTP status (or the connection error)
that caused it. No network and no Docker are used here: the request function
is a stub.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "smoke_e2e.py"

if not SCRIPT.is_file():  # e.g. inside the backend image, where only backend/ is present
    pytest.skip("scripts/smoke_e2e.py is not available here", allow_module_level=True)

_spec = importlib.util.spec_from_file_location("smoke_e2e_under_test", SCRIPT)
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    monkeypatch.setattr(smoke.time, "sleep", lambda seconds: None)


def _sender(*responses):
    queue = list(responses)
    calls = []

    def send():
        calls.append(1)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    send.calls = calls
    return send


def test_a_retry_logs_the_check_name_the_attempt_and_the_http_status(capsys):
    checks = smoke.Checks()
    send = _sender(
        (503, {"detail": "Vision service unavailable. Please retry."}),
        (503, {"detail": "Vision service unavailable. Please retry."}),
        (200, {"faces": []}),
    )

    status, body = smoke.call_with_retry(send, checks, "student B recognized and marked")

    assert (status, body) == (200, {"faces": []})
    assert len(send.calls) == 3
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("RETRY")]
    assert lines == [
        "RETRY - student B recognized and marked | attempt 1 got HTTP 503 "
        "(Vision service unavailable. Please retry.)",
        "RETRY - student B recognized and marked | attempt 2 got HTTP 503 "
        "(Vision service unavailable. Please retry.)",
    ]
    assert checks.retries == 2


@pytest.mark.parametrize("status", [502, 503, 504])
def test_gateway_and_unavailable_statuses_are_retried(status, capsys):
    checks = smoke.Checks()
    send = _sender((status, {}), (200, {}))

    assert smoke.call_with_retry(send, checks, "some check")[0] == 200
    assert f"got HTTP {status}" in capsys.readouterr().out


def test_a_dropped_connection_is_retried_and_names_the_error(capsys):
    checks = smoke.Checks()
    send = _sender((None, {"error": "ConnectionResetError"}), (200, {}))

    smoke.call_with_retry(send, checks, "frame after finalization is rejected (409)")

    out = capsys.readouterr().out
    assert "RETRY - frame after finalization is rejected (409) | attempt 1 got no HTTP response" in out
    assert "ConnectionResetError" in out


@pytest.mark.parametrize("status", [200, 400, 401, 403, 404, 409, 413, 422, 429, 500])
def test_any_other_status_is_a_verdict_and_is_not_retried(status, capsys):
    """A 401 or a 409 is the answer being tested; retrying it would hide a real failure."""
    checks = smoke.Checks()
    send = _sender((status, {"detail": "the answer"}))

    assert smoke.call_with_retry(send, checks, "some check") == (status, {"detail": "the answer"})
    assert len(send.calls) == 1
    assert checks.retries == 0
    assert "RETRY" not in capsys.readouterr().out


def test_retries_stop_and_the_last_response_is_returned(capsys):
    checks = smoke.Checks()
    send = _sender((503, {"detail": "still busy"}))

    status, body = smoke.call_with_retry(send, checks, "some check", attempts=3)

    assert (status, body) == (503, {"detail": "still busy"})
    assert len(send.calls) == 3
    assert checks.retries == 2  # the third response is returned, not retried


def test_describe_response_covers_status_reason_and_missing_response():
    assert smoke.describe_response(503, {"detail": "busy"}) == "HTTP 503 (busy)"
    assert smoke.describe_response(409, {}) == "HTTP 409"
    assert smoke.describe_response(200, None) == "HTTP 200"
    assert smoke.describe_response(None, {"error": "TimeoutError"}) == "no HTTP response (TimeoutError)"
    assert smoke.describe_response(None, None) == "no HTTP response (connection failed)"
    assert len(smoke.describe_response(500, {"detail": "x" * 500})) < 140


def test_a_retry_counts_separately_from_pass_and_fail(capsys):
    checks = smoke.Checks()
    checks.retry("a check", 1, 503, {"detail": "busy"})
    checks.check("a check", True)

    assert (checks.passed, checks.failed, checks.skipped, checks.retries) == (1, 0, 0, 1)
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("RETRY - a check | attempt 1 got HTTP 503")
    assert out[1] == "PASS - a check"


def test_no_request_in_the_script_retries_silently():
    """Every loop that sleeps and tries again must go through the logged retry."""
    source = SCRIPT.read_text(encoding="utf-8")
    flow = source[source.index("def run_flow(") : source.index("def main(")]

    # The only sleeps in the flow are the backend start-up wait and the two
    # places that log a RETRY line immediately before sleeping.
    sleeps = [i for i in range(len(flow)) if flow.startswith("time.sleep(", i)]
    logged = 0
    for position in sleeps:
        preceding = flow[max(0, position - 400) : position]
        if "checks.retry(" in preceding:
            logged += 1
    assert len(sleeps) - logged == 1, "a retry loop in run_flow sleeps without logging a RETRY line"
    assert "status not in (None, 502, 503, 504)" not in flow
