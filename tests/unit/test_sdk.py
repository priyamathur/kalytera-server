"""
Unit tests for Kalytera SDK
Core constraint: SDK trace call must never block, never raise, never slow down the agent
"""

import pytest
import time
import requests
from unittest.mock import patch, MagicMock, AsyncMock
from concurrent.futures import ThreadPoolExecutor
import tempfile
import os

from sdk.client import trace, TraceClient


class TestSDKCoreConstraints:
    """Tests that verify the SDK never blocks the agent"""

    def test_sdk_01_trace_call_returns_immediately(self):
        """SDK-01: Trace call returns immediately (< 5ms)"""
        start_time = time.time()
        
        # Call trace with valid inputs
        trace(
            session_id="test_session",
            user_input="test input",
            agent_response="test response",
            response_time_ms=1000
        )
        
        end_time = time.time()
        duration_ms = (end_time - start_time) * 1000
        
        # Must return in under 5ms
        assert duration_ms < 5, f"trace() took {duration_ms:.2f}ms, must be < 5ms"

    def test_sdk_02_kalytera_down_agent_keeps_running(self):
        """SDK-02: Kalytera down — agent keeps running"""
        # Mock network failure
        with patch('requests.post', side_effect=requests.ConnectionError("Connection failed")):
            # This should not raise an exception
            try:
                trace(
                    session_id="test_session",
                    user_input="test input", 
                    agent_response="test response",
                    response_time_ms=1000
                )
                # Test passes if no exception is raised
            except Exception as e:
                pytest.fail(f"trace() raised exception when Kalytera is down: {e}")

    def test_sdk_03_invalid_inputs_no_exception(self):
        """SDK-03: Invalid inputs — no exception"""
        invalid_inputs = [
            # None values
            {"session_id": None, "user_input": "test", "agent_response": "test"},
            # Empty strings
            {"session_id": "", "user_input": "", "agent_response": ""},
            # Wrong types
            {"session_id": 123, "user_input": [], "agent_response": {}},
            # Missing required fields (testing kwargs)
            {}
        ]
        
        for invalid_input in invalid_inputs:
            try:
                trace(**invalid_input)
                # Test passes if no exception is raised
            except Exception as e:
                pytest.fail(f"trace() raised exception with invalid inputs {invalid_input}: {e}")

    def test_sdk_04_network_timeout_no_exception(self):
        """SDK-04: Network timeout — no exception"""
        # Mock a 30-second timeout
        with patch('requests.post', side_effect=requests.Timeout("Request timeout")):
            start_time = time.time()
            
            try:
                trace(
                    session_id="test_session",
                    user_input="test input",
                    agent_response="test response",
                    response_time_ms=1000
                )
                
                end_time = time.time()
                duration_ms = (end_time - start_time) * 1000
                
                # Must still return within 5ms even with timeout
                assert duration_ms < 5, f"trace() took {duration_ms:.2f}ms even with timeout"
                
            except Exception as e:
                pytest.fail(f"trace() raised exception on network timeout: {e}")

    def test_sdk_07_concurrent_trace_calls(self):
        """SDK-07: Concurrent trace calls"""
        def make_trace_call(i):
            trace(
                session_id=f"session_{i}",
                user_input=f"input_{i}",
                agent_response=f"response_{i}",
                response_time_ms=1000
            )
            return i
        
        # Fire 100 trace calls simultaneously
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = []
            start_time = time.time()
            
            for i in range(100):
                future = executor.submit(make_trace_call, i)
                futures.append(future)
            
            # Wait for all to complete
            results = []
            for future in futures:
                try:
                    result = future.result(timeout=1.0)  # Should complete quickly
                    results.append(result)
                except Exception as e:
                    pytest.fail(f"Concurrent trace call failed: {e}")
            
            end_time = time.time()
            total_duration = end_time - start_time
            
            # All 100 calls should complete
            assert len(results) == 100, f"Expected 100 results, got {len(results)}"
            
            # Total duration should be reasonable (all calls are async)
            assert total_duration < 2.0, f"100 concurrent calls took {total_duration:.2f}s"


class TestSDKDatabaseIntegration:
    """Tests that verify SDK writes to database correctly"""

    def setup_method(self):
        """Setup test database"""
        from api.database import get_db, engine
        from db.models import Base
        
        # Create test tables
        Base.metadata.create_all(bind=engine)
        self.db = next(get_db())

    def test_sdk_05_agentlog_written_to_db(self, monkeypatch):
        """SDK-05: trace() writes to DB via background worker"""
        with patch('sdk.client._write_trace_to_db') as mock_db_write:
            trace(
                session_id="test_session_db",
                user_input="test input for db",
                agent_response="test response for db",
                response_time_ms=1200,
                workflow_step=1,
                tool_calls='["test_tool"]'
            )
            # Give background worker thread time to dequeue and write
            time.sleep(0.3)

        assert mock_db_write.called, "trace() background worker must call _write_trace_to_db"

    def test_sdk_06_session_ended_flag_set_correctly(self):
        """SDK-06: trace() passes session_ended=True through to the background worker"""
        captured = []

        def capture_write(trace_event):
            captured.append(trace_event)

        with patch('sdk.client._write_trace_to_db', side_effect=capture_write):
            trace(
                session_id="test_session_ended",
                user_input="final input",
                agent_response="final response",
                response_time_ms=800,
                session_ended=True
            )
            time.sleep(0.3)

        assert len(captured) == 1, "background worker must call _write_trace_to_db once"
        assert captured[0].session_ended is True, "session_ended flag must be True on the TraceEvent"


class TestSDKLocalFallback:
    """Tests for local logging fallback when API is unreachable"""

    def setup_method(self):
        """Setup temporary directory for local logs"""
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        """Clean up temporary files"""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_sdk_local_fallback_when_api_down(self):
        """Test that SDK logs locally when API is unreachable"""
        # Configure client to use temp directory
        client = TraceClient(log_dir=self.temp_dir)
        
        # Mock API failure
        with patch('requests.post', side_effect=requests.ConnectionError("API down")):
            client.trace(
                session_id="offline_session",
                user_input="offline input",
                agent_response="offline response",
                response_time_ms=1500
            )
            
            # Give background thread time to write file
            time.sleep(0.1)
        
        # Check that local log file was created
        log_files = os.listdir(self.temp_dir)
        assert len(log_files) > 0, "No local log file created when API was down"
        
        # Verify log content
        log_file = os.path.join(self.temp_dir, log_files[0])
        with open(log_file, 'r') as f:
            log_content = f.read()
            assert "offline_session" in log_content
            assert "offline input" in log_content


class TestWebhookReceiver:
    """Tests for the webhook API endpoint"""

    def test_sdk_08_webhook_receiver_post_trace(self):
        """SDK-08: Webhook receiver — POST /trace with correct payload schema"""
        import uuid
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)

        payload = {
            "id": str(uuid.uuid4()),
            "agent_id": "demo-agent",
            "session_id": "webhook_test_" + str(uuid.uuid4())[:8],
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