"""kalytera.init() + the OpenAI Agents SDK: real Runner, scripted model, no network."""
import asyncio
import json
from typing import Any, Dict, List

import pytest

agents = pytest.importorskip("agents")

from agents import Agent, Runner, function_tool  # noqa: E402
from agents.items import ModelResponse  # noqa: E402
from agents.models.interface import Model  # noqa: E402
from agents.usage import Usage  # noqa: E402
from openai.types.responses import (  # noqa: E402
    Response,
    ResponseCompletedEvent,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

from kalytera.integrations import openai_agents  # noqa: E402
from integration_helpers import RULE_REASON, refund_rules, scoped, setup_kalytera  # noqa: E402,F401


def _call(name: str, args: Dict[str, Any], call_id: str) -> ResponseFunctionToolCall:
    return ResponseFunctionToolCall(type="function_call", name=name, arguments=json.dumps(args),
                                    call_id=call_id, id=f"fc_{call_id}", status="completed")


def _say(text: str) -> ResponseOutputMessage:
    return ResponseOutputMessage(type="message", id="msg_1", role="assistant", status="completed",
                                 content=[ResponseOutputText(type="output_text", text=text, annotations=[])])


class Scripted(Model):
    """Turn 1: call refund_api with the given amount. Turn 2: reply with what the tool said."""

    def __init__(self, amount: float) -> None:
        self.amount = amount
        self.seen_tool_output = ""

    def _next(self, input: Any) -> List[Any]:
        outputs = [i for i in (input if isinstance(input, list) else []) if
                   isinstance(i, dict) and i.get("type") == "function_call_output"]
        if not outputs:
            return [_call("refund_api", {"order_id": "A1", "amount": self.amount}, "c1")]
        self.seen_tool_output = str(outputs[-1].get("output"))
        return [_say(f"Result: {self.seen_tool_output}")]

    async def get_response(self, system_instructions: Any, input: Any, *a: Any, **k: Any) -> ModelResponse:
        return ModelResponse(output=self._next(input), usage=Usage(), response_id=None)

    async def stream_response(self, system_instructions: Any, input: Any, *a: Any, **k: Any) -> Any:
        response = Response.model_construct(id="r1", object="response", created_at=0, model="scripted",
                                            output=self._next(input), parallel_tool_calls=False,
                                            tool_choice="auto", tools=[], status="completed")
        yield ResponseCompletedEvent(type="response.completed", response=response, sequence_number=0)


ran: List[int] = []


@function_tool
def refund_api(order_id: str, amount: int) -> str:
    """Issue a refund."""
    ran.append(amount)
    return f"refunded {amount}"


@pytest.fixture(autouse=True)
def _reset() -> None:
    ran.clear()
    assert openai_agents.install()


def _agent(amount: float, name: str = "Refund bot") -> Agent:
    return Agent(name=name, instructions="Refund things.", tools=[refund_api], model=Scripted(amount))


def test_a_run_is_one_session_named_after_the_agent(setup_kalytera: Any) -> None:
    result = Runner.run_sync(_agent(40), "Refund my $40 order A1")
    assert ran == [40]
    sent = setup_kalytera.traces
    assert len(sent) == 1
    t = sent[0]
    assert t["agent_id"] == scoped("refund-bot")
    assert t["input"] == "Refund my $40 order A1"
    assert t["output"] == result.final_output == "Result: refunded 40"
    assert t["session_ended"] is True
    call = t["tool_calls"][0]
    assert (call["name"], call["input"], call["success"]) == ("refund_api", {"order_id": "A1", "amount": 40}, True)


def test_an_enforced_rule_stops_the_tool_and_the_model_hears_why(setup_kalytera: Any) -> None:
    setup_kalytera.rules[scoped("refund-bot")] = refund_rules()
    model = Scripted(900)
    agent = Agent(name="Refund bot", instructions="Refund things.", tools=[refund_api], model=model)
    result = Runner.run_sync(agent, "Refund my $900 order")
    assert ran == []  # the tool never ran
    assert RULE_REASON in model.seen_tool_output and "Do not retry" in model.seen_tool_output
    assert RULE_REASON in result.final_output
    call = setup_kalytera.traces[-1]["tool_calls"][0]
    assert call["blocked"] == "DENY" and call["success"] is False


def test_rules_are_per_agent(setup_kalytera: Any) -> None:
    setup_kalytera.rules[scoped("refund-bot")] = refund_rules()
    Runner.run_sync(_agent(900, name="Billing bot"), "Refund my $900 order")
    assert ran == [900]  # Billing bot has no rules
    assert setup_kalytera.traces[-1]["agent_id"] == scoped("billing-bot")


def test_async_and_streamed_runs(setup_kalytera: Any) -> None:
    async def go() -> None:
        r = await Runner.run(_agent(10), "Refund $10")
        assert r.final_output == "Result: refunded 10"
        streamed = Runner.run_streamed(_agent(20), "Refund $20")
        async for _ in streamed.stream_events():
            pass

    asyncio.run(go())
    assert ran == [10, 20]
    outs = [(t["input"], t["output"], len(t["tool_calls"])) for t in setup_kalytera.traces]
    assert outs == [("Refund $10", "Result: refunded 10", 1), ("Refund $20", "Result: refunded 20", 1)]


def test_streamed_run_blocks_too(setup_kalytera: Any) -> None:
    setup_kalytera.rules[scoped("refund-bot")] = refund_rules()

    async def go() -> None:
        streamed = Runner.run_streamed(_agent(900), "Refund $900")
        async for _ in streamed.stream_events():
            pass

    asyncio.run(go())
    assert ran == []
    assert setup_kalytera.traces[-1]["tool_calls"][0]["blocked"] == "DENY"


def test_explicit_agent_id_wins(setup_kalytera: Any) -> None:
    import kalytera.tracer as tracer

    tracer._agent_id, tracer._agent_id_explicit = "support-system", True
    try:
        Runner.run_sync(_agent(5), "Refund $5")
    finally:
        tracer._agent_id_explicit = False
    assert setup_kalytera.traces[-1]["agent_id"] == "support-system"


def test_a_tool_that_also_has_kalytera_tool_is_checked_and_recorded_once(setup_kalytera: Any) -> None:
    import importlib

    import kalytera

    guard_mod = importlib.import_module("kalytera.guard")
    calls: List[str] = []
    real = guard_mod.guard

    def counting(tool: str, *a: Any, **k: Any) -> Any:
        calls.append(tool)
        return real(tool, *a, **k)

    @function_tool
    @kalytera.tool
    def refund_api(order_id: str, amount: float) -> str:  # float: the SDK passes 40.0 for "40"
        """Issue a refund."""
        ran.append(amount)
        return f"refunded {amount}"

    agent = Agent(name="Refund bot", instructions="x", tools=[refund_api], model=Scripted(40))
    with __import__("unittest.mock").mock.patch.object(guard_mod, "guard", counting):
        Runner.run_sync(agent, "Refund $40")
    assert ran == [40] and calls == ["refund_api"]
    assert len(setup_kalytera.traces[-1]["tool_calls"]) == 1
