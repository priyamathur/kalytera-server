"""
Tests for api/proxy_router.py — hosted LLM proxy.

All upstream HTTP calls and DB writes are mocked — no real network or DB.
"""
from __future__ import annotations

import json
import os
from contextlib import ExitStack
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.proxy_router import _new_session_id, _next_step


# ── helpers ───────────────────────────────────────────────────────────────────

def _openai_resp(content: str = "hello") -> bytes:
    return json.dumps({
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
    }).encode()


def _anthropic_resp(text: str = "bonjour") -> bytes:
    return json.dumps({
        "content": [{"type": "text", "text": text}],
        "model": "claude-3-haiku-20240307",
        "stop_reason": "end_turn",
    }).encode()


def _mock_upstream_cm(body: bytes, status: int = 200, ct: str = "application/json") -> MagicMock:
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=cm)
    cm.__aexit__ = AsyncMock(return_value=False)
    cm.read = AsyncMock(return_value=body)
    cm.status = status
    cm.headers = {"Content-Type": ct}
    return cm


def _mock_org(tier: str = "free") -> MagicMock:
    org = MagicMock()
    org.id = "org-test-1"
    org.name = "Test Org"
    org.tier = tier
    return org


def _mock_key_row(org_id: str = "org-test-1") -> MagicMock:
    row = MagicMock()
    row.org_id = org_id
    return row


def _auth_stack(stack: ExitStack, mock_http: bool = True) -> MagicMock:
    """Enter auth patches into an ExitStack. Returns mock_http if requested."""
    stack.enter_context(patch("api.proxy_router.get_apikey_by_hash", return_value=_mock_key_row()))
    stack.enter_context(patch("api.proxy_router.get_org_by_id", return_value=_mock_org()))
    stack.enter_context(patch("api.proxy_router.get_current_usage", return_value=None))
    if mock_http:
        return stack.enter_context(patch("api.proxy_router._http"))
    return MagicMock()


# ── app fixture ───────────────────────────────────────────────────────────────

@pytest.fixture
def client() -> TestClient:
    os.environ["DATABASE_URL"] = "sqlite:///./kalytera_hosted_proxy_test.db"
    os.environ["KALYTERA_API_KEY"] = ""
    from api.main import app
    return TestClient(app, raise_server_exceptions=False)


# ── unit: step counter ────────────────────────────────────────────────────────

class TestNextStep:
    def test_new_session_starts_at_one(self) -> None:
        sid = _new_session_id()
        assert _next_step(sid) == 1

    def test_same_session_increments(self) -> None:
        sid = _new_session_id()
        s1 = _next_step(sid)
        s2 = _next_step(sid)
        s3 = _next_step(sid)
        assert s1 == 1 and s2 == 2 and s3 == 3

    def test_different_sessions_independent(self) -> None:
        sid_a = _new_session_id()
        sid_b = _new_session_id()
        _next_step(sid_a)
        _next_step(sid_a)
        assert _next_step(sid_b) == 1


# ── integration: auth ─────────────────────────────────────────────────────────

class TestHostedProxyAuth:
    def test_invalid_key_returns_401(self, client: TestClient) -> None:
        with patch("api.proxy_router.get_apikey_by_hash", return_value=None):
            resp = client.post(
                "/proxy/kly_live_BADKEY/v1/chat/completions",
                json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            )
        assert resp.status_code == 401

    def test_valid_key_passes_auth(self, client: TestClient) -> None:
        with ExitStack() as stack:
            mock_http = _auth_stack(stack)
            stack.enter_context(patch("api.proxy_router._write_trace_async", new_callable=AsyncMock))
            mock_http.return_value.request = MagicMock(return_value=_mock_upstream_cm(_openai_resp()))
            resp = client.post(
                "/proxy/kly_live_VALIDKEY/v1/chat/completions",
                json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            )
        assert resp.status_code == 200

    def test_rate_limited_returns_429(self, client: TestClient) -> None:
        usage = MagicMock()
        usage.session_count = 10000
        with ExitStack() as stack:
            stack.enter_context(patch("api.proxy_router.get_apikey_by_hash", return_value=_mock_key_row()))
            stack.enter_context(patch("api.proxy_router.get_org_by_id", return_value=_mock_org()))
            stack.enter_context(patch("api.proxy_router.get_current_usage", return_value=usage))
            resp = client.post(
                "/proxy/kly_live_KEY/v1/chat/completions",
                json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            )
        assert resp.status_code == 429


# ── integration: OpenAI format ────────────────────────────────────────────────

class TestHostedProxyOpenAI:
    def test_forwards_and_returns_response(self, client: TestClient) -> None:
        with ExitStack() as stack:
            mock_http = _auth_stack(stack)
            stack.enter_context(patch("api.proxy_router._write_trace_async", new_callable=AsyncMock))
            mock_http.return_value.request = MagicMock(return_value=_mock_upstream_cm(_openai_resp("world")))
            resp = client.post(
                "/proxy/kly_live_KEY/v1/chat/completions",
                json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hello"}]},
            )
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "world"

    def test_agent_id_from_header(self, client: TestClient) -> None:
        captured: list = []

        async def capture(**kwargs: Any) -> None:
            captured.append(kwargs)

        with ExitStack() as stack:
            mock_http = _auth_stack(stack)
            stack.enter_context(patch("api.proxy_router._write_trace_async", side_effect=capture))
            mock_http.return_value.request = MagicMock(return_value=_mock_upstream_cm(_openai_resp()))
            client.post(
                "/proxy/kly_live_KEY/v1/chat/completions",
                headers={"X-Kalytera-Agent-Id": "my-prod-agent"},
                json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            )

        assert len(captured) == 1
        assert captured[0]["agent_id"] == "my-prod-agent"

    def test_default_agent_id_uses_key_prefix(self, client: TestClient) -> None:
        captured: list = []

        async def capture(**kwargs: Any) -> None:
            captured.append(kwargs)

        with ExitStack() as stack:
            mock_http = _auth_stack(stack)
            stack.enter_context(patch("api.proxy_router._write_trace_async", side_effect=capture))
            mock_http.return_value.request = MagicMock(return_value=_mock_upstream_cm(_openai_resp()))
            client.post(
                "/proxy/kly_live_ABCDEF/v1/chat/completions",
                json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            )

        assert "kly_live_" in captured[0]["agent_id"]

    def test_explicit_session_id_header(self, client: TestClient) -> None:
        captured: list = []

        async def capture(**kwargs: Any) -> None:
            captured.append(kwargs)

        with ExitStack() as stack:
            mock_http = _auth_stack(stack)
            stack.enter_context(patch("api.proxy_router._write_trace_async", side_effect=capture))
            mock_http.return_value.request = MagicMock(return_value=_mock_upstream_cm(_openai_resp()))
            client.post(
                "/proxy/kly_live_KEY/v1/chat/completions",
                headers={"X-Kalytera-Session-Id": "prod-session-xyz"},
                json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            )

        assert captured[0]["session_id"] == "prod-session-xyz"

    def test_fresh_conversations_get_distinct_session_ids(self, client: TestClient) -> None:
        sessions: list = []

        async def capture(**kwargs: Any) -> None:
            sessions.append(kwargs["session_id"])

        with ExitStack() as stack:
            mock_http = _auth_stack(stack)
            stack.enter_context(patch("api.proxy_router._write_trace_async", side_effect=capture))
            mock_http.return_value.request = MagicMock(return_value=_mock_upstream_cm(_openai_resp()))
            for _ in range(2):
                client.post(
                    "/proxy/kly_live_KEY/v1/chat/completions",
                    json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
                )

        assert len(sessions) == 2
        assert sessions[0] != sessions[1]

    def test_upstream_error_returns_502(self, client: TestClient) -> None:
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
        cm.__aexit__ = AsyncMock(return_value=False)

        with ExitStack() as stack:
            mock_http = _auth_stack(stack)
            mock_http.return_value.request = MagicMock(return_value=cm)
            resp = client.post(
                "/proxy/kly_live_KEY/v1/chat/completions",
                json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            )
        assert resp.status_code == 502

    def test_tool_calls_captured(self, client: TestClient) -> None:
        body = json.dumps({
            "choices": [{
                "message": {
                    "role": "assistant", "content": None,
                    "tool_calls": [{"function": {"name": "search", "arguments": '{"q":"test"}'}}],
                },
            }]
        }).encode()
        captured: list = []

        async def capture(**kwargs: Any) -> None:
            captured.append(kwargs)

        with ExitStack() as stack:
            mock_http = _auth_stack(stack)
            stack.enter_context(patch("api.proxy_router._write_trace_async", side_effect=capture))
            mock_http.return_value.request = MagicMock(return_value=_mock_upstream_cm(body))
            client.post(
                "/proxy/kly_live_KEY/v1/chat/completions",
                json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "search?"}]},
            )

        assert captured[0]["tool_calls"][0]["name"] == "search"


# ── integration: Anthropic format ─────────────────────────────────────────────

class TestHostedProxyAnthropic:
    def test_messages_endpoint_traced(self, client: TestClient) -> None:
        captured: list = []

        async def capture(**kwargs: Any) -> None:
            captured.append(kwargs)

        with ExitStack() as stack:
            mock_http = _auth_stack(stack)
            stack.enter_context(patch("api.proxy_router._write_trace_async", side_effect=capture))
            mock_http.return_value.request = MagicMock(return_value=_mock_upstream_cm(_anthropic_resp("bonjour")))
            resp = client.post(
                "/proxy/kly_live_KEY/v1/messages",
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": "say bonjour"}],
                },
            )

        assert resp.status_code == 200
        assert resp.json()["content"][0]["text"] == "bonjour"
        assert captured[0]["output_text"] == "bonjour"

    def test_system_prompt_included_in_input(self, client: TestClient) -> None:
        captured: list = []

        async def capture(**kwargs: Any) -> None:
            captured.append(kwargs)

        with ExitStack() as stack:
            mock_http = _auth_stack(stack)
            stack.enter_context(patch("api.proxy_router._write_trace_async", side_effect=capture))
            mock_http.return_value.request = MagicMock(return_value=_mock_upstream_cm(_anthropic_resp()))
            client.post(
                "/proxy/kly_live_KEY/v1/messages",
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 100,
                    "system": "You are helpful.",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )

        assert "You are helpful." in captured[0]["input_text"]


# ── integration: passthrough ──────────────────────────────────────────────────

class TestHostedProxyPassthrough:
    def test_non_inference_routes_forwarded(self, client: TestClient) -> None:
        with ExitStack() as stack:
            mock_http = _auth_stack(stack)
            mock_http.return_value.request = MagicMock(
                return_value=_mock_upstream_cm(b'{"object":"list","data":[]}')
            )
            resp = client.get("/proxy/kly_live_KEY/v1/models")
        assert resp.status_code == 200

    def test_passthrough_does_not_write_trace(self, client: TestClient) -> None:
        wrote: list = []

        async def capture(**kwargs: Any) -> None:
            wrote.append(kwargs)

        with ExitStack() as stack:
            mock_http = _auth_stack(stack)
            stack.enter_context(patch("api.proxy_router._write_trace_async", side_effect=capture))
            mock_http.return_value.request = MagicMock(
                return_value=_mock_upstream_cm(b'{"object":"list","data":[]}')
            )
            client.get("/proxy/kly_live_KEY/v1/models")

        assert len(wrote) == 0, "Passthrough routes must not write traces"
