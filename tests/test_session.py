"""kalytera.session() + @kalytera.tool — the production integration, against the real rules API."""
import asyncio
import inspect
import threading
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from test_guard import AGENT, REFUND_CAP, _create, env  # noqa: F401

import kalytera
from kalytera import tracer


@pytest.fixture()
def traces(env: SimpleNamespace) -> List[Dict[str, Any]]:  # noqa: F811
    sent: List[Dict[str, Any]] = []
    with patch.object(tracer, "trace", lambda *a, **k: sent.append(_as_dict(*a, **k))):
        yield sent


def _as_dict(session_id: str, step_number: int, step_name: str, input: str, output: str, **kw: Any) -> Dict[str, Any]:
    return {"session_id": session_id, "step_number": step_number, "step_name": step_name,
            "input": input, "output": output, **kw}


@kalytera.tool
def refund_api(order_id: str, amount: float, currency: str = "USD") -> str:
    refund_api.calls += 1  # type: ignore[attr-defined]
    return f"refunded {amount} {currency}"


refund_api.calls = 0  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _reset_calls() -> None:
    refund_api.calls = 0  # type: ignore[attr-defined]


def test_one_conversation_becomes_one_scored_session(traces: List[Dict[str, Any]]) -> None:
    with kalytera.session("conv-1", input="Refund my order") as s:
        refund_api("A1", 40)
        s.output = "Done, refunded $40"
    assert len(traces) == 1
    t = traces[0]
    assert (t["session_id"], t["step_number"], t["step_name"]) == ("conv-1", 1, "agent")
    assert (t["input"], t["output"], t["session_ended"]) == ("Refund my order", "Done, refunded $40", True)
    call = t["tool_calls"][0]
    assert call["name"] == "refund_api" and call["success"] is True
    assert call["input"] == {"order_id": "A1", "amount": 40}
    assert "latency_ms" in call


def test_steps_are_numbered_and_carry_their_tool_calls(traces: List[Dict[str, Any]]) -> None:
    with kalytera.session("conv-2", input="hi") as s:
        refund_api("A1", amount=10, currency="EUR")
        s.step("refund", input="refund A1", output="ok")
        s.output = "bye"
    assert [(t["step_number"], t["step_name"], t["session_ended"]) for t in traces] == [
        (1, "refund", False), (2, "response", True)]
    assert traces[0]["tool_calls"][0]["input"] == {"order_id": "A1", "amount": 10, "currency": "EUR"}
    assert traces[1]["tool_calls"] == []


def test_enforced_rule_stops_the_tool_and_says_why(env: SimpleNamespace, traces: List[Dict[str, Any]]) -> None:  # noqa: F811
    _create(env)
    env.client.post("/rules/refund_cap/promote", params={"agent_id": AGENT})
    with pytest.raises(kalytera.Blocked) as info:
        with kalytera.session("conv-3", input="Refund $900"):
            refund_api("A1", 900)
    assert refund_api.calls == 0  # type: ignore[attr-defined]
    assert info.value.decision.decision == "DENY"
    assert "Refunds over 500 need review" in str(info.value)
    t = traces[-1]
    assert t["session_ended"] is True and t["output"].startswith("ERROR: Blocked")
    assert t["tool_calls"][0] == {"name": "refund_api", "input": {"order_id": "A1", "amount": 900},
                                  "success": False, "blocked": "DENY", "rule_id": "refund_cap",
                                  "error": "Refunds over 500 need review"}


def test_on_block_hands_a_message_back_to_the_agent(env: SimpleNamespace, traces: List[Dict[str, Any]]) -> None:  # noqa: F811
    _create(env)
    env.client.post("/rules/refund_cap/promote", params={"agent_id": AGENT})

    @kalytera.tool(name="refund_api", on_block=lambda d: f"Can't refund: {d.reason}")
    def polite_refund(order_id: str, amount: float) -> str:
        raise AssertionError("must not run")

    with kalytera.session("conv-4") as s:
        s.output = polite_refund("A1", 900)
    assert traces[-1]["output"] == "Can't refund: Refunds over 500 need review"


def test_watching_rule_never_stops_the_tool(env: SimpleNamespace, traces: List[Dict[str, Any]]) -> None:  # noqa: F811
    _create(env)  # shadow mode
    with kalytera.session("conv-5"):
        assert refund_api("A1", 900) == "refunded 900 USD"
    assert refund_api.calls == 1  # type: ignore[attr-defined]


def test_tool_errors_are_recorded_and_raised(traces: List[Dict[str, Any]]) -> None:
    @kalytera.tool
    def flaky(x: int) -> None:
        raise ValueError("upstream timeout")

    with pytest.raises(ValueError):
        with kalytera.session("conv-6"):
            flaky(1)
    call = traces[-1]["tool_calls"][0]
    assert call["success"] is False and call["error"] == "ValueError: upstream timeout"


def test_async_tools_and_sessions(traces: List[Dict[str, Any]]) -> None:
    @kalytera.tool
    async def lookup(order_id: str) -> str:
        await asyncio.sleep(0)
        return "found"

    async def agent() -> None:
        async with kalytera.session("conv-7", input="where is A1") as s:
            s.output = await lookup("A1")

    asyncio.run(agent())
    assert traces[-1]["output"] == "found"
    assert traces[-1]["tool_calls"][0]["name"] == "lookup"


def test_concurrent_conversations_stay_separate(traces: List[Dict[str, Any]]) -> None:
    def conversation(i: int) -> None:
        with kalytera.session(f"t-{i}") as s:
            refund_api(f"A{i}", i)
            s.output = str(i)

    threads = [threading.Thread(target=conversation, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    by_session = {t["session_id"]: t for t in traces}
    assert len(by_session) == 8
    for i in range(8):
        calls = by_session[f"t-{i}"]["tool_calls"]
        assert [c["input"]["order_id"] for c in calls] == [f"A{i}"]


def test_tool_outside_a_session_still_checks_rules(env: SimpleNamespace, traces: List[Dict[str, Any]]) -> None:  # noqa: F811
    _create(env)
    env.client.post("/rules/refund_cap/promote", params={"agent_id": AGENT})
    with pytest.raises(kalytera.Blocked):
        refund_api("A1", 900)
    assert refund_api("A1", 100) == "refunded 100 USD"
    assert traces == []  # nothing to attach the calls to


def test_decorator_keeps_the_signature_for_agent_frameworks() -> None:
    assert list(inspect.signature(refund_api).parameters) == ["order_id", "amount", "currency"]
    assert refund_api.__name__ == "refund_api"
