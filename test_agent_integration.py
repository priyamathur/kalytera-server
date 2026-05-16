#!/usr/bin/env python3
"""
AgentIQ Integration Test - Simulating Real Agent Orchestration
Tests both single agents and multi-agent systems with AgentIQ monitoring
"""

import requests
import json
import time
from datetime import datetime
from typing import List, Dict, Any

# Your production AgentIQ endpoint
AGENTIQ_URL = "https://agentiq-api-z9it.onrender.com"

class AgentIQClient:
    """Client for integrating with AgentIQ platform"""
    
    def __init__(self, base_url: str):
        self.base_url = base_url
    
    def log_interaction(self, session_id: str, agent_name: str, step_name: str, 
                       user_input: str, agent_output: str, metadata: Dict = None):
        """Log a single agent interaction to AgentIQ"""
        data = {
            "data": [{
                "session_id": session_id,
                "step_name": f"{agent_name}:{step_name}",
                "input": user_input,
                "output": agent_output,
                "metadata": {
                    "agent_name": agent_name,
                    "timestamp": datetime.now().isoformat(),
                    **(metadata or {})
                }
            }],
            "source": "multi_agent_system"
        }
        
        response = requests.post(f"{self.base_url}/ingest/json", json=data)
        return response.json()

# Initialize AgentIQ client
agentiq = AgentIQClient(AGENTIQ_URL)

def simulate_customer_support_workflow():
    """Simulate a multi-agent customer support system"""
    
    session_id = f"support_session_{int(time.time())}"
    print(f"🎯 Starting Customer Support Session: {session_id}")
    
    # Agent 1: Intent Classifier
    user_query = "I was charged twice for my premium subscription this month and need a refund"
    
    intent_result = agentiq.log_interaction(
        session_id=session_id,
        agent_name="intent_classifier",
        step_name="classify_intent",
        user_input=user_query,
        agent_output="BILLING_DISPUTE - High confidence (0.94). Routed to billing specialist.",
        metadata={
            "intent": "billing_dispute",
            "confidence": 0.94,
            "routing_decision": "billing_specialist"
        }
    )
    print(f"✅ Intent Classification logged: {intent_result['success']}")
    
    time.sleep(1)
    
    # Agent 2: Billing Specialist Agent
    billing_result = agentiq.log_interaction(
        session_id=session_id,
        agent_name="billing_specialist", 
        step_name="investigate_duplicate_charge",
        user_input="Investigate duplicate charge for user account",
        agent_output="Found duplicate charge on March 15th for $29.99. Charge ID: ch_abc123. Initiating refund process.",
        metadata={
            "charge_found": True,
            "charge_id": "ch_abc123", 
            "amount": 29.99,
            "duplicate_date": "2024-03-15"
        }
    )
    print(f"✅ Billing Investigation logged: {billing_result['success']}")
    
    time.sleep(1)
    
    # Agent 3: Refund Processor
    refund_result = agentiq.log_interaction(
        session_id=session_id,
        agent_name="refund_processor",
        step_name="process_refund",
        user_input="Process refund for charge ch_abc123 amount $29.99",
        agent_output="Refund processed successfully. Refund ID: rf_xyz789. Customer will see credit in 3-5 business days.",
        metadata={
            "refund_id": "rf_xyz789",
            "refund_amount": 29.99,
            "processing_time_ms": 2300,
            "success": True
        }
    )
    print(f"✅ Refund Processing logged: {refund_result['success']}")
    
    time.sleep(1)
    
    # Agent 4: Communication Agent
    communication_result = agentiq.log_interaction(
        session_id=session_id,
        agent_name="communication_agent",
        step_name="send_confirmation",
        user_input="Send refund confirmation to customer",
        agent_output="Hi! I've found the duplicate charge from March 15th and processed a $29.99 refund (ID: rf_xyz789). You'll see the credit in 3-5 business days. Is there anything else I can help with?",
        metadata={
            "communication_type": "refund_confirmation",
            "customer_satisfaction_predicted": 0.89,
            "issue_resolved": True
        }
    )
    print(f"✅ Customer Communication logged: {communication_result['success']}")
    
    return session_id

def simulate_sales_agent_workflow():
    """Simulate a multi-agent sales system"""
    
    session_id = f"sales_session_{int(time.time())}"
    print(f"\n💼 Starting Sales Agent Session: {session_id}")
    
    # Agent 1: Lead Qualifier
    user_input = "I'm interested in your enterprise plan for my 50-person engineering team"
    
    qualifier_result = agentiq.log_interaction(
        session_id=session_id,
        agent_name="lead_qualifier",
        step_name="qualify_lead",
        user_input=user_input,
        agent_output="QUALIFIED LEAD - Enterprise prospect, 50 engineers, technical team. High value potential. Routing to enterprise sales specialist.",
        metadata={
            "lead_score": 0.92,
            "team_size": 50,
            "plan_interest": "enterprise",
            "qualification": "qualified"
        }
    )
    print(f"✅ Lead Qualification logged: {qualifier_result['success']}")
    
    time.sleep(1)
    
    # Agent 2: Product Specialist
    product_result = agentiq.log_interaction(
        session_id=session_id,
        agent_name="product_specialist",
        step_name="recommend_solution",
        user_input="Recommend best enterprise solution for 50-person engineering team",
        agent_output="For your team size, I recommend our Enterprise Pro plan with advanced analytics, priority support, and custom integrations. This includes unlimited projects and 24/7 support.",
        metadata={
            "recommended_plan": "enterprise_pro",
            "monthly_value": 4999,
            "features_highlighted": ["analytics", "support", "integrations"]
        }
    )
    print(f"✅ Product Recommendation logged: {product_result['success']}")
    
    time.sleep(1)
    
    # Agent 3: Pricing Agent  
    pricing_result = agentiq.log_interaction(
        session_id=session_id,
        agent_name="pricing_agent",
        step_name="calculate_custom_pricing",
        user_input="Calculate pricing for Enterprise Pro, 50 users",
        agent_output="Based on your team size, Enterprise Pro would be $4,999/month. For annual payment, I can offer 20% discount = $3,999/month. Includes all premium features plus dedicated success manager.",
        metadata={
            "base_price": 4999,
            "discounted_price": 3999,
            "discount_percent": 20,
            "payment_term": "annual"
        }
    )
    print(f"✅ Custom Pricing logged: {pricing_result['success']}")
    
    return session_id

def simulate_failed_interaction():
    """Simulate a failed agent interaction for testing error patterns"""
    
    session_id = f"failed_session_{int(time.time())}"
    print(f"\n❌ Simulating Failed Interaction: {session_id}")
    
    # Failed tool usage
    failed_result = agentiq.log_interaction(
        session_id=session_id,
        agent_name="payment_processor",
        step_name="process_payment",
        user_input="Process payment for order #12345",
        agent_output="ERROR: Payment gateway timeout after 30 seconds. Please try again later.",
        metadata={
            "error_type": "gateway_timeout", 
            "success": False,
            "error_code": "PAYMENT_GATEWAY_TIMEOUT",
            "retry_recommended": True
        }
    )
    print(f"✅ Failed Interaction logged: {failed_result['success']}")
    
    return session_id

def test_analytics_after_integration():
    """Test AgentIQ analytics after simulating agent workflows"""
    
    print(f"\n📊 Testing AgentIQ Analytics...")
    
    # Test health endpoint
    health = requests.get(f"{AGENTIQ_URL}/health").json()
    print(f"🏥 Health Status: {health['status']}")
    
    # Test pattern analysis
    patterns = requests.get(f"{AGENTIQ_URL}/patterns/insights/top-intents").json()
    print(f"🎯 Intent Patterns Found: {patterns['total_intent_patterns']}")
    
    # Test database status
    db_status = requests.get(f"{AGENTIQ_URL}/admin/database-status").json()
    print(f"💾 Database Tables: {len(db_status['existing_tables'])}")
    
    return True

def main():
    """Run complete AgentIQ integration test"""
    
    print("🚀 AgentIQ Multi-Agent System Integration Test")
    print("=" * 60)
    
    # Test 1: Customer Support Multi-Agent Workflow
    support_session = simulate_customer_support_workflow()
    
    # Test 2: Sales Multi-Agent Workflow  
    sales_session = simulate_sales_agent_workflow()
    
    # Test 3: Error Handling
    failed_session = simulate_failed_interaction()
    
    # Test 4: Analytics and Insights
    analytics_working = test_analytics_after_integration()
    
    print(f"\n🎉 Integration Test Complete!")
    print("=" * 60)
    print(f"✅ Customer Support Session: {support_session}")
    print(f"✅ Sales Agent Session: {sales_session}")
    print(f"✅ Error Scenario Session: {failed_session}")
    print(f"✅ Analytics Status: {'Working' if analytics_working else 'Issues'}")
    print(f"\n🌐 View results at: {AGENTIQ_URL}/docs")
    print(f"📊 Check patterns at: {AGENTIQ_URL}/patterns/insights/top-intents")

if __name__ == "__main__":
    main()