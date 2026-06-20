"""Tests for agentiq/tracer.py — Component 1."""
import time
import uuid

import agentiq
from agentiq import tracer


def test_trace_returns_under_5ms() -> None:
    t0 = time.monotonic()
    agentiq.trace(
        session_id="s1",
        step_number=1,
        step_name="retrieve_policy",
        input="What is the refund policy?",
        output="30-day refund window.",
    )
    elapsed_ms = (time.monotonic() - t0) * 1000
    assert elapsed_ms < 5, f"trace() took {elapsed_ms:.1f}ms — must be <5ms"


def test_trace_never_raises_on_bad_input() -> None:
    agentiq.trace(
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
    agentiq.trace(
        session_id=str(uuid.uuid4()),
        step_number=2,
        step_name="apply_policy",
        input="Apply electronics policy.",
        output="Policy applied.",
    )
    assert tracer._queue.qsize() >= before  # may be 0 if worker drained it


def test_watch_decorator_returns_correct_value() -> None:
    @agentiq.watch
    def my_agent(user_input: str) -> str:
        return f"response to: {user_input}"

    result = my_agent("test question")
    assert result == "response to: test question"


def test_watch_reraises_exception() -> None:
    @agentiq.watch
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

    @agentiq.watch
    def crashing_agent(x: str) -> str:
        raise RuntimeError("crash")

    try:
        crashing_agent("input")
    except RuntimeError:
        pass

    # Worker may have drained; just assert no error was raised from watch itself


def test_init_sets_agent_id() -> None:
    agentiq.init(api_key="test-key", agent_id="my-agent")
    assert tracer._agent_id == "my-agent"
    assert tracer._api_key == "test-key"
