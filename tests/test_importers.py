"""Langfuse / LangSmith data → Kalytera conversations, with payloads shaped like their APIs return."""
import json
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from kalytera import importers
from kalytera.importers import (
    fetch_langfuse,
    fetch_langsmith,
    from_langfuse,
    from_langsmith,
    messages_to_turns,
    to_steps,
)


def test_openai_messages_become_turns_with_actions_and_results() -> None:
    msgs = [
        {"role": "system", "content": "You are a refund agent."},
        {"role": "user", "content": "Refund $900 for A1"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "refund_api",
                                                          "arguments": json.dumps({"order_id": "A1", "amount": 900})}}]},
        {"role": "tool", "tool_call_id": "c1", "content": json.dumps({"error": "over the auto-approval limit"})},
        {"role": "assistant", "content": "Done! Your refund was issued."},
        {"role": "user", "content": "Thanks"},
        {"role": "assistant", "content": "You're welcome."},
    ]
    turns = messages_to_turns(msgs)
    assert [t["user"] for t in turns] == ["Refund $900 for A1", "Thanks"]
    assert turns[0]["assistant"] == "Done! Your refund was issued."
    action = turns[0]["actions"][0]
    assert (action["name"], action["input"], action["success"]) == ("refund_api", {"order_id": "A1", "amount": 900}, False)
    assert "auto-approval" in action["error"]


def test_langchain_serialized_messages() -> None:
    msgs = [
        {"lc": 1, "type": "constructor", "id": ["langchain", "schema", "messages", "HumanMessage"],
         "kwargs": {"content": "Where is my order?", "type": "human"}},
        {"lc": 1, "type": "constructor", "id": ["langchain", "schema", "messages", "AIMessage"],
         "kwargs": {"content": "", "type": "ai", "tool_calls": [{"name": "lookup", "args": {"id": "A1"}, "id": "t1"}]}},
        {"lc": 1, "type": "constructor", "id": ["langchain", "schema", "messages", "ToolMessage"],
         "kwargs": {"content": "Shipped", "type": "tool", "tool_call_id": "t1"}},
        {"lc": 1, "type": "constructor", "id": ["langchain", "schema", "messages", "AIMessage"],
         "kwargs": {"content": "It shipped yesterday.", "type": "ai"}},
    ]
    [turn] = messages_to_turns(msgs)
    assert (turn["user"], turn["assistant"]) == ("Where is my order?", "It shipped yesterday.")
    assert turn["actions"][0]["name"] == "lookup" and turn["actions"][0]["output"] == "Shipped"


LANGFUSE_ROOTS = [
    {"id": "o1", "traceId": "tr1", "type": "AGENT", "isRootObservation": True, "startTime": "2026-10-01T10:00:00Z",
     "input": json.dumps([{"role": "user", "content": "Refund my $900 order"}]),
     "output": json.dumps({"role": "assistant", "content": "Your refund was issued."})},
    {"id": "o2", "traceId": "tr2", "type": "SPAN", "isRootObservation": True, "startTime": "2026-10-02T10:00:00Z",
     "input": "What are your hours?", "output": "9 to 5."},
]
LANGFUSE_TOOLS = [
    {"id": "o3", "traceId": "tr1", "type": "TOOL", "name": "refund_api", "startTime": "2026-10-01T10:00:01Z",
     "input": json.dumps({"order_id": "A1", "amount": 900}), "output": "denied", "level": "ERROR",
     "statusMessage": "amount over limit"},
]


def test_langfuse_observations_become_conversations() -> None:
    convs = from_langfuse(LANGFUSE_ROOTS, LANGFUSE_TOOLS)
    assert [c["id"] for c in convs] == ["tr1", "tr2"]
    t = convs[0]["turns"][0]
    assert (t["user"], t["assistant"]) == ("Refund my $900 order", "Your refund was issued.")
    assert t["actions"] == [{"name": "refund_api", "input": {"order_id": "A1", "amount": 900}, "output": "denied",
                             "success": False, "error": "amount over limit"}]
    assert convs[1]["turns"] == [{"user": "What are your hours?", "assistant": "9 to 5.", "actions": []}]
    assert convs[0]["started_at"].startswith("2026-10-01")


LANGSMITH_ROOT = {
    "id": "r1", "trace_id": "r1", "name": "LangGraph", "run_type": "chain", "start_time": "2026-10-03T09:00:00",
    "inputs": {"messages": [{"type": "human", "content": "Refund $900 for A1"}]},
    "outputs": {"messages": [
        {"type": "human", "content": "Refund $900 for A1"},
        {"type": "ai", "content": "", "tool_calls": [{"name": "refund_api", "args": {"amount": 900}, "id": "x1"}]},
        {"type": "tool", "content": "Error: over limit", "tool_call_id": "x1", "status": "error"},
        {"type": "ai", "content": "Refund issued!"}]},
    "error": None,
}


def test_langsmith_langgraph_run_uses_the_full_message_history() -> None:
    [conv] = from_langsmith([LANGSMITH_ROOT], tools=[
        {"trace_id": "r1", "name": "refund_api", "inputs": {"amount": 900}, "error": "over limit"}])
    [turn] = conv["turns"]
    assert (turn["user"], turn["assistant"]) == ("Refund $900 for A1", "Refund issued!")
    assert len(turn["actions"]) == 1 and turn["actions"][0]["success"] is False  # from messages, not duplicated


def test_langsmith_plain_chain_run_with_separate_tool_runs() -> None:
    root = {"id": "r2", "trace_id": "r2", "start_time": "2026-10-03T09:00:00", "inputs": {"question": "Cancel order 7"},
            "outputs": {"output": "Cancelled."}, "error": None}
    tools = [{"trace_id": "r2", "name": "cancel_order", "inputs": {"input": {"order": 7}}, "outputs": {"output": "ok"},
              "error": None, "start_time": "2026-10-03T09:00:01"}]
    [conv] = from_langsmith([root], tools)
    assert conv["turns"][0]["user"] == "Cancel order 7" and conv["turns"][0]["assistant"] == "Cancelled."
    assert conv["turns"][0]["actions"][0]["input"] == {"order": 7}


def test_to_steps_ends_the_session_and_keeps_the_original_time() -> None:
    conv = {"id": "tr1", "started_at": "2026-10-01T10:00:00+00:00", "turns": [
        {"user": "a", "assistant": "b", "actions": [{"name": "x", "input": {"k": 1}, "success": False, "error": "e"}]},
        {"user": "c", "assistant": "d", "actions": []}]}
    steps = to_steps(conv, "bot", "langfuse")
    assert [(s["step_number"], s["session_ended"]) for s in steps] == [(1, False), (2, True)]
    assert steps[0]["session_id"] == "langfuse-tr1" and steps[0]["timestamp"].startswith("2026-10-01")
    assert steps[0]["tool_calls"] == [{"name": "x", "input": {"k": 1}, "success": False, "error": "e"}]


class _Resp:
    def __init__(self, status: int, body: Any) -> None:
        self.status_code, self._body = status, body

    def json(self) -> Any:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_fetch_langfuse_pages_roots_then_tools_with_basic_auth() -> None:
    calls: List[Dict[str, Any]] = []

    def fake_get(url: str, params: Dict[str, Any], timeout: int, headers: Dict[str, str]) -> _Resp:
        calls.append({"url": url, "params": params, "auth": headers["Authorization"]})
        if params.get("isRootObservation"):
            return _Resp(200, {"data": LANGFUSE_ROOTS[:1], "meta": {"cursor": "c2"}} if "cursor" not in params
                         else {"data": LANGFUSE_ROOTS[1:], "meta": {}})
        return _Resp(200, {"data": LANGFUSE_TOOLS + [{**LANGFUSE_TOOLS[0], "traceId": "other"}], "meta": {}})

    with patch.object(importers.requests, "get", fake_get):
        convs = fetch_langfuse("pk-lf-1", "sk-lf-2", "https://cloud.langfuse.com")
    assert [c["id"] for c in convs] == ["tr1", "tr2"]
    assert all(c["url"] == "https://cloud.langfuse.com/api/public/v2/observations" for c in calls)
    assert calls[0]["auth"] == "Basic cGstbGYtMTpzay1sZi0y"  # base64("pk-lf-1:sk-lf-2")
    assert calls[0]["params"]["fields"] == "core,basic,io" and calls[1]["params"]["cursor"] == "c2"
    assert calls[2]["params"]["type"] == "TOOL"
    assert calls[0]["params"]["toStartTime"] > calls[0]["params"]["fromStartTime"]  # settled conversations only
    assert len(convs[0]["turns"][0]["actions"]) == 1  # the other trace's tool call isn't attached


def test_fetch_langfuse_bad_keys_say_so() -> None:
    with patch.object(importers.requests, "get", lambda *a, **k: _Resp(401, {})):
        with pytest.raises(ValueError, match="rejected these keys"):
            fetch_langfuse("pk", "sk", "https://cloud.langfuse.com")


def test_fetch_langsmith_finds_the_project_then_pages_runs() -> None:
    posts: List[Dict[str, Any]] = []

    def fake_get(url: str, params: Dict[str, Any], timeout: int, headers: Dict[str, str]) -> _Resp:
        assert url == "https://api.smith.langchain.com/sessions" and headers["x-api-key"] == "lsv2_k"
        return _Resp(200, [{"id": "proj-1", "name": params["name"]}])

    def fake_post(url: str, json: Dict[str, Any], timeout: int, headers: Dict[str, str]) -> _Resp:
        posts.append(dict(json))
        if json.get("is_root"):
            return _Resp(200, {"runs": [LANGSMITH_ROOT, {**LANGSMITH_ROOT, "id": "r9", "trace_id": "r9",
                                                         "status": "pending"}], "cursors": {"next": None}})
        return _Resp(200, {"runs": [], "cursors": {}})

    with patch.object(importers.requests, "get", fake_get), patch.object(importers.requests, "post", fake_post):
        [conv] = fetch_langsmith("lsv2_k", "support-bot", "https://api.smith.langchain.com")
    assert posts[0]["session"] == ["proj-1"] and posts[0]["is_root"] is True and "inputs" in posts[0]["select"]
    assert posts[1]["run_type"] == "tool"
    assert conv["id"] == "r1"


def test_fetch_langsmith_unknown_project() -> None:
    with patch.object(importers.requests, "get", lambda *a, **k: _Resp(200, [])):
        with pytest.raises(ValueError, match="No LangSmith project"):
            fetch_langsmith("lsv2_k", "nope", "https://api.smith.langchain.com")
