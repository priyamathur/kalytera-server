"""
Test script for the real-time AgentIQ dashboard
Demonstrates live agent performance monitoring
"""

import requests
import time

API_BASE = "https://agentiq-api-z9it.onrender.com"

def send_test_interaction(user_input, agent_response, intent, response_time_ms=1200):
    """Send a test interaction to the AgentIQ API"""
    session_id = f"test-{intent}-{int(time.time())}"
    
    test_data = {
        "data": [{
            "user_input": user_input,
            "agent_response": agent_response,
            "session_id": session_id,
            "response_time_ms": response_time_ms,
            "workflow_step": 1,
            "intent": intent,
            "tool_calls": "[]"
        }]
    }
    
    try:
        response = requests.post(f"{API_BASE}/ingest/json", json=test_data, timeout=10)
        if response.status_code == 200:
            print(f"✅ Sent {intent} interaction (response: {response_time_ms}ms)")
            return True
        else:
            print(f"❌ Failed to send {intent} interaction: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error sending {intent} interaction: {e}")
        return False

def run_real_time_test():
    """Run a series of test interactions to demonstrate real-time dashboard"""
    
    print("🚀 Starting Real-Time Dashboard Test")
    print("📍 Dashboard URL: http://localhost:8506")
    print(f"🌐 API: {API_BASE}")
    print("=" * 60)
    
    # Test interactions across different agent types
    test_cases = [
        {
            "user_input": "Debug this Python error: IndexError list index out of range",
            "agent_response": "IndexError means you're accessing a list index that doesn't exist. Check your loop bounds and use len(list) to verify the index is valid.",
            "intent": "debugging",
            "response_time_ms": 1100
        },
        {
            "user_input": "Write a React component for user authentication",
            "agent_response": "import React, { useState } from 'react';\n\nfunction AuthComponent() {\n  const [email, setEmail] = useState('');\n  const [password, setPassword] = useState('');\n  \n  return (\n    <div>\n      <input type='email' value={email} onChange={(e) => setEmail(e.target.value)} />\n      <input type='password' value={password} onChange={(e) => setPassword(e.target.value)} />\n    </div>\n  );\n}",
            "intent": "code_generation", 
            "response_time_ms": 2300
        },
        {
            "user_input": "I can't access my account, forgot my password",
            "agent_response": "I'll help you reset your password. I'm sending a password reset link to your registered email. Please check your inbox and follow the instructions.",
            "intent": "account_recovery",
            "response_time_ms": 800
        },
        {
            "user_input": "Analyze this customer data for trends",
            "agent_response": "I've analyzed your customer data and found 3 key trends: 1) 23% increase in mobile users, 2) Higher engagement on weekends, 3) Strong correlation between session length and purchases (r=0.78).",
            "intent": "data_analysis",
            "response_time_ms": 3200
        },
        {
            "user_input": "Is this lead qualified for our enterprise package?", 
            "agent_response": "Yes, this lead scores 9/10 on qualification: Company size (500+ employees), Budget confirmed ($50k+), Decision maker identified, Active project timeline (Q2). Recommend immediate sales engagement.",
            "intent": "lead_qualification",
            "response_time_ms": 1600
        }
    ]
    
    print("📊 Sending test interactions (watch dashboard for real-time updates):")
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{i}/5 - {test_case['intent']}...")
        send_test_interaction(
            test_case["user_input"],
            test_case["agent_response"], 
            test_case["intent"],
            test_case["response_time_ms"]
        )
        
        # Wait between sends to see real-time updates
        print("⏱️ Waiting 3 seconds (check dashboard for updates)...")
        time.sleep(3)
    
    print("\n" + "=" * 60)
    print("✅ Test complete! The dashboard should now show:")
    print("   📊 Updated session counts and metrics")
    print("   📈 Real-time activity timeline")
    print("   🎯 Performance analysis with live insights")
    print("   📋 Recent activity with the test interactions")
    print("\n🔗 Open http://localhost:8506 to view the real-time dashboard")

if __name__ == "__main__":
    run_real_time_test()