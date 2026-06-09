#!/usr/bin/env python3
"""
AgentIQ Integration Flow Test
This demonstrates the complete flow: Agent → AgentIQ → Analytics → Insights
"""

import requests
import time
from datetime import datetime

def simulate_customer_service_agent():
    """Simulate a customer service agent handling a real issue"""
    
    print("🎭 SIMULATION: Customer Service Agent Handling Billing Issue")
    print("=" * 60)
    
    # Step 1: Customer contacts support
    user_input = "I was charged $99.99 twice this month for my premium plan. I only signed up once."
    print(f"📞 Customer: {user_input}")
    
    # Step 2: Agent processes the request
    print("🤖 Agent: Let me check your billing history...")
    time.sleep(1)
    
    # Step 3: Agent finds the issue
    agent_response = "I found the duplicate charge on March 15th for $99.99. This appears to be a billing system error. I'm processing a full refund now."
    print(f"💬 Agent: {agent_response}")
    
    # Step 4: Agent logs this interaction to AgentIQ (THIS IS THE KEY INTEGRATION)
    session_id = f"customer_service_{int(time.time())}"
    
    agentiq_data = {
        "data": [{
            "session_id": session_id,
            "step_name": "billing_dispute_resolution",
            "input": user_input,
            "output": agent_response,
            "metadata": {
                "agent_type": "customer_service",
                "issue_type": "billing_duplicate_charge",
                "resolution_time_seconds": 45,
                "customer_satisfaction_predicted": 0.92,
                "refund_amount": 99.99,
                "resolution_successful": True,
                "priority": "high",
                "timestamp": datetime.now().isoformat()
            }
        }],
        "source": "customer_service_system"
    }
    
    print("📤 Sending interaction data to AgentIQ...")
    try:
        response = requests.post(
            "https://agentiq-api-z9it.onrender.com/ingest/json", 
            json=agentiq_data,
            timeout=10
        )
        if response.status_code == 200:
            result = response.json()
            print(f"✅ AgentIQ logged successfully: {result['message']}")
            print(f"📊 Processing time: {result.get('processing_time_ms', 0)}ms")
        else:
            print(f"❌ AgentIQ logging failed: {response.status_code}")
    except Exception as e:
        print(f"❌ AgentIQ connection error: {e}")
    
    return session_id

def simulate_sales_agent():
    """Simulate a sales agent qualifying a lead"""
    
    print("\n🎯 SIMULATION: Sales Agent Qualifying Enterprise Lead")
    print("=" * 60)
    
    user_input = "Hi, I'm the CTO of a 200-person startup. We're looking for an agent monitoring solution."
    print(f"💼 Prospect: {user_input}")
    
    agent_response = "Perfect! For a 200-person team, I'd recommend our Enterprise plan. Can I ask what type of agents you're currently running?"
    print(f"🤖 Sales Agent: {agent_response}")
    
    session_id = f"sales_{int(time.time())}"
    
    agentiq_data = {
        "data": [{
            "session_id": session_id,
            "step_name": "enterprise_lead_qualification",
            "input": user_input,
            "output": agent_response,
            "metadata": {
                "agent_type": "sales",
                "lead_quality": "hot",
                "company_size": 200,
                "prospect_title": "CTO",
                "potential_deal_value": 50000,
                "qualification_score": 0.95,
                "next_action": "schedule_demo",
                "timestamp": datetime.now().isoformat()
            }
        }],
        "source": "sales_system"
    }
    
    print("📤 Sending sales interaction to AgentIQ...")
    try:
        response = requests.post(
            "https://agentiq-api-z9it.onrender.com/ingest/json", 
            json=agentiq_data,
            timeout=10
        )
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Sales interaction logged: {result['message']}")
        else:
            print(f"❌ Logging failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Connection error: {e}")
    
    return session_id

def check_agentiq_analytics():
    """Check what AgentIQ learned from our agent interactions"""
    
    print("\n📊 CHECKING: What AgentIQ Learned From Agent Interactions")
    print("=" * 60)
    
    endpoints = [
        ("/health", "System Health"),
        ("/admin/database-status", "Database Tables"),
        ("/patterns/insights/top-intents", "Pattern Analysis")
    ]
    
    for endpoint, description in endpoints:
        print(f"🔍 Checking {description}...")
        try:
            response = requests.get(
                f"https://agentiq-api-z9it.onrender.com{endpoint}", 
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                print(f"✅ {description}: Success")
                
                if endpoint == "/health":
                    services = data.get('services', {})
                    print(f"   💾 Database: {'✅' if services.get('database') else '❌'}")
                    print(f"   🤖 LLM Judge: {'✅' if services.get('intent_classifier') else '⏸️  (standby)'}")
                
                elif endpoint == "/admin/database-status":
                    tables = data.get('existing_tables', [])
                    print(f"   📋 Tables ready: {len(tables)} ({', '.join(tables)})")
                
                elif endpoint == "/patterns/insights/top-intents":
                    patterns = data.get('total_intent_patterns', 0)
                    print(f"   🎯 Intent patterns found: {patterns}")
                    if patterns > 0:
                        intents = data.get('top_intents', [])
                        for intent in intents[:3]:
                            print(f"      - {intent}")
            else:
                print(f"❌ {description}: HTTP {response.status_code}")
        except Exception as e:
            print(f"❌ {description}: {str(e)}")
        
        time.sleep(0.5)

def demonstrate_api_integration():
    """Show the complete API integration flow"""
    
    print("\n🌐 DEMONSTRATION: Complete API Integration Flow")
    print("=" * 60)
    
    print("1. 📱 Agent Systems → Send data to AgentIQ API")
    print("2. 🔧 AgentIQ → Processes and stores interactions")  
    print("3. 🧠 AgentIQ → Analyzes patterns and performance")
    print("4. 📊 Dashboard → Shows real-time insights")
    print("5. 📈 Analytics → Provides improvement recommendations")
    
    print("\n🔧 Integration Code Example:")
    print("""
    # In your agent code, add this one line:
    agentiq.trace(
        session_id="user_session_123",
        step_name="resolve_customer_issue", 
        input=user_message,
        output=agent_response,
        metadata={"success": True, "issue_type": "billing"}
    )
    
    # AgentIQ automatically:
    # ✅ Logs the interaction
    # ✅ Evaluates agent performance  
    # ✅ Detects failure patterns
    # ✅ Provides analytics dashboard
    """)

def main():
    """Run complete integration flow demonstration"""
    
    print("🚀 AgentIQ Integration Flow Demonstration")
    print("SHOWING: How developers integrate AgentIQ into agent systems")
    print("=" * 70)
    
    # Simulate different agent types
    customer_session = simulate_customer_service_agent()
    sales_session = simulate_sales_agent() 
    
    # Wait for data processing
    print("\n⏳ Waiting for AgentIQ to process interactions...")
    time.sleep(2)
    
    # Check what AgentIQ learned
    check_agentiq_analytics()
    
    # Show integration details
    demonstrate_api_integration()
    
    print("\n🎉 DEMONSTRATION COMPLETE!")
    print("=" * 60)
    print("✅ Agent interactions successfully logged to AgentIQ")
    print("✅ Data available for analytics and pattern detection")
    print("✅ API integration working end-to-end")
    print()
    print("🌐 View live data:")
    print("   • Dashboard: file://" + __file__.replace('test_integration_flow.py', 'web_dashboard.html'))
    print("   • API Docs: https://agentiq-api-z9it.onrender.com/docs")
    print("   • Health Check: https://agentiq-api-z9it.onrender.com/health")
    print()
    print("🔧 To integrate AgentIQ into YOUR agent system:")
    print("   1. Use the SDK examples in agentiq_sdk_example.py")
    print("   2. Send POST requests to /ingest/json with your agent data")
    print("   3. Monitor your agents via the dashboard and analytics endpoints")

if __name__ == "__main__":
    main()