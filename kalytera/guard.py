"""
kalytera.guard() — check a tool call against your rules before it runs.

    d = kalytera.guard("refund_api", {"amount": 900}, session_id=sid)
    if not d.allowed:
        return f"Blocked: {d.reason}"

Rules are evaluated in-process from a per-agent cache refreshed every 30s, so a
check makes no network call once rules are loaded. Shadow-mode rules never
change the decision; they are reported as would-blocks. Every decision is sent
to Kalytera in the background (arguments are hashed, never sent).

Fail-open: if rules can't be loaded, guard() returns ALLOW and says why in
Decision.error. If evaluation itself fails, a cached rule for that tool with
fail_closed=true turns the result into DENY. guard() never raises.
"""
import atexit
import dataclasses
import hashlib
import json
import threading
import time
from collections import deque
from queue import Empty, Full, Queue
from typing import Any, Dict, List, Optional, Tuple

from . import tracer as _tracer
from .rules import ALLOW, DENY, Decision, Rule, RuleError, SessionHistory, evaluate, parse_rule

REFRESH_S = 30.0          # how often cached rules are refreshed
RETRY_S = 10.0            # wait before retrying a failed fetch
FIRST_FETCH_TIMEOUT = 3.0  # the first guard() for an agent waits at most this long for rules
FLUSH_S = 1.0
MAX_BATCH = 200
EVENT_RETRY_S = 10.0      # wait before resending decisions that failed to send
MAX_UNSENT = 2000         # decisions kept for resending while the API is down (oldest dropped)

_lock = threading.Lock()
# agent_id -> (rules, fetched_at monotonic, last error)
_cache: Dict[str, Tuple[List[Rule], float, str]] = {}
_refreshing: Dict[str, bool] = {}
_history = SessionHistory()
_events: "Queue[Dict[str, Any]]" = Queue(maxsize=5000)
_sender: Optional[threading.Thread] = None
_unsent: "deque[Dict[str, Any]]" = deque(maxlen=MAX_UNSENT)
_last_send_failure = 0.0


def guard(
    tool: str,
    args: Optional[Dict[str, Any]] = None,
    session_id: str = "",
    agent_id: Optional[str] = None,
) -> Decision:
    """
    Decide whether `tool(args)` may run. Returns a Decision; check `.allowed`.

    `decision` is ALLOW, DENY or ESCALATE. On DENY/ESCALATE, `rule_id` and
    `reason` say which rule decided. Never raises; adds well under 5 ms once
    rules are cached.
    """
    args = args if isinstance(args, dict) else {}
    aid = agent_id or _tracer._agent_id
    rules: List[Rule] = []
    try:
        rules, load_error = _rules_for(aid)
        d = evaluate(rules, tool, args, session_id, _history)
        if load_error:
            d = dataclasses.replace(d, error=load_error)
        if d.decision == ALLOW:
            _history.record(session_id, tool)
    except Exception as exc:
        fail_closed = any(r.fail_closed and r.tool == tool for r in rules)
        d = Decision(DENY if fail_closed else ALLOW, error=f"guard() internal error: {exc}")
    _emit(aid, session_id, tool, args, d)
    return d


def _rules_for(agent_id: str) -> Tuple[List[Rule], str]:
    """Cached rules for an agent. Fetches synchronously only the first time."""
    now = time.monotonic()
    with _lock:
        cached = _cache.get(agent_id)
    if cached is None:
        _refresh(agent_id, timeout=FIRST_FETCH_TIMEOUT)
        with _lock:
            cached = _cache[agent_id]
    rules, fetched_at, error = cached
    wait = RETRY_S if error else REFRESH_S
    if now - fetched_at >= wait:
        _refresh_in_background(agent_id)
    return rules, error


def _refresh_in_background(agent_id: str) -> None:
    with _lock:
        if _refreshing.get(agent_id):
            return
        _refreshing[agent_id] = True

    def run() -> None:
        try:
            _refresh(agent_id)
        finally:
            with _lock:
                _refreshing[agent_id] = False

    threading.Thread(target=run, daemon=True).start()


def _refresh(agent_id: str, timeout: Optional[float] = None) -> None:
    """Fetch rules. On failure keep the last good rules and record the error."""
    from urllib.parse import quote

    status, body, err = _tracer._http("GET", f"/rules?agent_id={quote(agent_id)}", timeout=timeout)
    with _lock:
        previous = _cache.get(agent_id, ([], 0.0, ""))[0]
    if status != 200 or not isinstance(body, dict):
        problem = _tracer._connection_problem(status, err)
        msg = _plain(problem[1]) if problem else f"unexpected response (HTTP {status})"
        error = f"rules unavailable, using {len(previous)} cached rule(s): {msg}"
        _tracer._notify("guard_rules", f"✗ Kalytera guard: {error}")
        with _lock:
            _cache[agent_id] = (previous, time.monotonic(), error)
        return
    rules: List[Rule] = []
    for raw in body.get("rules", []):
        try:
            rules.append(parse_rule(raw))
        except RuleError as exc:
            _tracer._log_error(f"guard: skipping invalid rule: {exc}")
    with _lock:
        _cache[agent_id] = (rules, time.monotonic(), "")


def _args_hash(args: Dict[str, Any]) -> str:
    try:
        raw = json.dumps(args, sort_keys=True, default=str).encode()
    except Exception:
        raw = repr(args).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _emit(agent_id: str, session_id: str, tool: str, args: Dict[str, Any], d: Decision) -> None:
    """Queue the decision for the background sender. Never raises."""
    try:
        _events.put_nowait({
            "agent_id": agent_id,
            "session_id": str(session_id or ""),
            "tool": str(tool),
            "args_hash": _args_hash(args),
            "decision": d.decision,
            "rule_id": d.rule_id or None,
            "rule_version": d.rule_version or None,
            "shadow_hits": [
                {"rule_id": h.rule_id, "rule_version": h.rule_version, "action": h.action}
                for h in d.shadow_hits
            ],
            "error": d.error or None,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "+00:00",
        })
        _ensure_sender()
    except Full:
        _tracer._log_error("guard event queue full, dropping event")
    except Exception as exc:
        _tracer._log_error(f"guard event error: {exc}")


def _ensure_sender() -> None:
    global _sender
    if _sender is None or not _sender.is_alive():
        _sender = threading.Thread(target=_sender_loop, daemon=True)
        _sender.start()


def _sender_loop() -> None:
    global _last_send_failure
    while True:
        batch: List[Dict[str, Any]] = []
        try:
            batch.append(_events.get(timeout=FLUSH_S))
        except Empty:
            pass
        while batch and len(batch) < MAX_BATCH:
            try:
                batch.append(_events.get_nowait())
            except Empty:
                break
        taken = len(batch)
        if _unsent and time.monotonic() - _last_send_failure >= EVENT_RETRY_S:
            batch = list(_unsent) + batch
            _unsent.clear()
        try:
            for i in range(0, len(batch), MAX_BATCH):
                chunk = batch[i:i + MAX_BATCH]
                if not _send(chunk):
                    _unsent.extend(batch[i:])
                    _last_send_failure = time.monotonic()
                    break
        finally:
            for _ in range(taken):
                _events.task_done()


def _send(batch: List[Dict[str, Any]]) -> bool:
    """POST decisions. Returns False if they should be resent later."""
    status, _body, err = _tracer._http("POST", "/guard/events", {"events": batch})
    if status == 202:
        return True
    if status is not None and 400 <= status < 500 and status != 429:
        _tracer._notify("guard_events", f"✗ Kalytera guard: decisions rejected (HTTP {status})")
        return True  # the server won't accept them on retry either
    problem = _tracer._connection_problem(status, err)
    reason = _plain(problem[1]) if problem else f"HTTP {status}"
    _tracer._notify("guard_events", f"✗ Kalytera guard: decisions not recorded yet — {reason}; will retry")
    return False


def _plain(msg: str) -> str:
    """Tracer messages are worded for traces; keep only the cause for guard messages."""
    msg = msg.replace("✗ Kalytera: ", "")
    for tail in (" — traces are being dropped.", " — traces will NOT be recorded.", " — traces may not be recorded."):
        msg = msg.split(tail)[0]
    return msg


def flush(timeout: float = 5.0) -> None:
    """Wait until queued decisions are sent (at most `timeout` seconds). Runs at exit."""
    deadline = time.monotonic() + timeout
    while _events.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.05)


atexit.register(flush, 2.0)


def _reset() -> None:
    """Clear caches and history (tests)."""
    global _history
    with _lock:
        _cache.clear()
        _refreshing.clear()
    _history = SessionHistory()
    _unsent.clear()
    while True:
        try:
            _events.get_nowait()
            _events.task_done()
        except Empty:
            break
