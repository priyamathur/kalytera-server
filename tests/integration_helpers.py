"""Shared setup for the framework integration tests: real guard() and rule evaluation,
rules served from the local cache instead of the API, and traces captured instead of sent."""
import importlib
import time
from types import SimpleNamespace
from typing import Any, Dict, Generator, List
from unittest.mock import patch

import pytest

from kalytera import tracer
from kalytera.rules import parse_rule

guard_mod = importlib.import_module("kalytera.guard")  # `from kalytera import guard` is the function
RULE_REASON = "Refunds over 500 need review"


def refund_rules() -> List[Any]:
    return [parse_rule({"id": "refund_cap", "mode": "enforce", "action": "DENY", "reason": RULE_REASON,
                        "match": {"tool": "refund_api",
                                  "args": [{"field": "amount", "op": ">", "value": 500}]}})]


def scoped(name: str) -> str:
    return tracer.key_scoped(name)


class _Rules(dict):
    """Setting rules for an agent puts them in guard()'s cache, as if fetched from the API."""

    def __setitem__(self, agent_id: str, rules: List[Any]) -> None:
        super().__setitem__(agent_id, rules)
        guard_mod._cache[agent_id] = (rules, time.monotonic(), "")


@pytest.fixture()
def setup_kalytera() -> Generator[SimpleNamespace, None, None]:
    sent: List[Dict[str, Any]] = []

    def capture(session_id: str, step_number: int, step_name: str, input: str, output: str,
                tool_calls: Any = None, metadata: Any = None, agent_id: Any = None,
                session_ended: bool = False) -> None:
        sent.append({"session_id": session_id, "step_number": step_number, "step_name": step_name,
                     "input": input, "output": output, "tool_calls": tool_calls or [],
                     "agent_id": agent_id or tracer._agent_id, "session_ended": session_ended})

    def no_rules(agent_id: str, timeout: float = 0) -> None:
        guard_mod._cache.setdefault(agent_id, ([], time.monotonic(), ""))

    saved = (tracer._api_key, tracer._agent_id, tracer._agent_id_explicit)
    tracer._api_key, tracer._agent_id, tracer._agent_id_explicit = "kly_live_test", "default-agent", False
    guard_mod._cache.clear()
    with patch.object(tracer, "trace", capture), patch.object(guard_mod, "_refresh", no_rules), \
            patch.object(guard_mod, "_emit", lambda *a, **k: None):
        yield SimpleNamespace(traces=sent, rules=_Rules())
    guard_mod._cache.clear()
    tracer._api_key, tracer._agent_id, tracer._agent_id_explicit = saved
