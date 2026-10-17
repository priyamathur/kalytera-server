"""kalytera.init() + LangChain / LangGraph: real graphs and ToolNode, scripted chat model, no network."""
import asyncio
from typing import Any, List, Optional

import pytest

pytest.importorskip("langgraph")

from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langgraph.prebuilt import create_react_agent  # noqa: E402

from kalytera.integrations import langchain as lc  # noqa: E402
from integration_helpers import RULE_REASON, refund_rules, scoped, setup_kalytera  # noqa: E402,F401


class Scripted(BaseChatModel):
    """Turn 1: call refund_api with `amount`. Turn 2: repeat what the tool said."""

    amount: int = 40
    seen_tool_output: str = ""

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "Scripted":
        return self

    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None,
                  run_manager: Any = None, **kwargs: Any) -> ChatResult:
        last = messages[-1]
        if isinstance(last, ToolMessage):
            self.seen_tool_output = str(last.content)
            msg = AIMessage(content=f"Result: {last.content}")
        else:
            msg = AIMessage(content="", tool_calls=[{"name": "refund_api", "id": "c1",
                                                     "args": {"order_id": "A1", "amount": self.amount}}])
        return ChatResult(generations=[ChatGeneration(message=msg)])


ran: List[int] = []


@tool
def refund_api(order_id: str, amount: int) -> str:
    """Issue a refund."""
    ran.append(amount)
    return f"refunded {amount}"


@pytest.fixture(autouse=True)
def _reset() -> None:
    ran.clear()
    assert lc.install()


def _agent(amount: int, name: Optional[str] = "Refund bot") -> Any:
    model = Scripted(amount=amount)
    return model, create_react_agent(model, [refund_api], name=name)


def test_a_graph_run_is_one_session_named_after_the_graph(setup_kalytera: Any) -> None:
    _, agent = _agent(40)
    out = agent.invoke({"messages": [("user", "Refund my $40 order A1")]},
                       {"configurable": {"thread_id": "conv-7"}})
    assert ran == [40]
    assert out["messages"][-1].content == "Result: refunded 40"
    assert len(setup_kalytera.traces) == 1
    t = setup_kalytera.traces[0]
    assert t["agent_id"] == scoped("refund-bot")
    assert t["session_id"].startswith("conv-7-")
    assert (t["input"], t["output"], t["session_ended"]) == ("Refund my $40 order A1", "Result: refunded 40", True)
    call = t["tool_calls"][0]
    assert (call["name"], call["input"], call["success"]) == ("refund_api", {"order_id": "A1", "amount": 40}, True)
    assert call["output"] == "refunded 40"


def test_an_enforced_rule_stops_the_tool_and_the_model_hears_why(setup_kalytera: Any) -> None:
    setup_kalytera.rules[scoped("refund-bot")] = refund_rules()
    model, agent = _agent(900)
    out = agent.invoke({"messages": [("user", "Refund my $900 order")]})
    assert ran == []
    assert RULE_REASON in model.seen_tool_output and "Do not retry" in model.seen_tool_output
    tool_msg = [m for m in out["messages"] if isinstance(m, ToolMessage)][0]
    assert tool_msg.status == "error" and tool_msg.tool_call_id == "c1"
    call = setup_kalytera.traces[-1]["tool_calls"][0]
    assert call["blocked"] == "DENY" and call["success"] is False


def test_streaming_and_async(setup_kalytera: Any) -> None:
    _, agent = _agent(10)
    for _ in agent.stream({"messages": [("user", "Refund $10")]}, stream_mode="updates"):
        pass
    _, agent2 = _agent(20)

    async def go() -> None:
        await agent2.ainvoke({"messages": [("user", "Refund $20")]})
        async for _ in agent2.astream({"messages": [("user", "Refund $30")]}, stream_mode="values"):
            pass

    asyncio.run(go())
    outs = [(t["input"], t["output"]) for t in setup_kalytera.traces]
    assert outs == [("Refund $10", "Result: refunded 10"), ("Refund $20", "Result: refunded 20"),
                    ("Refund $30", "Result: refunded 20")]
    assert all(len(t["tool_calls"]) == 1 for t in setup_kalytera.traces)


def test_a_sub_agent_stays_in_the_parent_session(setup_kalytera: Any) -> None:
    _, inner = _agent(15, name="Refund helper")

    @tool
    def ask_refund_helper(request: str) -> str:
        """Hand a refund request to the refund helper."""
        return inner.invoke({"messages": [("user", request)]})["messages"][-1].content

    class Outer(Scripted):
        def _generate(self, messages: List[BaseMessage], stop: Any = None, run_manager: Any = None,
                      **kwargs: Any) -> ChatResult:
            if isinstance(messages[-1], ToolMessage):
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content=str(messages[-1].content)))])
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[
                {"name": "ask_refund_helper", "id": "o1", "args": {"request": "refund $15"}}]))])

    supervisor = create_react_agent(Outer(), [ask_refund_helper], name="Support desk")
    supervisor.invoke({"messages": [("user", "I want $15 back")]})
    assert len(setup_kalytera.traces) == 1  # one conversation, one session
    t = setup_kalytera.traces[0]
    assert t["agent_id"] == scoped("support-desk")
    assert [c["name"] for c in t["tool_calls"]] == ["refund_api", "ask_refund_helper"]


def test_unnamed_graph_uses_the_default_agent(setup_kalytera: Any) -> None:
    _, agent = _agent(5, name=None)
    agent.invoke({"messages": [("user", "Refund $5")]})
    assert setup_kalytera.traces[-1]["agent_id"] == scoped("agent")


def test_a_tool_called_directly_is_still_checked(setup_kalytera: Any) -> None:
    setup_kalytera.rules["default-agent"] = refund_rules()
    out = refund_api.invoke({"order_id": "A1", "amount": 900})
    assert ran == [] and RULE_REASON in out
    assert refund_api.invoke({"order_id": "A1", "amount": 100}) == "refunded 100"


def test_langchain_create_agent(setup_kalytera: Any) -> None:
    agents_mod = pytest.importorskip("langchain.agents")
    setup_kalytera.rules[scoped("refund-bot")] = refund_rules()
    model = Scripted(amount=900)
    agent = agents_mod.create_agent(model, tools=[refund_api], name="Refund bot")
    agent.invoke({"messages": [{"role": "user", "content": "Refund my $900 order"}]})
    assert ran == [] and RULE_REASON in model.seen_tool_output
    t = setup_kalytera.traces[-1]
    assert (t["agent_id"], t["input"]) == (scoped("refund-bot"), "Refund my $900 order")
    assert t["tool_calls"][0]["blocked"] == "DENY"


def test_one_line_init_reads_the_key_and_hooks_installed_frameworks(monkeypatch: Any, capsys: Any) -> None:
    import kalytera
    import kalytera.tracer as tracer

    monkeypatch.setenv("KALYTERA_API_KEY", "kly_live_from_env")
    monkeypatch.delenv("KALYTERA_AGENT_ID", raising=False)
    saved = (tracer._api_key, tracer._agent_id, tracer._agent_id_explicit)
    try:
        kalytera.init(verify=False)
        out = capsys.readouterr().out
        assert tracer._api_key == "kly_live_from_env" and tracer._agent_id_explicit is False
        assert "LangChain / LangGraph" in out and "OpenAI Agents SDK" in out
        assert "framework agents use their own names" in out
    finally:
        tracer._api_key, tracer._agent_id, tracer._agent_id_explicit = saved


def test_a_tool_that_also_has_kalytera_tool_is_checked_and_recorded_once(setup_kalytera: Any) -> None:
    import importlib
    from unittest.mock import patch

    import kalytera

    guard_mod = importlib.import_module("kalytera.guard")
    calls: List[str] = []
    real = guard_mod.guard

    def counting(tool_name: str, *a: Any, **k: Any) -> Any:
        calls.append(tool_name)
        return real(tool_name, *a, **k)

    @tool
    @kalytera.tool
    def refund_api(order_id: str, amount: int) -> str:
        """Issue a refund."""
        ran.append(amount)
        return f"refunded {amount}"

    agent = create_react_agent(Scripted(amount=40), [refund_api], name="Refund bot")
    with patch.object(guard_mod, "guard", counting):
        agent.invoke({"messages": [("user", "Refund $40")]})
    assert ran == [40] and calls == ["refund_api"]
    assert len(setup_kalytera.traces[-1]["tool_calls"]) == 1
