"""
Connect Kalytera to where an agent's production conversations already live
(Langfuse, LangSmith): no code changes. A connection syncs new conversations
continuously (api/connections_api.py); this module only fetches and converts.

Every source becomes the same shape, then the same AgentLog steps the SDK sends:

    conversation = {"id": str, "started_at": iso | None,
                    "turns": [{"user": str, "assistant": str,
                               "actions": [{"name", "input", "output", "success", "error"}]}]}

"""
import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

MAX_CONVERSATIONS = 200   # per pull: keeps judging fast (minutes) and its cost predictable
DEFAULT_DAYS = 30         # how far back the first pull reads
SETTLE_MINUTES = 5        # skip conversations newer than this: they may still be going on
TIMEOUT_S = 30


def _window(since: Optional[datetime]) -> Tuple[str, str]:
    now = datetime.now(timezone.utc)
    start = since or now - timedelta(days=DEFAULT_DAYS)
    return start.isoformat(), (now - timedelta(minutes=SETTLE_MINUTES)).isoformat()

Conversation = Dict[str, Any]


# ── Small helpers ────────────────────────────────────────────────────────────
def _maybe_json(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in "[{":
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def text(value: Any) -> str:
    """Readable text from whatever a tracing tool stored: a string, message, list of parts, or dict."""
    value = _maybe_json(value)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        msgs = _messages(value)
        if msgs:
            return text(msgs[-1].get("content"))
        return " ".join(t for t in (text(v) for v in value) if t)
    if isinstance(value, dict):
        if "kwargs" in value:
            return text(value["kwargs"].get("content"))
        for k in ("content", "text", "output", "answer", "response", "input", "question", "result"):
            if k in value:
                return text(value[k])
        if isinstance(value.get("messages"), list):
            return text(value["messages"])
        return json.dumps(value, default=str)[:4000]
    return str(value)


def _role(m: Dict[str, Any]) -> str:
    if "kwargs" in m:  # LangChain serialized: {"id": [..., "HumanMessage"], "kwargs": {...}}
        kind = (m["kwargs"].get("type") or (m.get("id") or [""])[-1]).lower()
    else:
        kind = str(m.get("role") or m.get("type") or "").lower()
    return {"human": "user", "humanmessage": "user", "ai": "assistant", "aimessage": "assistant",
            "aimessagechunk": "assistant", "toolmessage": "tool", "function": "tool"}.get(kind, kind)


def _messages(value: Any) -> List[Dict[str, Any]]:
    """The list as chat messages, or [] if it doesn't look like one."""
    if not isinstance(value, list) or not value:
        return []
    msgs = [m for m in value if isinstance(m, dict) and _role(m) in ("user", "assistant", "tool", "system")]
    return msgs if len(msgs) == len(value) else []


def _body(m: Dict[str, Any]) -> Dict[str, Any]:
    return m["kwargs"] if "kwargs" in m else m


def _failed(output: str) -> bool:
    data = _maybe_json(output)
    if isinstance(data, dict) and (data.get("error") or data.get("success") is False):
        return True
    return isinstance(output, str) and output.strip().lower().startswith(("error", "exception", "failed"))


def _iso(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, timezone.utc).isoformat()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


# ── Chat messages → turns ────────────────────────────────────────────────────
def messages_to_turns(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """OpenAI-style or LangChain messages → turns. Tool results are attached to the call they answer."""
    turns: List[Dict[str, Any]] = []
    by_call_id: Dict[str, Dict[str, Any]] = {}
    for m in messages:
        role, b = _role(m), _body(m)
        if role == "system":
            continue
        if role == "user":
            turns.append({"user": text(b.get("content")), "assistant": "", "actions": []})
            continue
        if not turns:
            turns.append({"user": "", "assistant": "", "actions": []})
        turn = turns[-1]
        if role == "assistant":
            for call in b.get("tool_calls") or []:
                fn = call.get("function") or {}
                args = _maybe_json(fn.get("arguments") if fn else call.get("args"))
                action = {"name": fn.get("name") or call.get("name") or "action",
                          "input": args if isinstance(args, dict) else {"input": args},
                          "output": "", "success": True, "error": None}
                turn["actions"].append(action)
                if call.get("id"):
                    by_call_id[call["id"]] = action
            said = text(b.get("content"))
            if said:
                turn["assistant"] = f"{turn['assistant']}\n{said}".strip()
        elif role == "tool":
            out = text(b.get("content"))
            action = by_call_id.get(b.get("tool_call_id") or "")
            if action is None:
                action = {"name": b.get("name") or "action", "input": {}, "success": True, "error": None}
                turn["actions"].append(action)
            action["output"] = out[:2000]
            if _failed(out) or b.get("status") == "error":
                action["success"], action["error"] = False, out[:300]
    return [t for t in turns if t["user"] or t["assistant"] or t["actions"]]


# ── Langfuse ─────────────────────────────────────────────────────────────────
LANGFUSE_REGIONS = {"EU (cloud.langfuse.com)": "https://cloud.langfuse.com",
                    "US (us.cloud.langfuse.com)": "https://us.cloud.langfuse.com"}


def _langfuse_pages(base: str, auth: str, params: Dict[str, Any], max_items: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    cursor = None
    while len(out) < max_items:
        q = {**params, **({"cursor": cursor} if cursor else {})}
        r = requests.get(f"{base.rstrip('/')}/api/public/v2/observations", params=q, timeout=TIMEOUT_S,
                         headers={"Authorization": f"Basic {auth}"})
        if r.status_code == 401:
            raise ValueError("Langfuse rejected these keys. Use the project's public key (pk-lf-…) and "
                             "secret key (sk-lf-…), and check the region.")
        r.raise_for_status()
        body = r.json()
        out.extend(body.get("data") or [])
        cursor = (body.get("meta") or {}).get("cursor")
        if not cursor or not body.get("data"):
            break
    return out


def from_langfuse(roots: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> List[Conversation]:
    """Langfuse observations → conversations: one per trace (its root input/output, its TOOL calls)."""
    actions: Dict[str, List[Dict[str, Any]]] = {}
    for t in sorted(tools, key=lambda o: o.get("startTime") or ""):
        failed = t.get("level") == "ERROR"
        actions.setdefault(t.get("traceId") or "", []).append({
            "name": t.get("name") or "action", "input": _as_args(t.get("input")),
            "output": text(t.get("output"))[:2000], "success": not failed,
            "error": (t.get("statusMessage") or "failed") if failed else None})
    convs = []
    for root in roots:
        tid = root.get("traceId") or root.get("id")
        conv = _conversation_from_io(str(tid), root.get("input"), root.get("output"), actions.get(tid, []))
        if conv:
            conv["started_at"] = _iso(root.get("startTime"))
            convs.append(conv)
    return convs


def fetch_langfuse(public_key: str, secret_key: str, base_url: str, since: Optional[datetime] = None,
                   limit: int = MAX_CONVERSATIONS) -> List[Conversation]:
    """Conversations that started after `since` (default: the last 30 days), newest settled ones only."""
    auth = base64.b64encode(f"{public_key.strip()}:{secret_key.strip()}".encode()).decode()
    start, end = _window(since)
    common = {"fields": "core,basic,io", "fromStartTime": start, "toStartTime": end}
    roots = _langfuse_pages(base_url, auth, {**common, "isRootObservation": "true", "limit": min(limit, 1000)}, limit)
    roots = roots[:limit]
    ids = {r.get("traceId") for r in roots}
    tools = [t for t in _langfuse_pages(base_url, auth, {**common, "type": "TOOL", "limit": 1000}, 20_000)
             if t.get("traceId") in ids]
    return from_langfuse(roots, tools)


# ── LangSmith ────────────────────────────────────────────────────────────────
LANGSMITH_REGIONS = {"US (api.smith.langchain.com)": "https://api.smith.langchain.com",
                     "EU (eu.api.smith.langchain.com)": "https://eu.api.smith.langchain.com"}
_RUN_FIELDS = ["id", "trace_id", "name", "inputs", "outputs", "error", "start_time", "status", "run_type"]


def _langsmith_runs(api: str, key: str, body: Dict[str, Any], max_items: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    query = dict(body)
    while len(out) < max_items:
        r = requests.post(f"{api.rstrip('/')}/runs/query", json=query, timeout=TIMEOUT_S, headers={"x-api-key": key})
        if r.status_code in (401, 403):
            raise ValueError("LangSmith rejected this API key (it starts with lsv2_). Check the key and region.")
        r.raise_for_status()
        page = r.json() or {}
        out.extend(page.get("runs") or [])
        nxt = (page.get("cursors") or {}).get("next")
        if not nxt or not page.get("runs"):
            break
        query["cursor"] = nxt
    return out


def from_langsmith(roots: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> List[Conversation]:
    """LangSmith runs → conversations: one per root run (trace), with its tool runs as actions."""
    actions: Dict[str, List[Dict[str, Any]]] = {}
    for t in sorted(tools, key=lambda r: r.get("start_time") or ""):
        actions.setdefault(str(t.get("trace_id")), []).append({
            "name": t.get("name") or "action", "input": _as_args(t.get("inputs")),
            "output": text(t.get("outputs"))[:2000], "success": not t.get("error"),
            "error": str(t["error"])[:300] if t.get("error") else None})
    convs = []
    for root in roots:
        tid = str(root.get("trace_id") or root.get("id"))
        conv = _conversation_from_io(tid, root.get("inputs"), root.get("outputs"), actions.get(tid, []),
                                     error=root.get("error"))
        if conv:
            conv["started_at"] = _iso(root.get("start_time"))
            convs.append(conv)
    return convs


def fetch_langsmith(api_key: str, project: str, api_url: str, since: Optional[datetime] = None,
                    limit: int = MAX_CONVERSATIONS) -> List[Conversation]:
    """Finished conversations (root runs) that started after `since` (default: the last 30 days)."""
    api = api_url.rstrip("/")
    r = requests.get(f"{api}/sessions", params={"name": project.strip(), "limit": 1}, timeout=TIMEOUT_S,
                     headers={"x-api-key": api_key.strip()})
    if r.status_code in (401, 403):
        raise ValueError("LangSmith rejected this API key (it starts with lsv2_). Check the key and region.")
    r.raise_for_status()
    found = r.json()
    found = found if isinstance(found, list) else [found]
    if not found or not found[0].get("id"):
        raise ValueError(f"No LangSmith project named “{project}”. Use the project name shown in LangSmith.")
    start, end = _window(since)
    base = {"session": [found[0]["id"]], "start_time": start, "select": _RUN_FIELDS}
    roots = [r for r in _langsmith_runs(api, api_key.strip(), {**base, "is_root": True, "limit": min(limit, 100)},
                                        limit * 2)
             if r.get("status") != "pending" and str(r.get("start_time") or "") <= end][:limit]
    ids = {str(r.get("trace_id") or r.get("id")) for r in roots}
    tools = [t for t in _langsmith_runs(api, api_key.strip(), {**base, "run_type": "tool", "limit": 100}, 5000)
             if str(t.get("trace_id")) in ids]
    return from_langsmith(roots, tools)


# ── Shared ───────────────────────────────────────────────────────────────────
def _as_args(value: Any) -> Dict[str, Any]:
    value = _maybe_json(value)
    if isinstance(value, dict):
        return value.get("input") if isinstance(value.get("input"), dict) else value
    return {"input": value}


def _io_messages(value: Any) -> List[Dict[str, Any]]:
    value = _maybe_json(value)
    if isinstance(value, dict):
        value = _maybe_json(value.get("messages"))
    return _messages(value) if isinstance(value, list) else []


def _conversation_from_io(cid: str, inputs: Any, outputs: Any, actions: List[Dict[str, Any]],
                          error: Any = None) -> Optional[Conversation]:
    """A traced run's input and output → turns. Message histories are expanded into turns."""
    msgs_in, msgs_out = _io_messages(inputs), _io_messages(outputs)
    if msgs_out and any(_role(m) == "user" for m in msgs_out):
        turns = messages_to_turns(msgs_out)            # output holds the whole conversation (LangGraph)
    elif msgs_in:
        turns = messages_to_turns(msgs_in + msgs_out)
        if not msgs_out and outputs is not None and turns:
            turns[-1]["assistant"] = turns[-1]["assistant"] or text(outputs)
    else:
        turns = [{"user": text(inputs), "assistant": text(outputs), "actions": []}]
    turns = [t for t in turns if t["user"] or t["assistant"] or t["actions"]]
    if not turns:
        return None
    if actions and not any(t["actions"] for t in turns):
        turns[-1]["actions"] = actions                 # tool calls traced separately: attach to the last turn
    if error and not turns[-1]["assistant"]:
        turns[-1]["assistant"] = f"ERROR: {str(error)[:300]}"
    return {"id": cid, "started_at": None, "turns": turns}


def to_steps(conv: Conversation, agent_id: str, source: str) -> List[Dict[str, Any]]:
    """One AgentLog step per turn; the last ends the session so it gets judged."""
    import uuid

    started = conv.get("started_at") or datetime.now(timezone.utc).isoformat()
    turns = conv["turns"]
    return [{
        "id": str(uuid.uuid4()), "agent_id": agent_id, "session_id": f"{source}-{conv['id']}"[:200],
        "step_number": i + 1, "step_name": "turn", "input": t["user"][:20_000], "output": t["assistant"][:20_000],
        "tool_calls": [{"name": a.get("name", "action"), "input": a.get("input") or {},
                        "success": a.get("success", True) is not False,
                        **({"error": a["error"]} if a.get("error") else {})} for a in t.get("actions") or []],
        "session_ended": i == len(turns) - 1, "timestamp": started, "metadata": {"source": source},
    } for i, t in enumerate(turns)]
