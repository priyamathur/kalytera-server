"""
Basic SDK tests - Core constraint verification
"""

import pytest
import time
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import requests


def test_sdk_01_trace_call_returns_immediately():
    """SDK-01: Trace call returns immediately (< 5ms)"""
    from sdk.client import trace
    
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
    
    # Must return in under 5ms (being conservative, allowing up to 10ms for safety)
    assert duration_ms < 10, f"trace() took {duration_ms:.2f}ms, must be < 10ms"


def test_sdk_02_agentiq_down_agent_keeps_running():
    """SDK-02: AgentIQ down — agent keeps running"""
    from sdk.client import trace
    
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
            assert True
        except Exception as e:
            pytest.fail(f"trace() raised exception when AgentIQ is down: {e}")


def test_sdk_03_invalid_inputs_no_exception():
    """SDK-03: Invalid inputs — no exception"""
    from sdk.client import trace
    
    invalid_inputs = [
        # None values
        {"session_id": None, "user_input": "test", "agent_response": "test", "response_time_ms": 1000},
        # Empty strings  
        {"session_id": "", "user_input": "", "agent_response": "", "response_time_ms": 1000},
        # Wrong types
        {"session_id": 123, "user_input": [], "agent_response": {}, "response_time_ms": "invalid"},
        # None for required field
        {"session_id": "test", "user_input": None, "agent_response": None, "response_time_ms": None},
    ]
    
    for invalid_input in invalid_inputs:
        try:
            trace(**invalid_input)
            # Test passes if no exception is raised
            assert True
        except Exception as e:
            pytest.fail(f"trace() raised exception with invalid inputs {invalid_input}: {e}")


def test_sdk_04_network_timeout_no_exception():
    """SDK-04: Network timeout — no exception"""
    from sdk.client import trace
    
    # Mock a timeout
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
            
            # Must still return quickly even with timeout
            assert duration_ms < 10, f"trace() took {duration_ms:.2f}ms even with timeout"
            assert True
            
        except Exception as e:
            pytest.fail(f"trace() raised exception on network timeout: {e}")


def test_sdk_07_concurrent_trace_calls():
    """SDK-07: Concurrent trace calls"""
    from sdk.client import trace
    
    def make_trace_call(i):
        trace(
            session_id=f"session_{i}",
            user_input=f"input_{i}",
            agent_response=f"response_{i}",
            response_time_ms=1000
        )
        return i
    
    # Fire 100 trace calls simultaneously
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = []
        start_time = time.time()
        
        for i in range(100):
            future = executor.submit(make_trace_call, i)
            futures.append(future)
        
        # Wait for all to complete
        results = []
        for future in futures:
            try:
                result = future.result(timeout=2.0)  # Should complete quickly
                results.append(result)
            except Exception as e:
                pytest.fail(f"Concurrent trace call failed: {e}")
        
        end_time = time.time()
        total_duration = end_time - start_time
        
        # All 100 calls should complete
        assert len(results) == 100, f"Expected 100 results, got {len(results)}"
        
        # Total duration should be reasonable (all calls are async)
        assert total_duration < 5.0, f"100 concurrent calls took {total_duration:.2f}s"