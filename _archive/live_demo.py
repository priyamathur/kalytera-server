#!/usr/bin/env python3
"""
AgentIQ Live Demo - Populate with realistic data and show visualization
This simulates a real agent system sending data to AgentIQ for monitoring
"""

import requests
import time
import random
from datetime import datetime
from typing import List, Dict, Any

# Production AgentIQ API
AGENTIQ_URL = "https://agentiq-api-z9it.onrender.com"
LOCAL_DASHBOARD = "http://localhost:8501"

def create_realistic_agent_interaction(session_type: str, step_num: int = 1) -> Dict[str, Any]:
    """Create realistic agent interaction data"""
    
    if session_type == "customer_support":
        scenarios = [
            {
                "input": "I can't access my account, it says my password is wrong",
                "output": "I can help you reset your password. I'll send a reset link to your email address ending in @gmail.com",
                "metadata": {"intent": "account_access", "successful": True, "resolution_time_s": 45}
            },
            {
                "input": "I was charged twice for my monthly subscription",
                "output": "I see the duplicate charge from March 15th for $29.99. I've initiated a refund that will appear in 3-5 business days.",
                "metadata": {"intent": "billing_dispute", "successful": True, "refund_amount": 29.99}
            },
            {
                "input": "How do I cancel my subscription?",
                "output": "I can help you cancel. Before I do that, may I ask what's prompting this decision? We might have options to help.",
                "metadata": {"intent": "cancellation", "successful": False, "retention_attempt": True}
            }
        ]
    
    elif session_type == "sales":
        scenarios = [
            {
                "input": "What's your enterprise pricing for a 100-person team?",
                "output": "For 100 users, our Enterprise plan is $199/month per user, but I can offer volume discounts starting at 15% for annual contracts.",
                "metadata": {"intent": "pricing_inquiry", "successful": True, "team_size": 100, "potential_value": 19900}
            },
            {
                "input": "Do you have API integrations with Salesforce?",
                "output": "Yes! We have native Salesforce integration plus REST APIs. I can set up a demo to show you exactly how it works with your setup.",
                "metadata": {"intent": "technical_integration", "successful": True, "demo_scheduled": True}
            }
        ]
    
    else:  # technical_support
        scenarios = [
            {
                "input": "Our API is returning 500 errors for the /users endpoint",
                "output": "I see elevated error rates on that endpoint. Let me check our system status... There's a known issue being resolved. ETA 15 minutes.",
                "metadata": {"intent": "api_error", "successful": True, "error_type": "500", "eta_minutes": 15}
            },
            {
                "input": "The webhook isn't triggering when orders are created",
                "output": "Let me verify your webhook configuration. I see the endpoint URL is responding with 404. Could you check the URL?",
                "metadata": {"intent": "webhook_issue", "successful": False, "debug_required": True}
            }
        ]
    
    scenario = random.choice(scenarios)
    return {
        "session_id": f"{session_type}_{int(time.time())}_{step_num}",
        "step_name": f"{session_type}_agent_response",
        "input": scenario["input"],
        "output": scenario["output"],
        "metadata": {
            "agent_type": session_type,
            "timestamp": datetime.now().isoformat(),
            "step_number": step_num,
            **scenario["metadata"]
        }
    }

def send_agent_data_to_agentiq(interactions: List[Dict[str, Any]]):
    """Send agent interaction data to AgentIQ"""
    
    payload = {
        "data": interactions,
        "source": "live_demo_system"
    }
    
    try:
        response = requests.post(f"{AGENTIQ_URL}/ingest/json", json=payload, timeout=10)
        if response.status_code == 200:
            result = response.json()
            return True, result
        else:
            return False, f"HTTP {response.status_code}"
    except Exception as e:
        return False, str(e)

def simulate_live_agent_system():
    """Simulate a live multi-agent system sending data to AgentIQ"""
    
    print("🤖 AgentIQ Live Demo - Simulating Real Agent System")
    print("=" * 60)
    print(f"📡 Sending data to: {AGENTIQ_URL}")
    print(f"📊 Dashboard available at: {LOCAL_DASHBOARD}")
    print(f"🌐 Production dashboard: {AGENTIQ_URL}/docs")
    print()
    
    # Simulate different agent types
    agent_types = ["customer_support", "sales", "technical_support"]
    
    for round_num in range(3):
        print(f"📈 Round {round_num + 1}: Generating agent interactions...")
        
        # Create batch of interactions
        interactions = []
        for agent_type in agent_types:
            for step in range(2):  # 2 steps per agent type
                interaction = create_realistic_agent_interaction(agent_type, step + 1)
                interactions.append(interaction)
                print(f"   ✅ {agent_type}: {interaction['input'][:50]}...")
        
        # Send to AgentIQ
        success, result = send_agent_data_to_agentiq(interactions)
        
        if success:
            print(f"   📤 Sent {len(interactions)} interactions successfully")
            print(f"   📊 Sessions processed: {result.get('sessions_processed', 0)}")
        else:
            print(f"   ❌ Failed to send data: {result}")
        
        print()
        
        # Wait between rounds
        if round_num < 2:
            print("⏳ Waiting 3 seconds for next round...")
            time.sleep(3)
    
    return True

def check_dashboard_data():
    """Check what data is available for dashboard"""
    
    print("📊 Checking AgentIQ Dashboard Data...")
    
    endpoints = [
        ("/health", "System Health"),
        ("/admin/database-status", "Database Status"),
        ("/patterns/insights/top-intents", "Intent Patterns")
    ]
    
    for endpoint, description in endpoints:
        try:
            response = requests.get(f"{AGENTIQ_URL}{endpoint}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                print(f"✅ {description}: Working")
                
                if endpoint == "/admin/database-status":
                    print(f"   📋 Tables: {', '.join(data.get('existing_tables', []))}")
                elif endpoint == "/patterns/insights/top-intents":
                    print(f"   🎯 Intent patterns: {data.get('total_intent_patterns', 0)}")
            else:
                print(f"❌ {description}: HTTP {response.status_code}")
        except Exception as e:
            print(f"❌ {description}: {str(e)}")
    
    print()

def show_dashboard_instructions():
    """Show instructions for viewing the dashboard"""
    
    print("🎯 How to View AgentIQ Visualizations:")
    print("=" * 50)
    print()
    
    print("1. 📊 LOCAL DASHBOARD (Streamlit):")
    print(f"   Open: {LOCAL_DASHBOARD}")
    print("   - Real-time charts and analytics")
    print("   - Interactive data visualization")
    print("   - Local data processing")
    print()
    
    print("2. 🌐 PRODUCTION API DOCUMENTATION:")
    print(f"   Open: {AGENTIQ_URL}/docs")
    print("   - Interactive API testing")
    print("   - Live endpoint exploration")
    print("   - Real-time data inspection")
    print()
    
    print("3. 🔍 RAW DATA ENDPOINTS:")
    print(f"   Health: {AGENTIQ_URL}/health")
    print(f"   Analytics: {AGENTIQ_URL}/analytics/dashboard-summary")
    print(f"   Patterns: {AGENTIQ_URL}/patterns/insights/top-intents")
    print()
    
    print("4. 📱 INTEGRATION TESTING:")
    print("   - Use the SDK examples from agentiq_sdk_example.py")
    print("   - Send your own agent data via JSON API")
    print("   - Monitor multi-agent workflows in real-time")

def main():
    """Run the complete live demonstration"""
    
    # Step 1: Simulate live agent system
    simulate_live_agent_system()
    
    # Step 2: Check dashboard data
    check_dashboard_data()
    
    # Step 3: Show how to visualize
    show_dashboard_instructions()
    
    print("🎉 Live Demo Complete!")
    print("=" * 50)
    print("🔗 Your AgentIQ system is now populated with realistic data")
    print(f"📊 Open {LOCAL_DASHBOARD} to see the visualizations")
    print(f"🌐 Or visit {AGENTIQ_URL}/docs for API exploration")
    print()
    print("💡 Next Steps:")
    print("   1. Open the Streamlit dashboard to see charts")
    print("   2. Try the API endpoints in your browser")  
    print("   3. Integrate AgentIQ into your own agent system")

if __name__ == "__main__":
    main()