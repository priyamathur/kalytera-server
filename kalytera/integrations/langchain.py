"""
LangChain / LangGraph (pip install langchain-core, langgraph).

- Block: every LangChain tool runs through BaseTool.run / arun, whether it's called
  by LangGraph's ToolNode, create_agent, create_react_agent or directly. A stopped
  call doesn't run; the model gets a ToolMessage with the rule's reason.
- See: each top-level graph run (invoke / ainvoke / stream / astream) is one
  Kalytera session, named after the graph (create_agent(name=...)). Subgraphs and
  sub-agents stay in that session. Sessions in one thread share its thread_id prefix.
"""
import functools
import time
from typing import Any, Dict, Optional

from langchain_core.tools import BaseTool

from ..session import Session, block_message, check_call, current_session, record_call
from . import agent_id_for, new_session_id

DEFAULT_GRAPH_NAME = "LangGraph"


def _args(tool_input: Any) -> Dict[str, Any]:
    if isinstance(tool_input, dict):
        args = tool_input.get("args") if tool_input.get("type") == "tool_call" else tool_input
        return dict(args) if isinstance(args, dict) else {"input": args}
    return {"input": tool_input}


def _blocked(d: Any, tool: BaseTool, tool_call_id: Optional[str]) -> Any:
    msg = block_message(d)
    if tool_call_id is None:
        return msg
    from langchain_core.messages import ToolMessage

    return ToolMessage(content=msg, tool_call_id=tool_call_id, name=tool.name, status="error")


def _install_tools() -> None:
    orig_run, orig_arun = BaseTool.run, BaseTool.arun

    @functools.wraps(orig_run)
    def run(self: BaseTool, tool_input: Any, *args: Any, **kwargs: Any) -> Any:
        call_args = _args(tool_input)
        d = check_call(self.name, call_args, outer=True)
        if d is not None:
            return _blocked(d, self, kwargs.get("tool_call_id"))
        t0, error = time.monotonic(), None
        try:
            return orig_run(self, tool_input, *args, **kwargs)
        except BaseException as exc:
            error = exc
            raise
        finally:
            record_call(self.name, call_args, t0, error, outer=True)

    @functools.wraps(orig_arun)
    async def arun(self: BaseTool, tool_input: Any, *args: Any, **kwargs: Any) -> Any:
        call_args = _args(tool_input)
        d = check_call(self.name, call_args, outer=True)
        if d is not None:
            return _blocked(d, self, kwargs.get("tool_call_id"))
        t0, error = time.monotonic(), None
        try:
            return await orig_arun(self, tool_input, *args, **kwargs)
        except BaseException as exc:
            error = exc
            raise
        finally:
            record_call(self.name, call_args, t0, error, outer=True)

    BaseTool.run = run  # type: ignore[method-assign]
    BaseTool.arun = arun  # type: ignore[method-assign]


# ── Graph runs → sessions ────────────────────────────────────────────────────
def _text(message: Any) -> str:
    content = getattr(message, "content", message.get("content") if isinstance(message, dict) else message)
    if isinstance(content, list):
        return " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return "" if content is None else str(content)


def _role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role") or message.get("type") or "")
    if isinstance(message, (tuple, list)) and message:
        return str(message[0])
    return str(getattr(message, "type", ""))


def _messages(value: Any) -> list:
    if isinstance(value, dict) and isinstance(value.get("messages"), list):
        return value["messages"]
    return []


def _input_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    for m in reversed(_messages(value)):
        if _role(m) in ("human", "user"):
            return m[1] if isinstance(m, (tuple, list)) else _text(m)
    return ""


class _LastReply:
    """Remembers the latest complete AI message seen in a run's output chunks."""

    def __init__(self) -> None:
        self.text = ""

    def see(self, chunk: Any) -> None:
        if isinstance(chunk, tuple):  # (mode, data), (namespace, mode, data) or (message, metadata)
            for part in chunk:
                self.see(part)
            return
        if isinstance(chunk, dict):
            for m in _messages(chunk):
                self._message(m)
            for value in chunk.values():  # updates mode: {node: {"messages": [...]}}
                if isinstance(value, dict):
                    for m in _messages(value):
                        self._message(m)
            return
        self._message(chunk)

    def _message(self, m: Any) -> None:
        if _role(m) == "ai" and type(m).__name__ != "AIMessageChunk" and _text(m):
            self.text = _text(m)


def _session_for(graph: Any, input: Any, config: Any) -> Session:
    name = getattr(graph, "name", None)
    thread = ((config or {}).get("configurable") or {}).get("thread_id") if isinstance(config, dict) else None
    return Session(new_session_id(str(thread) if thread else None), _input_text(input),
                   agent_id_for(None if name in (None, DEFAULT_GRAPH_NAME) else name))


def _install_graphs() -> bool:
    try:
        from langgraph.pregel import Pregel
    except ImportError:
        return False
    orig_stream, orig_astream = Pregel.stream, Pregel.astream

    @functools.wraps(orig_stream)
    def stream(self: Any, input: Any, config: Any = None, *args: Any, **kwargs: Any) -> Any:
        if current_session() is not None:  # subgraph or sub-agent: part of the outer run
            yield from orig_stream(self, input, config, *args, **kwargs)
            return
        reply = _LastReply()
        with _session_for(self, input, config) as s:
            for chunk in orig_stream(self, input, config, *args, **kwargs):
                reply.see(chunk)
                yield chunk
            s.output = reply.text

    @functools.wraps(orig_astream)
    async def astream(self: Any, input: Any, config: Any = None, *args: Any, **kwargs: Any) -> Any:
        if current_session() is not None:
            async for chunk in orig_astream(self, input, config, *args, **kwargs):
                yield chunk
            return
        reply = _LastReply()
        with _session_for(self, input, config) as s:
            async for chunk in orig_astream(self, input, config, *args, **kwargs):
                reply.see(chunk)
                yield chunk
            s.output = reply.text

    Pregel.stream = stream  # type: ignore[method-assign]
    Pregel.astream = astream  # type: ignore[method-assign]
    return True


_done = False


def install() -> bool:
    global _done
    if not _done:
        _install_tools()
        _install_graphs()
        _done = True
    return True
