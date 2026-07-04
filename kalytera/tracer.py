"""
Kalytera interceptor — captures agent steps, sends to API asynchronously.
Constraint: never raises, never blocks. Returns in <5ms.
"""
import asyncio
import functools
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from queue import Full, Queue
from typing import Any, Callable, Dict, List, Optional

import aiohttp

from kalytera import config as _cfg

_queue: Queue[Dict[str, Any]] = Queue(maxsize=500)
_worker: Optional[threading.Thread] = None
_agent_id: str = ""
_api_endpoint: str = ""
_api_key: str = ""


def init(api_key: str, agent_id: str = "", api_endpoint: str = "") -> None:
    """Configure Kalytera. Call once at startup before the first trace."""
    global _agent_id, _api_key, _api_endpoint
    _agent_id = agent_id or str(uuid.uuid4())[:8]
    _api_key = api_key
    _api_endpoint = api_endpoint or _cfg.DEFAULT_ENDPOINT
    _ensure_worker()
    print(
        f"✓ Kalytera connected\n"
        f"  Evaluating every step in real time\n"
        f"  Dashboard: {_api_endpoint}/dashboard"
    )


def trace(
    session_id: str,
    step_number: int,
    step_name: str,
    input: str,
    output: str,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record one agent step. Returns immediately. Never raises."""
    try:
        payload: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "agent_id": _agent_id,
            "session_id": str(session_id) if session_id is not None else "",
            "step_number": int(step_number) if step_number is not None else 1,
            "step_name": str(step_name) if step_name is not None else "",
            "input": str(input) if input is not None else "",
            "output": str(output) if output is not None else "",
            "tool_calls": tool_calls if isinstance(tool_calls, list) else [],
            "latency_ms": (metadata or {}).get("latency_ms", 0),
            "session_ended": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata if isinstance(metadata, dict) else {},
        }
        _ensure_worker()
        _queue.put_nowait(payload)
    except Full:
        _log_error("queue full, dropping trace event")
    except Exception as exc:
        _log_error(f"trace() internal error: {exc}")


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
                asyncio.run(_send(payload))
            except Exception as exc:
                _log_error(f"send failed: {exc}")
            finally:
                _queue.task_done()
        except Exception:
            pass


async def _send(payload: Dict[str, Any]) -> None:
    endpoint = _api_endpoint or _cfg.DEFAULT_ENDPOINT
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if _api_key:
        headers["Authorization"] = f"Bearer {_api_key}"
    timeout = aiohttp.ClientTimeout(total=_cfg.REQUEST_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(f"{endpoint}/trace", json=payload, headers=headers) as resp:
            if resp.status >= 400:
                _log_error(f"POST /trace returned HTTP {resp.status}")


def _log_error(msg: str) -> None:
    try:
        os.makedirs(os.path.dirname(_cfg.ERROR_LOG_PATH), exist_ok=True)
        with open(_cfg.ERROR_LOG_PATH, "a") as f:
            f.write(f"[{datetime.now(timezone.utc).isoformat()}] {msg}\n")
    except Exception:
        pass
