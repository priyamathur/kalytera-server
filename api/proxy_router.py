"""
Hosted LLM proxy — /proxy/{kalytera_key}/{path}

Production-ready zero-code monitoring. Developer changes one env var:
    OPENAI_BASE_URL=https://api.kalytera.dev/proxy/kly_live_YOURKEY/v1
    ANTHROPIC_BASE_URL=https://api.kalytera.dev/proxy/kly_live_YOURKEY

Their LLM API key (OPENAI_API_KEY etc.) stays in the Authorization header
and is forwarded transparently to the real provider. The Kalytera key in
the URL authenticates and routes the trace.

Optional headers the developer can send for finer control:
    X-Kalytera-Agent-Id   — stable agent name (default: proxy-<key_prefix>)
    X-Kalytera-Session-Id — group multi-turn calls into one session
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import aiohttp
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from api.billing import TIERS, hash_key
from api.database import SessionLocal, get_db
from db.queries import (
    get_apikey_by_hash,
    get_current_usage,
    get_org_by_id,
    increment_session_count,
    insert_agent_log,
    upsert_agent_org,
)
from kalytera.proxy import (
    _detect_upstream,
    _messages_to_text,
    _parse_anthropic_chunk,
    _parse_openai_chunk,
)

router = APIRouter()

# ── shared HTTP session ───────────────────────────────────────────────────────

_proxy_http: Optional[aiohttp.ClientSession] = None


def _http() -> aiohttp.ClientSession:
    global _proxy_http
    if _proxy_http is None or _proxy_http.closed:
        _proxy_http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120))
    return _proxy_http


# ── per-session step counter (in-memory, TTL 1h) ─────────────────────────────

_session_steps: Dict[str, Tuple[int, float]] = {}
_SESSION_TTL = 3600.0


def _next_step(session_id: str) -> int:
    now = time.monotonic()
    # Evict sessions idle for more than 1 hour
    stale = [s for s, (_, ts) in _session_steps.items() if now - ts > _SESSION_TTL]
    for s in stale:
        del _session_steps[s]
    step, _ = _session_steps.get(session_id, (0, now))
    _session_steps[session_id] = (step + 1, now)
    return step + 1


# ── headers ───────────────────────────────────────────────────────────────────

_STRIP_HEADERS = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
    "x-kalytera-agent-id", "x-kalytera-session-id",
})


def _forward_headers(request: Request) -> Dict[str, str]:
    return {k: v for k, v in request.headers.items() if k.lower() not in _STRIP_HEADERS}


# ── auth + rate limit ─────────────────────────────────────────────────────────

def _validate_org(kalytera_key: str, db: Session) -> Any:
    row = get_apikey_by_hash(hash_key(kalytera_key), db)
    if not row:
        raise HTTPException(401, "Invalid Kalytera API key in proxy URL")
    org = get_org_by_id(row.org_id, db)
    if not org:
        raise HTTPException(401, "Organization not found")

    period = datetime.now(timezone.utc).strftime("%Y-%m")
    usage = get_current_usage(org.id, period, db)
    used = usage.session_count if usage else 0
    limit = TIERS.get(org.tier, TIERS["free"])["sessions"]
    if limit and used >= limit:
        raise HTTPException(429, {
            "error": "monthly_limit_reached",
            "tier": org.tier,
            "sessions_used": used,
            "sessions_limit": limit,
            "upgrade_url": "/billing/checkout",
        })
    return org


# ── trace writer (sync, runs in BackgroundTask / executor) ────────────────────

def _write_trace(
    *,
    org_id: str,
    agent_id: str,
    session_id: str,
    step_number: int,
    step_name: str,
    input_text: str,
    output_text: str,
    latency_ms: int,
    tool_calls: List[Dict[str, Any]],
) -> None:
    db = SessionLocal()
    try:
        insert_agent_log({
            "id": str(uuid.uuid4()),
            "agent_id": agent_id,
            "session_id": session_id,
            "step_number": step_number,
            "step_name": step_name,
            "input": input_text,
            "output": output_text,
            "tool_calls": tool_calls,
            "latency_ms": latency_ms,
            "session_ended": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": {"source": "hosted_proxy"},
        }, db)
        upsert_agent_org(agent_id, org_id, db)
        increment_session_count(org_id, datetime.now(timezone.utc).strftime("%Y-%m"), db)
    except Exception as exc:
        print(f"[hosted_proxy] trace write error (non-fatal): {exc}")
    finally:
        db.close()


async def _write_trace_async(**kwargs: Any) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: _write_trace(**kwargs))


# ── proxy route ───────────────────────────────────────────────────────────────

@router.api_route(
    "/proxy/{kalytera_key}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def hosted_proxy(
    kalytera_key: str,
    path: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """
    Transparent LLM proxy. Forwards the request to the real provider,
    captures input/output, writes a trace row — all without touching
    the developer's agent code.
    """
    t0 = time.monotonic()

    org = _validate_org(kalytera_key, db)

    # Detect real LLM provider from the Authorization header
    auth_header = request.headers.get("Authorization", "")
    _, upstream_base = _detect_upstream(auth_header)
    upstream_url = f"{upstream_base}/{path}"
    if request.url.query:
        upstream_url += f"?{request.url.query}"

    # Agent + session identity
    agent_id = (
        request.headers.get("X-Kalytera-Agent-Id")
        or request.query_params.get("agent_id", "")
        or f"proxy-{kalytera_key[:12]}"
    )
    explicit_sid = request.headers.get("X-Kalytera-Session-Id", "")

    body_bytes = await request.body()
    fwd_headers = _forward_headers(request)

    # Only parse + trace LLM inference endpoints
    is_chat = path.endswith("chat/completions") and request.method == "POST"
    is_messages = path.endswith("messages") and request.method == "POST"
    should_trace = is_chat or is_messages

    # Parse request body for tracing
    input_text = ""
    session_id = explicit_sid or _new_session_id()
    step_name = "unknown"
    is_streaming = False
    parse_chunk = _parse_openai_chunk

    if should_trace:
        try:
            body_json: Dict[str, Any] = json.loads(body_bytes)
        except Exception:
            body_json = {}

        messages: List[Dict[str, Any]] = body_json.get("messages", [])
        step_name = body_json.get("model", "unknown")
        is_streaming = bool(body_json.get("stream", False))

        if not explicit_sid:
            is_fresh = not any(m.get("role") == "assistant" for m in messages)
            session_id = _new_session_id() if is_fresh else session_id

        if is_messages:
            system = body_json.get("system", "")
            msg_text = _messages_to_text(messages)
            input_text = f"system: {system}\n{msg_text}" if system else msg_text
            parse_chunk = _parse_anthropic_chunk
        else:
            input_text = _messages_to_text(messages)

    step_number = _next_step(session_id)
    trace_kwargs: Dict[str, Any] = dict(
        org_id=org.id, agent_id=agent_id, session_id=session_id,
        step_number=step_number, step_name=step_name,
        input_text=input_text,
    )

    # ── streaming ─────────────────────────────────────────────────────────────
    if should_trace and is_streaming:
        async def stream_and_capture() -> AsyncGenerator[bytes, None]:
            chunks: List[str] = []
            try:
                async with _http().post(
                    upstream_url, data=body_bytes, headers=fwd_headers,
                ) as upstream_resp:
                    async for raw_line in upstream_resp.content:
                        yield raw_line
                        text = raw_line.decode("utf-8", errors="replace").strip()
                        piece = parse_chunk(text)
                        if piece:
                            chunks.append(piece)
            except Exception as exc:
                print(f"[hosted_proxy] stream error: {exc}")

            asyncio.create_task(_write_trace_async(
                **trace_kwargs,
                output_text="".join(chunks),
                latency_ms=int((time.monotonic() - t0) * 1000),
            ))

        return StreamingResponse(
            stream_and_capture(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── non-streaming (or passthrough) ────────────────────────────────────────
    try:
        async with _http().request(
            request.method, upstream_url, data=body_bytes, headers=fwd_headers,
        ) as upstream_resp:
            resp_bytes = await upstream_resp.read()
            status_code = upstream_resp.status
            ct = upstream_resp.headers.get("Content-Type", "application/octet-stream")
    except Exception as exc:
        raise HTTPException(502, f"Upstream LLM error: {exc}")

    latency_ms = int((time.monotonic() - t0) * 1000)

    if should_trace and status_code == 200:
        output_text = ""
        tool_calls: List[Dict[str, Any]] = []
        try:
            rj = json.loads(resp_bytes)
            if is_messages:
                output_text = " ".join(
                    b.get("text", "") for b in rj.get("content", []) if b.get("type") == "text"
                )
            else:
                choice = rj.get("choices", [{}])[0]
                msg = choice.get("message", {})
                output_text = msg.get("content") or ""
                for t in msg.get("tool_calls") or []:
                    fn = t.get("function", {})
                    tool_calls.append({
                        "name": fn.get("name", ""),
                        "input": fn.get("arguments", ""),
                        "output": "", "success": True, "latency_ms": 0,
                    })
        except Exception:
            pass

        asyncio.create_task(_write_trace_async(
            **trace_kwargs,
            output_text=output_text,
            latency_ms=latency_ms,
            tool_calls=tool_calls,
        ))

    return Response(
        content=resp_bytes,
        status_code=status_code,
        media_type=ct.split(";")[0].strip(),
    )


def _new_session_id() -> str:
    return str(uuid.uuid4())[:8]
