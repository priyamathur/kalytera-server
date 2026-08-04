"""
Kalytera transparent LLM proxy — zero-code monitoring.

Start it once:
    kalytera proxy --port 8787 --api-key kly_live_... --agent-id my-agent

Then point your agent at it (no other code changes):
    export OPENAI_BASE_URL=http://localhost:8787/v1
    export ANTHROPIC_BASE_URL=http://localhost:8787

Supports:
    POST /v1/chat/completions   — OpenAI + any compatible provider
    POST /v1/messages           — Anthropic
    Everything else             — forwarded to OpenAI transparently
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from aiohttp import ClientSession, ClientTimeout, web

_OPENAI_UPSTREAM = "https://api.openai.com"
_ANTHROPIC_UPSTREAM = "https://api.anthropic.com"

# Headers that must not be forwarded to upstream
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
})


# ── helpers ───────────────────────────────────────────────────────────────────

def _forward_headers(headers: Any) -> Dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP}


def _messages_to_text(messages: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "")
                for c in content
                if isinstance(c, dict) and c.get("type") == "text"
            )
        parts.append(f"{role}: {content}")
    return "\n".join(parts)


def _parse_openai_chunk(line: str) -> str:
    """Extract text delta from a single OpenAI SSE line."""
    if not line.startswith("data: ") or line.strip() == "data: [DONE]":
        return ""
    try:
        data = json.loads(line[6:])
        return data.get("choices", [{}])[0].get("delta", {}).get("content") or ""
    except Exception:
        return ""


def _parse_anthropic_chunk(line: str) -> str:
    """Extract text delta from a single Anthropic SSE line."""
    if not line.startswith("data: "):
        return ""
    try:
        data = json.loads(line[6:])
        if data.get("type") == "content_block_delta":
            return data.get("delta", {}).get("text") or ""
    except Exception:
        pass
    return ""


# ── session tracker ───────────────────────────────────────────────────────────

class _SessionTracker:
    """
    Tracks session_id and step_number across calls.

    A new session starts when:
    - the caller passes an explicit X-Kalytera-Session-Id that differs from current
    - or the conversation looks fresh (no prior assistant turns in messages)
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._session_id: str = str(uuid.uuid4())[:8]
        self._step: int = 0

    async def get(self, explicit: Optional[str], is_fresh: bool) -> Tuple[str, int]:
        async with self._lock:
            if explicit and explicit != self._session_id:
                self._session_id = explicit
                self._step = 0
            elif not explicit and is_fresh:
                self._session_id = str(uuid.uuid4())[:8]
                self._step = 0
            self._step += 1
            return self._session_id, self._step


# ── proxy core ────────────────────────────────────────────────────────────────

class KalyteraProxy:
    def __init__(
        self,
        *,
        api_key: str,
        agent_id: str,
        port: int = 8787,
        kalytera_endpoint: str = "https://api.kalytera.dev",
    ) -> None:
        self.api_key = api_key
        self.agent_id = agent_id
        self.port = port
        self._endpoint = kalytera_endpoint.rstrip("/")
        self._tracker = _SessionTracker()
        self._http: Optional[ClientSession] = None

    def _client(self) -> ClientSession:
        if self._http is None or self._http.closed:
            self._http = ClientSession(timeout=ClientTimeout(total=120))
        return self._http

    # ── trace sender (fire-and-forget, never raises) ──────────────────────────

    async def _fire(
        self,
        *,
        session_id: str,
        step_number: int,
        step_name: str,
        input_text: str,
        output_text: str,
        latency_ms: int,
        tool_calls: List[Dict[str, Any]],
    ) -> None:
        payload: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "agent_id": self.agent_id,
            "session_id": session_id,
            "step_number": step_number,
            "step_name": step_name,
            "input": input_text,
            "output": output_text,
            "tool_calls": tool_calls,
            "latency_ms": latency_ms,
            "session_ended": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": {"source": "proxy"},
        }
        try:
            async with self._client().post(
                f"{self._endpoint}/trace",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=ClientTimeout(total=5),
            ) as r:
                if r.status not in (200, 201):
                    text = await r.text()
                    print(f"[kalytera] warn {r.status}: {text[:100]}")
        except Exception as exc:
            print(f"[kalytera] trace error (non-fatal): {exc}")

    # ── OpenAI /v1/chat/completions ───────────────────────────────────────────

    async def handle_openai_chat(self, request: web.Request) -> web.Response | web.StreamResponse:
        t0 = time.monotonic()
        body_bytes = await request.read()
        try:
            body: Dict[str, Any] = json.loads(body_bytes)
        except Exception:
            body = {}

        messages: List[Dict[str, Any]] = body.get("messages", [])
        model: str = body.get("model", "unknown")
        is_streaming: bool = bool(body.get("stream", False))

        explicit_sid = request.headers.get("X-Kalytera-Session-Id")
        is_fresh = not any(m.get("role") == "assistant" for m in messages)
        sid, step = await self._tracker.get(explicit_sid, is_fresh)

        input_text = _messages_to_text(messages)
        step_name = model
        fwd_headers = _forward_headers(request.headers)
        upstream_url = f"{_OPENAI_UPSTREAM}/v1/chat/completions"

        if is_streaming:
            return await self._stream(
                request=request,
                upstream_url=upstream_url,
                fwd_headers=fwd_headers,
                body_bytes=body_bytes,
                sid=sid, step=step, step_name=step_name,
                input_text=input_text, t0=t0,
                parse_chunk=_parse_openai_chunk,
            )

        try:
            async with self._client().post(
                upstream_url, data=body_bytes, headers=fwd_headers,
            ) as r:
                resp_bytes = await r.read()
                status = r.status
                ct = r.headers.get("Content-Type", "application/json")
        except Exception as exc:
            print(f"[kalytera] upstream error: {exc}")
            return web.Response(status=502, text=f"Upstream error: {exc}")

        latency_ms = int((time.monotonic() - t0) * 1000)
        output_text = ""
        tool_calls: List[Dict[str, Any]] = []

        if status == 200:
            try:
                rj = json.loads(resp_bytes)
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

        asyncio.create_task(self._fire(
            session_id=sid, step_number=step, step_name=step_name,
            input_text=input_text, output_text=output_text,
            latency_ms=latency_ms, tool_calls=tool_calls,
        ))
        return web.Response(body=resp_bytes, status=status,
                            content_type=ct.split(";")[0].strip())

    # ── Anthropic /v1/messages ────────────────────────────────────────────────

    async def handle_anthropic_messages(self, request: web.Request) -> web.Response | web.StreamResponse:
        t0 = time.monotonic()
        body_bytes = await request.read()
        try:
            body = json.loads(body_bytes)
        except Exception:
            body = {}

        messages: List[Dict[str, Any]] = body.get("messages", [])
        model: str = body.get("model", "unknown")
        system: str = body.get("system", "")
        is_streaming: bool = bool(body.get("stream", False))

        explicit_sid = request.headers.get("X-Kalytera-Session-Id")
        is_fresh = not any(m.get("role") == "assistant" for m in messages)
        sid, step = await self._tracker.get(explicit_sid, is_fresh)

        msg_text = _messages_to_text(messages)
        input_text = f"system: {system}\n{msg_text}" if system else msg_text
        step_name = model
        fwd_headers = _forward_headers(request.headers)
        upstream_url = f"{_ANTHROPIC_UPSTREAM}/v1/messages"

        if is_streaming:
            return await self._stream(
                request=request,
                upstream_url=upstream_url,
                fwd_headers=fwd_headers,
                body_bytes=body_bytes,
                sid=sid, step=step, step_name=step_name,
                input_text=input_text, t0=t0,
                parse_chunk=_parse_anthropic_chunk,
            )

        try:
            async with self._client().post(
                upstream_url, data=body_bytes, headers=fwd_headers,
            ) as r:
                resp_bytes = await r.read()
                status = r.status
                ct = r.headers.get("Content-Type", "application/json")
        except Exception as exc:
            print(f"[kalytera] upstream error: {exc}")
            return web.Response(status=502, text=f"Upstream error: {exc}")

        latency_ms = int((time.monotonic() - t0) * 1000)
        output_text = ""

        if status == 200:
            try:
                rj = json.loads(resp_bytes)
                output_text = " ".join(
                    b.get("text", "")
                    for b in rj.get("content", [])
                    if b.get("type") == "text"
                )
            except Exception:
                pass

        asyncio.create_task(self._fire(
            session_id=sid, step_number=step, step_name=step_name,
            input_text=input_text, output_text=output_text,
            latency_ms=latency_ms, tool_calls=[],
        ))
        return web.Response(body=resp_bytes, status=status,
                            content_type=ct.split(";")[0].strip())

    # ── streaming passthrough ─────────────────────────────────────────────────

    async def _stream(
        self,
        *,
        request: web.Request,
        upstream_url: str,
        fwd_headers: Dict[str, str],
        body_bytes: bytes,
        sid: str,
        step: int,
        step_name: str,
        input_text: str,
        t0: float,
        parse_chunk: Callable[[str], str],
    ) -> web.StreamResponse:
        stream_resp = web.StreamResponse(headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })
        await stream_resp.prepare(request)

        chunks: List[str] = []
        try:
            async with self._client().post(
                upstream_url, data=body_bytes, headers=fwd_headers,
            ) as upstream:
                async for raw_line in upstream.content:
                    await stream_resp.write(raw_line)
                    text = raw_line.decode("utf-8", errors="replace").strip()
                    piece = parse_chunk(text)
                    if piece:
                        chunks.append(piece)
        except Exception as exc:
            print(f"[kalytera] stream error: {exc}")

        await stream_resp.write_eof()
        latency_ms = int((time.monotonic() - t0) * 1000)
        asyncio.create_task(self._fire(
            session_id=sid, step_number=step, step_name=step_name,
            input_text=input_text, output_text="".join(chunks),
            latency_ms=latency_ms, tool_calls=[],
        ))
        return stream_resp

    # ── transparent passthrough for all other routes ──────────────────────────

    async def handle_passthrough(self, request: web.Request) -> web.Response:
        path = request.path
        qs = request.query_string
        url = f"{_OPENAI_UPSTREAM}{path}" + (f"?{qs}" if qs else "")
        body_bytes = await request.read()
        fwd_headers = _forward_headers(request.headers)
        try:
            async with self._client().request(
                request.method, url, data=body_bytes, headers=fwd_headers,
            ) as r:
                resp_bytes = await r.read()
                ct = r.headers.get("Content-Type", "application/octet-stream")
                return web.Response(body=resp_bytes, status=r.status,
                                    content_type=ct.split(";")[0].strip())
        except Exception as exc:
            return web.Response(status=502, text=f"Upstream error: {exc}")

    # ── app factory + runner ──────────────────────────────────────────────────

    def build_app(self) -> web.Application:
        app = web.Application()
        app.router.add_post("/v1/chat/completions", self.handle_openai_chat)
        app.router.add_post("/v1/messages", self.handle_anthropic_messages)
        app.router.add_route("*", "/{path_info:.*}", self.handle_passthrough)
        return app

    def run(self) -> None:
        print(
            f"\n✓ Kalytera proxy running  (port {self.port})\n"
            f"  agent_id : {self.agent_id}\n"
            f"  reports to : {self._endpoint}\n"
            f"\n"
            f"  Point your agent at it:\n"
            f"    OPENAI_BASE_URL=http://localhost:{self.port}/v1\n"
            f"    ANTHROPIC_BASE_URL=http://localhost:{self.port}\n"
            f"\n"
            f"  All LLM calls captured automatically.\n"
            f"  Press Ctrl+C to stop.\n"
        )
        web.run_app(self.build_app(), host="127.0.0.1", port=self.port, print=None)
