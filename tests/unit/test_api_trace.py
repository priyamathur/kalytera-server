"""
Test for API trace endpoint - SDK-08
"""

import pytest
from fastapi.testclient import TestClient


def test_sdk_08_webhook_receiver_post_trace():
    """SDK-08: Webhook receiver — POST /trace with correct payload schema"""
    import uuid
    try:
        from api.main import app
        client = TestClient(app)

        payload = {
            "id": str(uuid.uuid4()),
            "agent_id": "demo-agent",
            "session_id": "webhook_test",
            "step_number": 1,
            "step_name": "test_step",
            "input": "webhook test input",
            "output": "webhook test response",
            "timestamp": "2026-06-08T10:00:00",
        }

        response = client.post("/trace", json=payload)

        assert response.status_code in [200, 201], f"Expected 200 or 201, got {response.status_code}: {response.text}"

        response_data = response.json()
        assert "status" in response_data or "id" in response_data

    except ImportError as e:
        pytest.skip(f"Cannot import FastAPI app: {e}")


def test_api_trace_invalid_payload():
    """POST /trace with missing required fields returns 422"""
    try:
        from api.main import app
        client = TestClient(app)

        # Missing id, agent_id, session_id, step_number, step_name, output, timestamp
        invalid_payload = {
            "input": "test without required fields"
        }

        response = client.post("/trace", json=invalid_payload)

        assert response.status_code in [400, 422], f"Expected 400 or 422 for invalid payload, got {response.status_code}"

    except ImportError as e:
        pytest.skip(f"Cannot import FastAPI app: {e}")


def test_api_health_endpoint():
    """Test that API health endpoint works"""
    try:
        from api.main import app
        client = TestClient(app)
        
        response = client.get("/health")
        
        # Should return success
        assert response.status_code == 200
        
        health_data = response.json()
        assert "status" in health_data
        
    except ImportError as e:
        pytest.skip(f"Cannot import FastAPI app: {e}")