"""
Kalytera interceptor — captures agent steps, sends to API asynchronously.
Constraint: never raises, never blocks. Returns in <5ms.

Problems that mean traces are NOT being recorded (rejected key, monthly limit,
unreachable endpoint) are printed once to stderr — never silently dropped.
"""
import asyncio
import functools
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from queue import Full, Queue
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import aiohttp

from . import config as _cfg


_queue: Queue[Dict[str, Any]] = Queue(maxsize=500)
_worker: Optional[threading.Thread] = None
_agent_id: str = ""
_api_endpoint: str = ""
_api_key: str = ""
_notified: Set[str] = set()

_SIGNUP_URL = "https://kalytera.dev"
_DASHBOARD_URL = "https://app.kalytera.dev"


def init(api_key: str, agent_id: str = "", api_endpoint: str = "", verify: bool = True) -> None:
    """
    Configure Kalytera. Call once at startup before the first trace.

    With verify=True (default) the API key is checked in a background thread and
    the result is printed — init() itself still returns immediately.
    """
    global _agent_id, _api_key, _api_endpoint
    _auto_id = not agent_id
    _agent_id = agent_id or str(uuid.uuid4())[:8]
    _api_key = api_key
    _api_endpoint = (api_endpoint or _cfg.DEFAULT_ENDPOINT).rstrip("/")
    _notified.clear()
    _ensure_worker()
    id_note = f"  ⚠  agent_id auto-set to '{_agent_id}' — pass agent_id='..' to configure() to use a stable name\n" if _auto_id else ""
    print(
        f"Kalytera configured  (agent_id='{_agent_id}')\n"
        f"{id_note}"
        f"  Sending to: {_api_endpoint}\n"
        f"  Run kalytera.check() to confirm traces are recorded and scored."
    )
    if not api_key:
        _notify("no_key", f"✗ Kalytera: no API key set — traces will NOT be recorded. Get a free key at {_SIGNUP_URL}")
    elif verify:
        threading.Thread(target=_verify_key_in_background, daemon=True).start()


def check(timeout: float = 90.0, wait_for_score: bool = True) -> bool:
    """
    End-to-end self-test. Blocks (unlike trace()) and prints each stage:
      1. the API key is accepted
      2. a test step is recorded
      3. the server scores it (skipped if wait_for_score=False)

    Returns True if traces are being recorded. The test step appears in your
    dashboard as step 'kalytera_check' — its score itself doesn't matter.
    """
    print("Kalytera check")
    if not _api_key:
        print(f"  ✗ No API key. Call kalytera.configure(api_key='kly_live_...') first. Get a key at {_SIGNUP_URL}")
        return False

    status, body, err = _http("GET", "/agents")
    problem = _connection_problem(status, err)
    if problem:
        print(f"  {problem[1]}")
        return False
    print("  ✓ API key accepted")

    session_id = f"kalytera-check-{uuid.uuid4().hex[:8]}"
    payload = _build_payload(
        session_id=session_id, step_number=1, step_name="kalytera_check",
        input="Kalytera connection check", output="Connection check completed.",
        tool_calls=None, metadata={"kalytera_check": True}, agent_id=None, session_ended=True,
    )
    status, body, err = _http("POST", "/trace", payload)
    if status != 201:
        detail = err or _detail(body) or f"HTTP {status}"
        print(f"  ✗ Test step was not recorded: {detail}")
        return False
    print(f"  ✓ Test step recorded  (agent_id='{payload['agent_id']}', session_id='{session_id}')")

    if not wait_for_score:
        print(f"  Scoring runs on the server — see {_DASHBOARD_URL}")
        return True

    print(f"  … waiting for the server to score it (up to {int(timeout)}s)")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, body, err = _http("GET", f"/trace/{payload['id']}/eval")
        if status == 404 and _detail(body) == "Not Found":
            print(f"  ⚠ This server doesn't report scores to the SDK yet — check {_DASHBOARD_URL} in a minute")
            return True
        if status == 200 and isinstance(body, dict) and body.get("status") == "scored":
            print(
                f"  ✓ Scored by the LLM judge: overall {body.get('overall_score', 0):.2f}"
                f"  ({'passed' if body.get('passed') else 'failed'})"
            )
            if body.get("eval_error"):
                print("  ⚠ The judge reported an error for this step — check the server's judge API key")
            print(f"  All set. Your traces will appear at {_DASHBOARD_URL}")
            return True
        time.sleep(3)
    print(
        f"  ⚠ Recorded, but not scored within {int(timeout)}s. The server scores in batches —"
        f" check {_DASHBOARD_URL} in a few minutes."
    )
    return True


def trace(
    session_id: str,
    step_number: int,
    step_name: str,
    input: str,
    output: str,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    agent_id: Optional[str] = None,
    session_ended: bool = False,
) -> None:
    """
    Record one agent step. Returns immediately. Never raises.

    Pass session_ended=True on the last step of a session — sessions are scored
    once they end.
    """
    try:
        payload = _build_payload(
            session_id, step_number, step_name, input, output,
            tool_calls, metadata, agent_id, session_ended,
        )
        _ensure_worker()
        _queue.put_nowait(payload)
    except Full:
        _log_error("queue full, dropping trace event")
    except Exception as exc:
        _log_error(f"trace() internal error: {exc}")


def _build_payload(
    session_id: Any,
    step_number: Any,
    step_name: Any,
    input: Any,
    output: Any,
    tool_calls: Any,
    metadata: Any,
    agent_id: Optional[str],
    session_ended: Any,
) -> Dict[str, Any]:
    """Normalise trace() arguments into the POST /trace body. May raise on bad input."""
    meta = metadata if isinstance(metadata, dict) else {}
    return {
        "id": str(uuid.uuid4()),
        "agent_id": agent_id or _agent_id,
        "session_id": str(session_id) if session_id is not None else "",
        "step_number": int(step_number) if step_number is not None else 1,
        "step_name": str(step_name) if step_name is not None else "",
        "input": str(input) if input is not None else "",
        "output": str(output) if output is not None else "",
        "tool_calls": tool_calls if isinstance(tool_calls, list) else [],
        "latency_ms": int(meta.get("latency_ms", 0) or 0),
        "session_ended": bool(session_ended),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": meta,
    }


def watch(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: wraps an agent function, traces each call as a single step."""
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        session_id = str(uuid.uuid4())
        input_text = str(args[0]) if args else str(kwargs)
        t0 = time.monotonic()
        result = None
        error: Optional[Exception] = None
        try:
            result = fn(*args, **kwargs)
            return result
        except Exception as exc:
            error = exc
            raise
        finally:
            latency_ms = int((time.monotonic() - t0) * 1000)
            output_text = f"ERROR: {error}" if error else str(result)
            trace(
                session_id=session_id,
                step_number=1,
                step_name=fn.__name__,
                input=input_text,
                output=output_text,
                metadata={"latency_ms": latency_ms, "error": error is not None},
                session_ended=True,  # each call is a complete one-step session
            )
    return wrapper


def _ensure_worker() -> None:
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_worker_loop, daemon=True)
        _worker.start()


def _worker_loop() -> None:
    while True:
        try:
            payload = _queue.get(timeout=1.0)
            try:
                _send_with_retry(payload)
            finally:
                _queue.task_done()
        except Exception:
            pass


def _send_with_retry(payload: Dict[str, Any]) -> None:
    for attempt in range(_cfg.SEND_RETRIES + 1):
        try:
            asyncio.run(_send(payload))
            return
        except Exception as exc:
            if attempt < _cfg.SEND_RETRIES:
                time.sleep(2)
                continue
            _notify(
                "network",
                f"✗ Kalytera: can't reach {_api_endpoint or _cfg.DEFAULT_ENDPOINT} ({exc or type(exc).__name__})"
                " — traces are being dropped.",
            )


async def _send(payload: Dict[str, Any]) -> None:
    endpoint = _api_endpoint or _cfg.DEFAULT_ENDPOINT
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if _api_key:
        headers["Authorization"] = f"Bearer {_api_key}"
    timeout = aiohttp.ClientTimeout(total=_cfg.REQUEST_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(f"{endpoint}/trace", json=payload, headers=headers) as resp:
            if resp.status >= 400:
                problem = _connection_problem(resp.status, None)
                if problem:
                    _notify(*problem)


def _verify_key_in_background() -> None:
    status, _body, err = _http("GET", "/agents")
    problem = _connection_problem(status, err)
    if problem:
        _notify(*problem)
    else:
        _notify("verified", f"✓ Kalytera connected — API key accepted. Traces will appear at {_DASHBOARD_URL}")


def _connection_problem(status: Optional[int], err: Optional[str]) -> Optional[Tuple[str, str]]:
    """Map a response to (kind, user-facing message), or None if the key works."""
    endpoint = _api_endpoint or _cfg.DEFAULT_ENDPOINT
    if err is not None:
        return "network", f"✗ Kalytera: can't reach {endpoint} ({err}) — traces are being dropped."
    if status in (401, 403):
        return "auth", (
            f"✗ Kalytera: API key rejected (HTTP {status}) — traces will NOT be recorded."
            f" Check the key, or get one at {_SIGNUP_URL}"
        )
    if status == 429:
        return "limit", f"✗ Kalytera: monthly session limit reached — traces are being dropped. Upgrade at {_SIGNUP_URL}"
    if status is None or status >= 400:
        return f"http_{status}", f"✗ Kalytera: server returned HTTP {status} — traces may not be recorded."
    return None


def _http(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Tuple[Optional[int], Any, Optional[str]]:
    """Blocking stdlib request for check()/verification. Returns (status, json_body, network_error)."""
    endpoint = _api_endpoint or _cfg.DEFAULT_ENDPOINT
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{endpoint}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if _api_key:
        req.add_header("Authorization", f"Bearer {_api_key}")
    try:
        with urllib.request.urlopen(req, timeout=_cfg.REQUEST_TIMEOUT) as resp:
            return resp.status, _json_or_none(resp.read()), None
    except urllib.error.HTTPError as exc:
        return exc.code, _json_or_none(exc.read()), None
    except Exception as exc:
        reason = getattr(exc, "reason", None) or exc
        return None, None, str(reason) or type(exc).__name__


def _json_or_none(raw: bytes) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return None


def _detail(body: Any) -> Optional[str]:
    if isinstance(body, dict):
        detail = body.get("detail")
        return detail if isinstance(detail, str) else (json.dumps(detail) if detail else None)
    return None


def _notify(kind: str, msg: str) -> None:
    """Print a message to stderr once per kind, and always append it to the error log."""
    _log_error(msg)
    if kind in _notified:
        return
    _notified.add(kind)
    try:
        print(msg, file=sys.stderr, flush=True)
    except Exception:
        pass


def _log_error(msg: str) -> None:
    try:
        os.makedirs(os.path.dirname(_cfg.ERROR_LOG_PATH), exist_ok=True)
        with open(_cfg.ERROR_LOG_PATH, "a") as f:
            f.write(f"[{datetime.now(timezone.utc).isoformat()}] {msg}\n")
    except Exception:
        pass
