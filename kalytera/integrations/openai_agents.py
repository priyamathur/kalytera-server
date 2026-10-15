"""
OpenAI Agents SDK (pip install openai-agents).

- See: each Runner.run / run_sync / run_streamed is one Kalytera session, named
  after the starting agent. Handoffs and agents-as-tools stay in that session.
- Block: a tool input guardrail (the SDK's own mechanism) is added to every
  function tool, MCP tools included. A stopped call doesn't run; the model gets
  the rule's reason as the tool result, so it explains instead of retrying.
"""
import functools
import json
import time
from typing import Any, Dict, Optional

from agents import FunctionTool
from agents.agent import AgentBase
from agents.run import AgentRunner
from agents.tool_guardrails import (
    ToolGuardrailFunctionOutput,
    ToolInputGuardrail,
    ToolInputGuardrailData,
    ToolOutputGuardrail,
    ToolOutputGuardrailData,
)

from ..session import Session, _current, block_message, check_call, current_session, record_call
from . import agent_id_for, new_session_id

_started: Dict[str, float] = {}  # tool_call_id -> start time


def _args(raw: Optional[str]) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {"input": parsed}
    except ValueError:
        return {"input": raw}


def _before(data: ToolInputGuardrailData) -> ToolGuardrailFunctionOutput:
    ctx = data.context
    d = check_call(ctx.tool_name, _args(ctx.tool_arguments), outer=True)
    if d is not None:
        return ToolGuardrailFunctionOutput.reject_content(block_message(d))
    _started[ctx.tool_call_id] = time.monotonic()
    return ToolGuardrailFunctionOutput.allow()


def _after(data: ToolOutputGuardrailData) -> ToolGuardrailFunctionOutput:
    ctx = data.context
    t0 = _started.pop(ctx.tool_call_id, time.monotonic())
    record_call(ctx.tool_name, _args(ctx.tool_arguments), t0, None, outer=True)
    return ToolGuardrailFunctionOutput.allow()


BEFORE = ToolInputGuardrail(guardrail_function=_before, name="kalytera")
AFTER = ToolOutputGuardrail(guardrail_function=_after, name="kalytera")


def _input_text(value: Any) -> str:
    """The user's message: a string, or the last user item of an input list."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for item in reversed(value):
            if isinstance(item, dict) and item.get("role") == "user":
                content = item.get("content")
                if isinstance(content, list):
                    return " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
                return str(content or "")
    return ""


def _conversation(kwargs: Dict[str, Any]) -> Optional[str]:
    run_config = kwargs.get("run_config")
    session = kwargs.get("session")
    return (kwargs.get("conversation_id") or getattr(session, "session_id", None)
            or getattr(run_config, "group_id", None))


def _new_session(agent: Any, input: Any, kwargs: Dict[str, Any]) -> Session:
    return Session(new_session_id(_conversation(kwargs)), _input_text(input),
                   agent_id_for(getattr(agent, "name", None)))


def install() -> bool:
    if getattr(AgentRunner, "_kalytera", False):
        return True
    orig_tools = AgentBase.get_all_tools
    orig_run = AgentRunner.run
    orig_streamed = AgentRunner.run_streamed

    @functools.wraps(orig_tools)
    async def get_all_tools(self: Any, run_context: Any) -> Any:
        tools = await orig_tools(self, run_context)
        for t in tools:
            if isinstance(t, FunctionTool):
                if BEFORE not in (t.tool_input_guardrails or []):
                    t.tool_input_guardrails = [*(t.tool_input_guardrails or []), BEFORE]
                if AFTER not in (t.tool_output_guardrails or []):
                    t.tool_output_guardrails = [*(t.tool_output_guardrails or []), AFTER]
        return tools

    @functools.wraps(orig_run)
    async def run(self: Any, starting_agent: Any, input: Any, **kwargs: Any) -> Any:
        if current_session() is not None:  # a nested run (agent as a tool) stays in its session
            return await orig_run(self, starting_agent, input, **kwargs)
        with _new_session(starting_agent, input, kwargs) as s:
            result = await orig_run(self, starting_agent, input, **kwargs)
            s.output = result.final_output
            return result

    @functools.wraps(orig_streamed)
    def run_streamed(self: Any, starting_agent: Any, input: Any, **kwargs: Any) -> Any:
        if current_session() is not None:
            return orig_streamed(self, starting_agent, input, **kwargs)
        s = _new_session(starting_agent, input, kwargs)
        s.__enter__()  # the run task created below copies this context
        try:
            result = orig_streamed(self, starting_agent, input, **kwargs)
        except BaseException as exc:
            s.__exit__(type(exc), exc, None)
            raise
        finally:
            if s._token is not None:  # don't leave the session set in the caller's context
                _current.reset(s._token)
                s._token = None
        events = result.stream_events

        @functools.wraps(events)
        async def stream_events(*a: Any, **k: Any) -> Any:
            try:
                async for event in events(*a, **k):
                    yield event
            except BaseException as exc:
                s.__exit__(type(exc), exc, None)
                raise
            s.output = result.final_output
            s.__exit__(None, None, None)

        result.stream_events = stream_events
        return result

    AgentBase.get_all_tools = get_all_tools  # type: ignore[method-assign]
    AgentRunner.run = run  # type: ignore[method-assign]
    AgentRunner.run_streamed = run_streamed  # type: ignore[method-assign]
    AgentRunner._kalytera = True  # type: ignore[attr-defined]
    return True
