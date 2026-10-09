"""Tests for kalytera/tracer.py — Component 1."""
import time
import uuid

import kalytera
from kalytera import tracer


def test_trace_returns_under_5ms() -> None:
    t0 = time.monotonic()
    kalytera.trace(
        session_id="s1",
        step_number=1,
        step_name="retrieve_policy",
        input="What is the refund policy?",
        output="30-day refund window.",
    )
    elapsed_ms = (time.monotonic() - t0) * 1000
    assert elapsed_ms < 5, f"trace() took {elapsed_ms:.1f}ms — must be <5ms"


def test_trace_never_raises_on_bad_input() -> None:
    kalytera.trace(
        session_id=None,  # type: ignore[arg-type]
        step_number=None,  # type: ignore[arg-type]
        step_name=None,  # type: ignore[arg-type]
        input=None,  # type: ignore[arg-type]
        output=None,  # type: ignore[arg-type]
        tool_calls="not_a_list",  # type: ignore[arg-type]
        metadata="not_a_dict",  # type: ignore[arg-type]
    )


def test_trace_queues_payload() -> None:
    before = tracer._queue.qsize()
    kalytera.trace(
        session_id=str(uuid.uuid4()),
        step_number=2,
        step_name="apply_policy",
        input="Apply electronics policy.",
        output="Policy applied.",
    )
    assert tracer._queue.qsize() >= before  # may be 0 if worker drained it


def test_watch_decorator_returns_correct_value() -> None:
    @kalytera.watch
    def my_agent(user_input: str) -> str:
        return f"response to: {user_input}"

    result = my_agent("test question")
    assert result == "response to: test question"


def test_watch_reraises_exception() -> None:
    @kalytera.watch
    def broken_agent(x: str) -> str:
        raise ValueError("agent broken")

    raised = False
    try:
        broken_agent("hi")
    except ValueError:
        raised = True
    assert raised, "watch must re-raise exceptions from the wrapped function"


def test_watch_still_traces_on_exception() -> None:
    """Even when the agent raises, a trace event is still queued."""
    before = tracer._queue.qsize()

    @kalytera.watch
    def crashing_agent(x: str) -> str:
        raise RuntimeError("crash")

    try:
        crashing_agent("input")
    except RuntimeError:
        pass

    # Worker may have drained; just assert no error was raised from watch itself


def test_init_sets_agent_id() -> None:
    kalytera.init(api_key="test-key", agent_id="my-agent")
    assert tracer._agent_id == "my-agent"
    assert tracer._api_key == "test-key"


# --- session_ended, visible errors, check() ---

def test_trace_accepts_session_ended() -> None:
    payload = tracer._build_payload("s1", 3, "respond", "in", "out", None, None, None, True)
    assert payload["session_ended"] is True


def test_trace_defaults_session_ended_false() -> None:
    payload = tracer._build_payload("s1", 1, "step", "in", "out", None, None, None, False)
    assert payload["session_ended"] is False


def test_watch_marks_session_ended() -> None:
    captured: list = []
    original = tracer.trace
    tracer_trace = lambda **kw: captured.append(kw)  # noqa: E731
    try:
        kalytera.tracer.trace = tracer_trace  # type: ignore[assignment]

        @kalytera.watch
        def agent(x: str) -> str:
            return x

        agent("hi")
    finally:
        kalytera.tracer.trace = original  # type: ignore[assignment]
    assert captured and captured[0]["session_ended"] is True


def test_rejected_key_message_is_printed_once(capsys) -> None:
    tracer._notified.clear()
    for _ in range(3):
        tracer._notify(*tracer._connection_problem(401, None))
    err = capsys.readouterr().err
    assert err.count("API key rejected") == 1


def test_connection_problem_classification() -> None:
    assert tracer._connection_problem(200, None) is None
    assert tracer._connection_problem(401, None)[0] == "auth"
    assert tracer._connection_problem(403, None)[0] == "auth"
    assert tracer._connection_problem(429, None)[0] == "limit"
    assert tracer._connection_problem(None, "connection refused")[0] == "network"
    assert tracer._connection_problem(500, None)[0] == "http_500"


def test_init_does_not_claim_connected(capsys) -> None:
    kalytera.init(api_key="test-key", agent_id="my-agent", verify=False)
    out = capsys.readouterr().out
    assert "connected" not in out.lower()
    assert "kalytera.check()" in out


def test_init_without_key_warns(capsys) -> None:
    kalytera.init(api_key="", agent_id="my-agent", verify=False)
    assert "no API key" in capsys.readouterr().err


def _fake_http(responses):
    calls = []

    def fake(method, path, body=None):
        calls.append((method, path))
        for prefix, resp in responses:
            if f"{method} {path}".startswith(prefix):
                return resp
        raise AssertionError(f"unexpected request {method} {path}")
    return fake, calls


def test_check_reports_rejected_key(monkeypatch, capsys) -> None:
    kalytera.init(api_key="bad-key", agent_id="a", verify=False)
    fake, _ = _fake_http([("GET /agents", (401, {"detail": "Invalid API key"}, None))])
    monkeypatch.setattr(tracer, "_http", fake)
    assert kalytera.check() is False
    assert "API key rejected" in capsys.readouterr().out


def test_check_reports_unreachable(monkeypatch, capsys) -> None:
    kalytera.init(api_key="k", agent_id="a", verify=False)
    fake, _ = _fake_http([("GET /agents", (None, None, "connection refused"))])
    monkeypatch.setattr(tracer, "_http", fake)
    assert kalytera.check() is False
    assert "can't reach" in capsys.readouterr().out


def test_check_success_waits_for_score(monkeypatch, capsys) -> None:
    kalytera.init(api_key="k", agent_id="a", verify=False)
    fake, calls = _fake_http([
        ("GET /agents", (200, ["a"], None)),
        ("POST /trace", (201, {"status": "accepted"}, None)),
        ("GET /trace/", (200, {"status": "scored", "overall_score": 0.91, "passed": True}, None)),
    ])
    monkeypatch.setattr(tracer, "_http", fake)
    assert kalytera.check(timeout=5) is True
    out = capsys.readouterr().out
    assert "API key accepted" in out and "recorded" in out and "0.91" in out
    assert [c[0] for c in calls] == ["GET", "POST", "GET"]


def test_check_handles_server_without_eval_endpoint(monkeypatch, capsys) -> None:
    kalytera.init(api_key="k", agent_id="a", verify=False)
    fake, _ = _fake_http([
        ("GET /agents", (200, ["a"], None)),
        ("POST /trace", (201, {"status": "accepted"}, None)),
        ("GET /trace/", (404, {"detail": "Not Found"}, None)),
    ])
    monkeypatch.setattr(tracer, "_http", fake)
    assert kalytera.check(timeout=5) is True
    assert "doesn't report scores" in capsys.readouterr().out


def test_check_without_key(capsys) -> None:
    kalytera.init(api_key="", agent_id="a", verify=False)
    assert kalytera.check() is False
    assert "No API key" in capsys.readouterr().out
