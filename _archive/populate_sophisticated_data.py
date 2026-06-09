#!/usr/bin/env python3
"""
Populate AgentIQ with sophisticated agent data to trigger real evaluations and pattern detection
This loads realistic multi-agent conversations that will showcase the LLM evaluation engine
"""

import requests
import time
import random
from datetime import datetime, timedelta

# Use local API for faster data loading
LOCAL_API = "http://localhost:8000"

def create_sophisticated_agent_sessions():
    """Create realistic multi-agent conversations with complexity"""
    
    sessions = []
    
    # Complex customer support scenarios
    support_scenarios = [
        {
            "session_id": "support_billing_001",
            "conversations": [
                {
                    "step_name": "intent_classification",
                    "input": "I've been charged three times for the same subscription this month, this is completely unacceptable. I want a full refund immediately and I'm considering legal action.",
                    "output": "BILLING_DISPUTE - High urgency (0.98), Complex case detected. Routing to senior billing specialist with legal escalation protocol.",
                    "metadata": {"intent": "billing_dispute", "urgency": "high", "legal_mention": True, "confidence": 0.98, "escalation_needed": True}
                },
                {
                    "step_name": "senior_billing_specialist",
                    "input": "Customer has triple billing charges and mentioned legal action. Account shows charges on 3/1, 3/15, 3/28 for $149.99 each.",
                    "output": "I sincerely apologize for this error. I've identified the system glitch that caused triple billing. Processing immediate refund of $299.98 (2 charges) plus $50 account credit for the inconvenience. Legal escalation cancelled.",
                    "metadata": {"charges_found": 3, "refund_amount": 299.98, "credit_issued": 50, "legal_risk": "resolved", "resolution_time_minutes": 8}
                },
                {
                    "step_name": "quality_assurance",
                    "input": "Review resolution: Triple billing, $299.98 refund + $50 credit, customer satisfaction expected?",
                    "output": "Resolution appropriate. Customer likely satisfied with immediate action and goodwill credit. Recommend follow-up email in 24 hours to confirm resolution.",
                    "metadata": {"resolution_quality": "excellent", "customer_satisfaction_predicted": 0.91, "follow_up_recommended": True}
                }
            ]
        },
        {
            "session_id": "support_technical_001", 
            "conversations": [
                {
                    "step_name": "technical_triage",
                    "input": "Our entire webhook system stopped working 2 hours ago. We're losing critical order data and this is affecting our business operations. We need immediate assistance.",
                    "output": "CRITICAL_TECHNICAL_ISSUE detected. Webhook system outage confirmed. Escalating to senior technical team with P1 priority. ETA for resolution: 30 minutes.",
                    "metadata": {"severity": "critical", "issue_type": "webhook_outage", "business_impact": "high", "sla_breach_risk": True, "eta_minutes": 30}
                },
                {
                    "step_name": "senior_technical_specialist",
                    "input": "P1 webhook outage - customer losing order data. System status shows API gateway issues starting 14:23 UTC.",
                    "output": "Root cause identified: API gateway configuration rollback needed. Implementing fix now. Customer webhooks should resume within 10 minutes. Will provide detailed incident report.",
                    "metadata": {"root_cause": "api_gateway_config", "fix_eta_minutes": 10, "incident_report_promised": True, "technical_debt_identified": True}
                },
                {
                    "step_name": "incident_resolution",
                    "input": "Webhook fix deployed, customer systems testing. Need to confirm resolution and provide incident analysis.",
                    "output": "Webhook system restored. Customer confirmed order data flowing correctly. Incident duration: 2.5 hours. Implementing additional monitoring to prevent recurrence.",
                    "metadata": {"resolution_confirmed": True, "incident_duration_hours": 2.5, "preventive_measures_added": True, "customer_satisfaction": 0.78}
                }
            ]
        },
        {
            "session_id": "sales_enterprise_001",
            "conversations": [
                {
                    "step_name": "lead_qualification",
                    "input": "Hi, I'm the VP of Engineering at TechCorp. We have 500 engineers building AI agents and need enterprise-grade monitoring. What can you offer?",
                    "output": "Excellent fit for AgentIQ Enterprise. For 500 engineers, I recommend our Enterprise Pro plan with unlimited agents, advanced analytics, and dedicated support. Estimated value: $15K/month.",
                    "metadata": {"company_size": 500, "prospect_title": "VP Engineering", "use_case": "AI agents", "deal_size_estimated": 15000, "qualification_score": 0.96}
                },
                {
                    "step_name": "technical_discovery", 
                    "input": "We're using LangChain, AutoGPT, and custom agents. Need integration examples and technical architecture review.",
                    "output": "Perfect! AgentIQ supports all those frameworks. I'll arrange a technical deep-dive with our solution architect. We have pre-built LangChain integrations and AutoGPT monitoring templates.",
                    "metadata": {"frameworks": ["LangChain", "AutoGPT", "custom"], "technical_fit": "excellent", "demo_scheduled": True, "solution_architect_assigned": True}
                },
                {
                    "step_name": "proposal_generation",
                    "input": "Generate enterprise proposal: 500 users, LangChain/AutoGPT integration, custom analytics dashboard, 24/7 support.",
                    "output": "Enterprise proposal generated: $12K/month (20% volume discount), includes unlimited agent monitoring, custom dashboards, dedicated customer success manager, and priority support.",
                    "metadata": {"monthly_value": 12000, "discount_applied": 0.20, "contract_term": "annual", "success_manager_included": True, "close_probability": 0.85}
                }
            ]
        },
        {
            "session_id": "support_failed_001",
            "conversations": [
                {
                    "step_name": "password_reset_attempt",
                    "input": "I can't log into my account. The password reset isn't working and I've tried multiple times.",
                    "output": "Let me help with that password reset. I'll send a new reset link to your email ending in ...@gmail.com",
                    "metadata": {"issue_type": "password_reset", "previous_attempts": 3, "email_masked": True}
                },
                {
                    "step_name": "email_system_failure",
                    "input": "Send password reset email to user account",
                    "output": "ERROR: Email service timeout after 30 seconds. Unable to send password reset email. Alternative verification required.",
                    "metadata": {"success": False, "error_type": "email_timeout", "service_down": "email_system", "fallback_needed": True}
                },
                {
                    "step_name": "manual_resolution_failure",
                    "input": "Email system down, attempt manual account verification via phone",
                    "output": "Phone verification system also experiencing issues. Unable to complete account access request. Customer will need to submit support ticket for manual review.",
                    "metadata": {"success": False, "error_type": "multiple_system_failure", "resolution": "manual_ticket_required", "customer_experience": "poor"}
                }
            ]
        }
    ]
    
    return support_scenarios

def load_data_to_agentiq(sessions, api_url):
    """Load sophisticated session data to AgentIQ"""
    
    print("📊 Loading Sophisticated Agent Data to AgentIQ")
    print(f"🌐 API: {api_url}")
    print("=" * 60)
    
    total_interactions = 0
    successful_loads = 0
    
    for session in sessions:
        session_id = session["session_id"]
        conversations = session["conversations"]
        
        print(f"\n🎯 Loading Session: {session_id}")
        print(f"   📝 Conversations: {len(conversations)}")
        
        # Convert to AgentIQ format
        agentiq_data = {
            "data": [],
            "source": "sophisticated_demo_system"
        }
        
        for conv in conversations:
            interaction = {
                "session_id": session_id,
                "step_name": conv["step_name"],
                "input": conv["input"],
                "output": conv["output"],
                "metadata": {
                    "timestamp": (datetime.now() - timedelta(hours=random.randint(1, 24))).isoformat(),
                    **conv["metadata"]
                }
            }
            agentiq_data["data"].append(interaction)
            total_interactions += 1
        
        # Send to AgentIQ
        try:
            response = requests.post(f"{api_url}/ingest/json", json=agentiq_data, timeout=15)
            if response.status_code == 200:
                result = response.json()
                print(f"   ✅ Loaded: {result.get('interactions_processed', 0)} interactions")
                successful_loads += 1
            else:
                print(f"   ❌ Failed: HTTP {response.status_code}")
        except Exception as e:
            print(f"   ❌ Error: {str(e)}")
        
        time.sleep(0.5)  # Rate limiting
    
    return total_interactions, successful_loads

def trigger_evaluations(api_url):
    """Trigger LLM evaluations on the loaded data"""
    
    print("\n🧠 Triggering LLM Evaluations")
    print("=" * 40)
    
    try:
        # Trigger evaluation batch processing
        response = requests.post(f"{api_url}/evaluation/batch-evaluate", timeout=60)
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Evaluations triggered: {result.get('message', 'Success')}")
            return True
        else:
            print(f"❌ Evaluation trigger failed: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Evaluation error: {str(e)}")
        return False

def check_pattern_detection(api_url):
    """Check if pattern detection algorithms found insights"""
    
    print("\n🔍 Checking Pattern Detection Results")
    print("=" * 45)
    
    endpoints = [
        ("/patterns/insights/top-intents", "Intent Patterns"),
        ("/patterns/insights/failure-analysis", "Failure Patterns"), 
        ("/analytics/dashboard-summary", "Analytics Summary")
    ]
    
    for endpoint, name in endpoints:
        try:
            response = requests.get(f"{api_url}{endpoint}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                print(f"✅ {name}: Available")
                
                if endpoint == "/patterns/insights/top-intents":
                    patterns = data.get("total_intent_patterns", 0)
                    print(f"   📊 Intent patterns detected: {patterns}")
                    
                elif endpoint == "/patterns/insights/failure-analysis":
                    failures = data.get("total_failure_patterns", 0)
                    print(f"   ❌ Failure patterns detected: {failures}")
                    
                elif endpoint == "/analytics/dashboard-summary":
                    sessions = data.get("total_sessions", 0)
                    print(f"   📈 Sessions analyzed: {sessions}")
                    
            else:
                print(f"❌ {name}: HTTP {response.status_code}")
        except Exception as e:
            print(f"❌ {name}: {str(e)}")

def main():
    """Load sophisticated data and trigger advanced analytics"""
    
    print("🚀 AgentIQ Sophisticated Data Population")
    print("GOAL: Trigger real LLM evaluations and pattern detection")
    print("=" * 70)
    
    # Create sophisticated session data
    sessions = create_sophisticated_agent_sessions()
    print(f"📋 Created {len(sessions)} sophisticated agent sessions")
    
    # Try local API first, fallback to production
    api_urls = [LOCAL_API, "https://agentiq-api-z9it.onrender.com"]
    
    for api_url in api_urls:
        print(f"\n🔗 Trying API: {api_url}")
        
        # Test health
        try:
            health = requests.get(f"{api_url}/health", timeout=5)
            if health.status_code == 200:
                print("✅ API healthy, proceeding with data load")
                
                # Load sophisticated data
                total_interactions, successful_loads = load_data_to_agentiq(sessions, api_url)
                
                print("\n📊 Data Load Summary:")
                print(f"   💬 Total interactions: {total_interactions}")
                print(f"   ✅ Sessions loaded: {successful_loads}/{len(sessions)}")
                
                if successful_loads > 0:
                    # Wait for processing
                    print("\n⏳ Waiting for AgentIQ processing...")
                    time.sleep(5)
                    
                    # Trigger evaluations
                    evaluations_triggered = trigger_evaluations(api_url)
                    
                    # Check patterns
                    check_pattern_detection(api_url)
                    
                    if api_url == LOCAL_API:
                        print("\n🎉 SUCCESS! Sophisticated data loaded to local AgentIQ")
                        print("📊 Open Streamlit dashboard: http://localhost:8501")
                        print("🧠 View real LLM evaluations and pattern detection")
                    
                    break
                    
        except Exception as e:
            print(f"❌ API {api_url} not available: {str(e)}")
            continue
    
    print("\n✨ Sophisticated AgentIQ demonstration ready!")
    print("🔗 Features now active:")
    print("   ✅ Multi-agent conversation analysis")
    print("   ✅ LLM-powered evaluation engine") 
    print("   ✅ Advanced pattern detection")
    print("   ✅ Real-time analytics dashboard")

if __name__ == "__main__":
    main()