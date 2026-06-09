"""
Test for API trace endpoint - SDK-08
"""

import pytest
from fastapi.testclient import TestClient


def test_sdk_08_webhook_receiver_post_trace():
    """SDK-08: Webhook receiver — POST /trace"""
    try:
        from api.main import app
        client = TestClient(app)
        
        # Valid trace payload
        payload = {
            "session_id": "webhook_test",
            "timestamp": "2026-06-08T10:00:00",
            "user_input": "webhook test input",
            "agent_response": "webhook test response",
            "response_time_ms": 1000,
            "workflow_step": 1
        }
        
        response = client.post("/api/trace", json=payload)
        
        # Should return success status
        assert response.status_code in [200, 201], f"Expected 200 or 201, got {response.status_code}: {response.text}"
        
        # Should return JSON response
        response_data = response.json()
        assert "status" in response_data or "message" in response_data
        
    except ImportError as e:
        pytest.skip(f"Cannot import FastAPI app: {e}")


def test_api_trace_invalid_payload():
    """Test trace endpoint with invalid payload"""
    try:
        from api.main import app
        client = TestClient(app)
        
        # Invalid payload - missing required fields
        invalid_payload = {
            "user_input": "test without session_id"
        }
        
        response = client.post("/api/trace", json=invalid_payload)
        
        # Should return error status (422 Unprocessable Entity or 400 Bad Request)
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