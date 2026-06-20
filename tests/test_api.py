"""Tests for api/main.py — POST /trace and GET /agents/{id}/patterns."""
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Generator, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Prevent database.py from connecting on import
with patch("api.database.initialize_database", return_value=True), \
     patch("api.database.engine", MagicMock()), \
     patch("api.database.SessionLocal", MagicMock()):
    from api.main import app

from api.database import get_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trace_payload(**overrides: Any) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "agent_id": "agent-test",
        "session_id": "session-1",
        "step_number": 1,
        "step_name": "retrieve_policy",
        "input": "What is the refund policy?",
        "output": "30-day refund window.",
        "tool_calls": [],
        "latency_ms": 42,
        "session_ended": False,
        "timestamp": _now_iso(),
        "metadata": {},
    }
    base.update(overrides)
    return base


def _mock_pattern(agent_id: str = "agent-test") -> MagicMock:
    p = MagicMock()
    p.id = str(uuid.uuid4())
    p.agent_id = agent_id
    p.pattern_type = "workflow_step"
    p.pattern_value = "step_3"
    p.failure_count = 8
    p.total_count = 20
    p.failure_rate = 0.4
    p.pct_of_all_failures = 0.6
    p.root_cause = "Payment API timed out at step 3."
    p.is_worsening = True
    p.first_seen = datetime.now(timezone.utc)
    p.last_seen = datetime.now(timezone.utc)
    return p


def _mock_db_noop() -> MagicMock:
    db = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    return db


# ---------------------------------------------------------------------------
# Client fixture — no real DB, no auth key by default
# ---------------------------------------------------------------------------

@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    def _get_db_override() -> Generator[MagicMock, None, None]:
        yield _mock_db_noop()

    app.dependency_overrides[get_db] = _get_db_override
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def authed_client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("AGENTIQ_API_KEY", "test-secret")

    def _get_db_override() -> Generator[MagicMock, None, None]:
        yield _mock_db_noop()

    app.dependency_overrides[get_db] = _get_db_override
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# POST /trace — happy path
# ---------------------------------------------------------------------------

def test_post_trace_returns_201(client: TestClient) -> None:
    with patch("api.main.insert_agent_log") as mock_insert:
        mock_insert.return_value = MagicMock()
        r = client.post("/trace", json=_trace_payload())
    assert r.status_code == 201


def test_post_trace_returns_id_and_status(client: TestClient) -> None:
    payload = _trace_payload()
    with patch("api.main.insert_agent_log"):
        r = client.post("/trace", json=payload)
    body = r.json()
    assert body["id"] == payload["id"]
    assert body["status"] == "accepted"


def test_post_trace_calls_insert(client: TestClient) -> None:
    payload = _trace_payload()
    with patch("api.main.insert_agent_log") as mock_insert:
        mock_insert.return_value = MagicMock()
        client.post("/trace", json=payload)
    mock_insert.assert_called_once()
    call_payload = mock_insert.call_args[0][0]
    assert call_payload["agent_id"] == "agent-test"
    assert call_payload["step_name"] == "retrieve_policy"


def test_post_trace_with_tool_calls(client: TestClient) -> None:
    payload = _trace_payload(tool_calls=[{"name": "payment_api", "success": True}])
    with patch("api.main.insert_agent_log"):
        r = client.post("/trace", json=payload)
    assert r.status_code == 201


# ---------------------------------------------------------------------------
# POST /trace — validation
# ---------------------------------------------------------------------------

def test_post_trace_missing_required_field_returns_422(client: TestClient) -> None:
    payload = _trace_payload()
    del payload["agent_id"]
    r = client.post("/trace", json=payload)
    assert r.status_code == 422


def test_post_trace_invalid_step_number_returns_422(client: TestClient) -> None:
    payload = _trace_payload(step_number="not-an-int")
    r = client.post("/trace", json=payload)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /trace — auth
# ---------------------------------------------------------------------------

def test_post_trace_no_key_configured_allows_all(client: TestClient) -> None:
    """When AGENTIQ_API_KEY is not set, any request passes (dev mode)."""
    with patch("api.main.insert_agent_log"):
        r = client.post("/trace", json=_trace_payload())
    assert r.status_code == 201


def test_post_trace_wrong_key_returns_401(authed_client: TestClient) -> None:
    r = authed_client.post(
        "/trace",
        json=_trace_payload(),
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert r.status_code == 401


def test_post_trace_missing_auth_header_returns_401(authed_client: TestClient) -> None:
    r = authed_client.post("/trace", json=_trace_payload())
    assert r.status_code == 401


def test_post_trace_correct_key_accepted(authed_client: TestClient) -> None:
    with patch("api.main.insert_agent_log"):
        r = authed_client.post(
            "/trace",
            json=_trace_payload(),
            headers={"Authorization": "Bearer test-secret"},
        )
    assert r.status_code == 201


# ---------------------------------------------------------------------------
# GET /agents/{agent_id}/patterns
# ---------------------------------------------------------------------------

def test_get_patterns_returns_200(client: TestClient) -> None:
    with patch("api.main.get_patterns_for_agent", return_value=[]):
        r = client.get("/agents/agent-test/patterns")
    assert r.status_code == 200
    assert r.json() == []


def test_get_patterns_returns_list(client: TestClient) -> None:
    pattern = _mock_pattern()
    with patch("api.main.get_patterns_for_agent", return_value=[pattern]):
        r = client.get("/agents/agent-test/patterns")
    body = r.json()
    assert len(body) == 1
    assert body[0]["pattern_value"] == "step_3"
    assert body[0]["failure_count"] == 8
    assert body[0]["root_cause"] == "Payment API timed out at step 3."
    assert body[0]["is_worsening"] is True


def test_get_patterns_scoped_to_agent(client: TestClient) -> None:
    """Verify get_patterns_for_agent is called with the path agent_id."""
    with patch("api.main.get_patterns_for_agent", return_value=[]) as mock_q:
        client.get("/agents/my-specific-agent/patterns")
    mock_q.assert_called_once()
    assert mock_q.call_args[0][0] == "my-specific-agent"


def test_get_patterns_auth_required(authed_client: TestClient) -> None:
    r = authed_client.get("/agents/agent-test/patterns")
    assert r.status_code == 401


def test_get_patterns_correct_key(authed_client: TestClient) -> None:
    with patch("api.main.get_patterns_for_agent", return_value=[]):
        r = authed_client.get(
            "/agents/agent-test/patterns",
            headers={"Authorization": "Bearer test-secret"},
        )
    assert r.status_code == 200
