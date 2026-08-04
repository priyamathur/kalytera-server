"""
Tests for kalytera/proxy.py — transparent LLM proxy.

All upstream HTTP calls are mocked — no real network requests.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kalytera.proxy import (
    KalyteraProxy,
    _SessionTracker,
    _messages_to_text,
    _parse_anthropic_chunk,
    _parse_openai_chunk,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_proxy(**kwargs: Any) -> KalyteraProxy:
    return KalyteraProxy(
        api_key="kly_live_test",
        agent_id="test-agent",
        kalytera_endpoint="http://localhost:9999",
        **kwargs,
    )


def _openai_response(content: str = "hello") -> bytes:
    return json.dumps({
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }).encode()


def _anthropic_response(text: str = "hello") -> bytes:
    return json.dumps({
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": "claude-3-haiku-20240307",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }).encode()


def _mock_upstream(body: bytes, status: int = 200) -> MagicMock:
    """Returns a mock that acts like aiohttp ClientSession.post() context manager."""
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=cm)
    cm.__aexit__ = AsyncMock(return_value=False)
    cm.read = AsyncMock(return_value=body)
    cm.status = status
    cm.headers = {"Content-Type": "application/json"}
    return cm


# ── unit: helpers ─────────────────────────────────────────────────────────────

class TestMessagesToText:
    def test_simple(self) -> None:
        msgs = [{"role": "user", "content": "hello"}]
        assert _messages_to_text(msgs) == "user: hello"

    def test_multi_turn(self) -> None:
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = _messages_to_text(msgs)
        assert "user: hi" in result
        assert "assistant: hello" in result

    def test_list_content(self) -> None:
        msgs = [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]
        assert "hello" in _messages_to_text(msgs)

    def test_empty(self) -> None:
        assert _messages_to_text([]) == ""


class TestParseOpenAIChunk:
    def test_valid_chunk(self) -> None:
        line = 'data: {"choices":[{"delta":{"content":"hello"}}]}'
        assert _parse_openai_chunk(line) == "hello"

    def test_done_sentinel(self) -> None:
        assert _parse_openai_chunk("data: [DONE]") == ""

    def test_non_data_line(self) -> None:
        assert _parse_openai_chunk("event: start") == ""

    def test_malformed_json(self) -> None:
        assert _parse_openai_chunk("data: {broken}") == ""

    def test_empty_delta(self) -> None:
        line = 'data: {"choices":[{"delta":{}}]}'
        assert _parse_openai_chunk(line) == ""


class TestParseAnthropicChunk:
    def test_content_block_delta(self) -> None:
        line = 'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"hi"}}'
        assert _parse_anthropic_chunk(line) == "hi"

    def test_other_event_type(self) -> None:
        line = 'data: {"type":"message_start","message":{}}'
        assert _parse_anthropic_chunk(line) == ""

    def test_non_data_line(self) -> None:
        assert _parse_anthropic_chunk("event: content_block_start") == ""

    def test_malformed_json(self) -> None:
        assert _parse_anthropic_chunk("data: {broken}") == ""


# ── unit: session tracker ─────────────────────────────────────────────────────

class TestSessionTracker:
    def test_fresh_conversation_starts_new_session(self) -> None:
        tracker = _SessionTracker()
        first_id = tracker._session_id

        sid, step = asyncio.get_event_loop().run_until_complete(
            tracker.get(explicit=None, is_fresh=True)
        )
        assert sid != first_id
        assert step == 1

    def test_continuing_conversation_reuses_session(self) -> None:
        tracker = _SessionTracker()
        # fresh call sets session
        sid1, _ = asyncio.get_event_loop().run_until_complete(
            tracker.get(explicit=None, is_fresh=True)
        )
        # non-fresh continues
        sid2, step2 = asyncio.get_event_loop().run_until_complete(
            tracker.get(explicit=None, is_fresh=False)
        )
        assert sid1 == sid2
        assert step2 == 2

    def test_explicit_session_id_overrides(self) -> None:
        tracker = _SessionTracker()
        sid, step = asyncio.get_event_loop().run_until_complete(
            tracker.get(explicit="my-session-abc", is_fresh=False)
        )
        assert sid == "my-session-abc"
        assert step == 1

    def test_explicit_session_id_continues(self) -> None:
        tracker = _SessionTracker()
        asyncio.get_event_loop().run_until_complete(
            tracker.get(explicit="sess-1", is_fresh=False)
        )
        sid2, step2 = asyncio.get_event_loop().run_until_complete(
            tracker.get(explicit="sess-1", is_fresh=False)
        )
        assert sid2 == "sess-1"
        assert step2 == 2

    def test_step_increments(self) -> None:
        tracker = _SessionTracker()
        results = [
            asyncio.get_event_loop().run_until_complete(tracker.get(None, False))
            for _ in range(4)
        ]
        steps = [r[1] for r in results]
        assert steps == [1, 2, 3, 4]


# ── integration: OpenAI handler ───────────────────────────────────────────────

@pytest.fixture
def proxy() -> KalyteraProxy:
    return _make_proxy()


@pytest.fixture
async def client(proxy: KalyteraProxy) -> TestClient:
    app = proxy.build_app()
    server = TestServer(app)
    test_client = TestClient(server)
    await test_client.start_server()
    yield test_client
    await test_client.close()


class TestOpenAIHandler:
    async def test_forwards_request_and_returns_response(self, proxy: KalyteraProxy) -> None:
        upstream_resp = _mock_upstream(_openai_response("world"))
        proxy._fire = AsyncMock()

        with patch.object(proxy._client(), "post", return_value=upstream_resp):
            app = proxy.build_app()
            server = TestServer(app)
            async with TestClient(server) as client:
                resp = await client.post(
                    "/v1/chat/completions",
                    json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
                )
                assert resp.status == 200
                body = await resp.json()
                assert body["choices"][0]["message"]["content"] == "world"

    async def test_fires_trace_after_response(self, proxy: KalyteraProxy) -> None:
        upstream_resp = _mock_upstream(_openai_response("pong"))
        fired: list = []

        async def capture(**kwargs: Any) -> None:
            fired.append(kwargs)

        proxy._fire = capture  # type: ignore[method-assign]

        with patch.object(proxy._client(), "post", return_value=upstream_resp):
            app = proxy.build_app()
            async with TestClient(TestServer(app)) as client:
                await client.post(
                    "/v1/chat/completions",
                    json={"model": "gpt-4", "messages": [{"role": "user", "content": "ping"}]},
                )
                await asyncio.sleep(0.05)  # let create_task fire

        assert len(fired) == 1
        assert fired[0]["input_text"] == "user: ping"
        assert fired[0]["output_text"] == "pong"
        assert fired[0]["step_name"] == "gpt-4"

    async def test_upstream_error_returns_502(self, proxy: KalyteraProxy) -> None:
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(proxy._client(), "post", return_value=cm):
            app = proxy.build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.post(
                    "/v1/chat/completions",
                    json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]},
                )
                assert resp.status == 502

    async def test_kalytera_down_does_not_affect_response(self, proxy: KalyteraProxy) -> None:
        upstream_resp = _mock_upstream(_openai_response("fine"))

        async def failing_fire(**kwargs: Any) -> None:
            raise Exception("kalytera is down")

        proxy._fire = failing_fire  # type: ignore[method-assign]

        with patch.object(proxy._client(), "post", return_value=upstream_resp):
            app = proxy.build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.post(
                    "/v1/chat/completions",
                    json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]},
                )
                assert resp.status == 200

    async def test_detects_new_session_on_fresh_conversation(self, proxy: KalyteraProxy) -> None:
        upstream_resp = _mock_upstream(_openai_response())
        sessions: list = []

        async def capture(**kwargs: Any) -> None:
            sessions.append(kwargs["session_id"])

        proxy._fire = capture  # type: ignore[method-assign]

        with patch.object(proxy._client(), "post", return_value=upstream_resp):
            app = proxy.build_app()
            async with TestClient(TestServer(app)) as client:
                # Fresh conversation (no assistant turn)
                await client.post("/v1/chat/completions", json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "first"}],
                })
                await asyncio.sleep(0.05)
                # Another fresh conversation
                await client.post("/v1/chat/completions", json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "second"}],
                })
                await asyncio.sleep(0.05)

        assert len(sessions) == 2
        assert sessions[0] != sessions[1], "Each fresh conversation should get a distinct session_id"

    async def test_continues_session_on_multi_turn(self, proxy: KalyteraProxy) -> None:
        upstream_resp = _mock_upstream(_openai_response())
        sessions: list = []

        async def capture(**kwargs: Any) -> None:
            sessions.append(kwargs["session_id"])

        proxy._fire = capture  # type: ignore[method-assign]

        with patch.object(proxy._client(), "post", return_value=upstream_resp):
            app = proxy.build_app()
            async with TestClient(TestServer(app)) as client:
                # First turn (fresh)
                await client.post("/v1/chat/completions", json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "hello"}],
                })
                # Second turn (has assistant turn — not fresh)
                await client.post("/v1/chat/completions", json={
                    "model": "gpt-4",
                    "messages": [
                        {"role": "user", "content": "hello"},
                        {"role": "assistant", "content": "hi"},
                        {"role": "user", "content": "how are you"},
                    ],
                })
                await asyncio.sleep(0.05)

        assert len(sessions) == 2
        assert sessions[0] == sessions[1], "Multi-turn should reuse the same session_id"

    async def test_explicit_session_id_header(self, proxy: KalyteraProxy) -> None:
        upstream_resp = _mock_upstream(_openai_response())
        sessions: list = []

        async def capture(**kwargs: Any) -> None:
            sessions.append(kwargs["session_id"])

        proxy._fire = capture  # type: ignore[method-assign]

        with patch.object(proxy._client(), "post", return_value=upstream_resp):
            app = proxy.build_app()
            async with TestClient(TestServer(app)) as client:
                await client.post(
                    "/v1/chat/completions",
                    json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]},
                    headers={"X-Kalytera-Session-Id": "my-custom-session"},
                )
                await asyncio.sleep(0.05)

        assert sessions[0] == "my-custom-session"

    async def test_tool_calls_extracted(self, proxy: KalyteraProxy) -> None:
        resp_with_tools = json.dumps({
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city":"NYC"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }]
        }).encode()
        upstream_resp = _mock_upstream(resp_with_tools)
        fired: list = []

        async def capture(**kwargs: Any) -> None:
            fired.append(kwargs)

        proxy._fire = capture  # type: ignore[method-assign]

        with patch.object(proxy._client(), "post", return_value=upstream_resp):
            app = proxy.build_app()
            async with TestClient(TestServer(app)) as client:
                await client.post(
                    "/v1/chat/completions",
                    json={"model": "gpt-4", "messages": [{"role": "user", "content": "weather?"}]},
                )
                await asyncio.sleep(0.05)

        assert len(fired) == 1
        assert fired[0]["tool_calls"][0]["name"] == "get_weather"


# ── integration: Anthropic handler ────────────────────────────────────────────

class TestAnthropicHandler:
    async def test_forwards_and_returns(self, proxy: KalyteraProxy) -> None:
        upstream_resp = _mock_upstream(_anthropic_response("bonjour"))
        fired: list = []

        async def capture(**kwargs: Any) -> None:
            fired.append(kwargs)

        proxy._fire = capture  # type: ignore[method-assign]

        with patch.object(proxy._client(), "post", return_value=upstream_resp):
            app = proxy.build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.post(
                    "/v1/messages",
                    json={
                        "model": "claude-3-haiku-20240307",
                        "max_tokens": 100,
                        "messages": [{"role": "user", "content": "say bonjour"}],
                    },
                )
                assert resp.status == 200
                body = await resp.json()
                assert body["content"][0]["text"] == "bonjour"
                await asyncio.sleep(0.05)

        assert fired[0]["output_text"] == "bonjour"
        assert fired[0]["step_name"] == "claude-3-haiku-20240307"

    async def test_system_prompt_included_in_input(self, proxy: KalyteraProxy) -> None:
        upstream_resp = _mock_upstream(_anthropic_response())
        fired: list = []

        async def capture(**kwargs: Any) -> None:
            fired.append(kwargs)

        proxy._fire = capture  # type: ignore[method-assign]

        with patch.object(proxy._client(), "post", return_value=upstream_resp):
            app = proxy.build_app()
            async with TestClient(TestServer(app)) as client:
                await client.post(
                    "/v1/messages",
                    json={
                        "model": "claude-3-haiku-20240307",
                        "max_tokens": 100,
                        "system": "You are helpful.",
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                )
                await asyncio.sleep(0.05)

        assert "You are helpful." in fired[0]["input_text"]


# ── integration: passthrough ──────────────────────────────────────────────────

class TestPassthrough:
    async def test_unknown_routes_forwarded(self, proxy: KalyteraProxy) -> None:
        models_resp = _mock_upstream(b'{"object":"list","data":[]}')

        with patch.object(proxy._client(), "request", return_value=models_resp):
            app = proxy.build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/v1/models")
                assert resp.status == 200


# ── integration: _fire ────────────────────────────────────────────────────────

class TestFireTrace:
    async def test_posts_to_kalytera(self, proxy: KalyteraProxy) -> None:
        posted: list = []

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_cm)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_cm.status = 201

        def capture_post(url: str, **kwargs: Any) -> Any:
            posted.append({"url": url, "json": kwargs.get("json")})
            return mock_cm

        with patch.object(proxy._client(), "post", side_effect=capture_post):
            await proxy._fire(
                session_id="s1", step_number=1, step_name="gpt-4",
                input_text="hello", output_text="world",
                latency_ms=200, tool_calls=[],
            )

        assert len(posted) == 1
        assert "/trace" in posted[0]["url"]
        assert posted[0]["json"]["agent_id"] == "test-agent"
        assert posted[0]["json"]["input"] == "hello"
        assert posted[0]["json"]["output"] == "world"

    async def test_never_raises_if_kalytera_down(self, proxy: KalyteraProxy) -> None:
        async def boom(*args: Any, **kwargs: Any) -> Any:
            raise Exception("connection refused")

        with patch.object(proxy._client(), "post", side_effect=boom):
            # Should not raise
            await proxy._fire(
                session_id="s1", step_number=1, step_name="gpt-4",
                input_text="hi", output_text="hello",
                latency_ms=100, tool_calls=[],
            )
