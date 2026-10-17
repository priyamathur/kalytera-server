"""
The two-line integration for an agent in production:

    @kalytera.tool                       # guard() before every call + record it
    def refund_api(order_id: str, amount: float) -> str: ...

    with kalytera.session(conversation_id, input=user_message) as s:
        s.output = run_agent(user_message)     # tools called in here are recorded

- session(): one conversation. Steps are numbered for you, tool calls made
  inside are attached to them, and the session is marked ended (so it gets
  scored) when the block exits, also if it raises.
- @tool: checks your rules before the tool runs. If a promoted rule says DENY
  or ESCALATE the tool does not run: kalytera.Blocked is raised, or, with
  on_block=..., its return value goes back to your agent instead (for example
  a message the LLM can relay). Works on sync and async functions; put it
  under a framework's own decorator (@function_tool, @tool) so the framework
  still sees the real signature.

Like trace(), none of this raises because of Kalytera itself: if the API is
down, tools run (guard() fails open) and traces are dropped with a warning.
"""
import asyncio
import contextvars
import functools
import inspect
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, TypeVar

from .rules import Decision

F = TypeVar("F", bound=Callable[..., Any])

_current: "contextvars.ContextVar[Optional[Session]]" = contextvars.ContextVar("kalytera_session", default=None)


class Blocked(Exception):
    """Raised by a @kalytera.tool function when a rule stops the call. Read .decision.reason."""

    def __init__(self, decision: Decision, tool: str) -> None:
        self.decision = decision
        self.tool = tool
        verb = "needs review" if decision.decision == "ESCALATE" else "blocked"
        super().__init__(f"{tool} {verb} by rule {decision.rule_id}: {decision.reason}")


class Session:
    """One conversation. Use `with kalytera.session(...) as s:`; set s.output before it ends."""

    def __init__(self, session_id: Optional[str] = None, input: Any = None,
                 agent_id: Optional[str] = None) -> None:
        self.session_id = str(session_id) if session_id else uuid.uuid4().hex
        self.input = "" if input is None else str(input)
        self.output: Any = None
        self.agent_id = agent_id
        self._step = 0
        self._pending: List[Dict[str, Any]] = []
        self._token: Optional[contextvars.Token] = None
        self._started = 0.0
        # A framework hook (outer) and @kalytera.tool (inner) can both see one call:
        # count it once. Keys are (tool, args) of calls the outer layer checked / the inner recorded.
        self._outer_checked: Dict[str, int] = {}
        self._inner_recorded: Dict[str, int] = {}

    # ── recording ────────────────────────────────────────────────────────────
    def step(self, name: str, input: Any = "", output: Any = "", ended: bool = False) -> None:
        """Record one step. Tool calls made since the last step are attached to it."""
        from . import tracer

        self._step += 1
        calls, self._pending = self._pending, []
        tracer.trace(self.session_id, self._step, name, "" if input is None else str(input),
                     "" if output is None else str(output), tool_calls=calls, agent_id=self.agent_id,
                     session_ended=ended)

    def _record_call(self, call: Dict[str, Any]) -> None:
        self._pending.append(call)

    # ── context manager (sync and async) ─────────────────────────────────────
    def __enter__(self) -> "Session":
        self._token = _current.set(self)
        self._started = time.monotonic()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        try:
            output = f"ERROR: {exc_type.__name__}: {exc}" if exc_type else self.output
            # First step gets the user's message; the last one carries the reply and ends the session.
            self.step("response" if self._step else "agent", self.input if not self._step else "",
                      output, ended=True)
        except Exception:
            pass
        finally:
            if self._token is not None:
                _current.reset(self._token)
        return False

    async def __aenter__(self) -> "Session":
        return self.__enter__()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return self.__exit__(exc_type, exc, tb)


def session(session_id: Optional[str] = None, input: Any = None, agent_id: Optional[str] = None) -> Session:
    """Start a conversation: `with kalytera.session(conversation_id, input=message) as s:`."""
    return Session(session_id, input, agent_id)


def current_session() -> Optional[Session]:
    """The session the calling code runs in, if any."""
    return _current.get()


def _key(tool_name: str, call_args: Dict[str, Any]) -> str:
    """The same call as two layers see it: 40 and 40.0 (after type conversion) match."""
    import json

    def norm(v: Any) -> Any:
        if isinstance(v, float) and v.is_integer():
            return int(v)
        if isinstance(v, dict):
            return {str(k): norm(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [norm(x) for x in v]
        return v

    return f"{tool_name}:{json.dumps(norm(call_args), sort_keys=True, default=str)}"


def _take(counts: Dict[str, int], key: str) -> bool:
    if counts.get(key, 0) <= 0:
        return False
    counts[key] -= 1
    return True


def check_call(tool_name: str, call_args: Dict[str, Any], outer: bool = False) -> Optional[Decision]:
    """
    Run guard() for a tool call in the current session. Returns the Decision if it's
    stopped, else None. outer=True is a framework hook; a @kalytera.tool inside it then
    doesn't check the same call again (repeat-count rules would see it twice).
    """
    from .guard import guard

    s = _current.get()
    if s is not None and not outer and _take(s._outer_checked, _key(tool_name, call_args)):
        return None
    d = guard(tool_name, call_args, session_id=s.session_id if s else "", agent_id=s.agent_id if s else None)
    if d.allowed:
        if s is not None and outer:
            key = _key(tool_name, call_args)
            s._outer_checked[key] = s._outer_checked.get(key, 0) + 1
        return None
    if s:
        s._record_call({"name": tool_name, "input": call_args, "success": False,
                        "blocked": d.decision, "rule_id": d.rule_id, "error": d.reason})
    return d


OUTPUT_CHARS = 2000  # what an action returned, kept so the judge can check the reply against it


def record_call(tool_name: str, call_args: Dict[str, Any], t0: float, error: Optional[BaseException],
                outer: bool = False, output: Any = None) -> None:
    """Attach a finished tool call to the current session, if there is one (once, if two layers saw it)."""
    s = _current.get()
    if s is None:
        return
    key = _key(tool_name, call_args)
    if outer and _take(s._inner_recorded, key):
        return
    if not outer:
        _take(s._outer_checked, key)  # in case the inner layer never checked (it always does today)
        s._inner_recorded[key] = s._inner_recorded.get(key, 0) + 1
    call: Dict[str, Any] = {"name": tool_name, "input": call_args, "success": error is None,
                            "latency_ms": int((time.monotonic() - t0) * 1000)}
    if error is not None:
        call["error"] = f"{type(error).__name__}: {error}"
    elif output is not None:
        output = getattr(output, "content", output)  # LangChain hands back a ToolMessage
        call["output"] = str(output)[:OUTPUT_CHARS]
    s._record_call(call)


def block_message(d: Decision) -> str:
    """What the model is told when a rule stops a tool call, so it explains instead of retrying."""
    what = "needs review by a person" if d.decision == "ESCALATE" else "was blocked"
    return (f"This tool call {what} (rule {d.rule_id}: {d.reason}). Do not retry it. "
            f"Tell the user it can't be done automatically.")


def tool(fn: Optional[F] = None, *, name: Optional[str] = None,
         on_block: Optional[Callable[[Decision], Any]] = None) -> Any:
    """
    Decorator: check guard rules before the tool runs and record the call.

        @kalytera.tool
        def refund_api(order_id, amount): ...

        @kalytera.tool(on_block=lambda d: f"I can't do that: {d.reason}")
        def refund_api(order_id, amount): ...
    """
    def wrap(func: F) -> F:
        tool_name = name or func.__name__
        sig = inspect.signature(func)

        def arguments(args: Any, kwargs: Any) -> Dict[str, Any]:
            try:
                bound = sig.bind_partial(*args, **kwargs)
                out = dict(bound.arguments)
                for p in sig.parameters.values():  # **kwargs params flatten into the dict
                    if p.kind is p.VAR_KEYWORD and p.name in out:
                        out.update(out.pop(p.name))
                out.pop("self", None)
                out.pop("cls", None)
                return out
            except TypeError:
                return dict(kwargs)

        def check(call_args: Dict[str, Any]) -> Optional[Decision]:
            return check_call(tool_name, call_args)

        def done(call_args: Dict[str, Any], t0: float, error: Optional[BaseException], result: Any) -> None:
            record_call(tool_name, call_args, t0, error, output=result)

        def blocked(d: Decision) -> Any:
            if on_block is not None:
                return on_block(d)
            raise Blocked(d, tool_name)

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                call_args = arguments(args, kwargs)
                d = check(call_args)
                if d is not None:
                    return blocked(d)
                t0, error, result = time.monotonic(), None, None
                try:
                    result = await func(*args, **kwargs)
                    return result
                except BaseException as exc:
                    error = exc
                    raise
                finally:
                    done(call_args, t0, error, result)
            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            call_args = arguments(args, kwargs)
            d = check(call_args)
            if d is not None:
                return blocked(d)
            t0, error, result = time.monotonic(), None, None
            try:
                result = func(*args, **kwargs)
                return result
            except BaseException as exc:
                error = exc
                raise
            finally:
                done(call_args, t0, error, result)
        return wrapper  # type: ignore[return-value]

    return wrap(fn) if fn is not None else wrap
