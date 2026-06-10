#!/usr/bin/env python3
"""
Test AgentIQ SDK Integration
"""

import time
import sys
sys.path.append('.')

from sdk.client import trace

def test_sdk_integration():
    """Test the SDK integration with timing"""
    
    print("🧪 Testing AgentIQ SDK Integration")
    print("=" * 50)
    
    # Test 1: Basic trace call with timing
    print("1. Testing SDK speed (should be < 5ms)...")
    start_time = time.time()
    
    trace(
        session_id="sdk_test_session_1",
        user_input="I need help with my billing",
        agent_response="I can help you with your billing questions. Let me look up your account.",
        response_time_ms=1200,
        workflow_step=1,
        tool_calls='["billing_api"]'
    )
    
    end_time = time.time()
    duration_ms = (end_time - start_time) * 1000
    
    print(f"   ✅ SDK call completed in {duration_ms:.2f}ms")
    
    if duration_ms < 5:
        print("   🎯 PASS: SDK is non-blocking (< 5ms)")
    else:
        print(f"   ⚠️  WARNING: SDK took {duration_ms:.2f}ms (should be < 5ms)")
    
    # Test 2: Multiple quick calls
    print("\n2. Testing multiple quick calls...")
    for i in range(3):
        trace(
            session_id=f"sdk_test_session_{i+2}",
            user_input=f"Test message {i+1}",
            agent_response=f"Test response {i+1}",
            response_time_ms=800 + i*100,
            workflow_step=i+1
        )
        print(f"   ✅ Call {i+1} completed")
    
    # Test 3: Test with session end
    print("\n3. Testing session end...")
    trace(
        session_id="sdk_test_complete_session",
        user_input="Thank you for your help",
        agent_response="You're welcome! Is there anything else I can help you with?",
        response_time_ms=600,
        workflow_step=2,
        session_ended=True
    )
    print("   ✅ Session end call completed")
    
    print("\n🎉 SDK Integration Test Complete!")
    print("📊 Sent 5 trace calls to AgentIQ")
    print("🔗 Check the dashboard at: http://localhost:8501")

if __name__ == "__main__":
    test_sdk_integration()