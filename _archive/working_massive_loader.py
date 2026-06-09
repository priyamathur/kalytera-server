"""
Working Massive Data Loader for AgentIQ
Use the exact format that worked before to load thousands of sessions
"""

import requests
import json
import time
import random

API_BASE = "https://agentiq-api-z9it.onrender.com"

def create_working_data_format():
    """Create data in the exact format that worked previously"""
    
    print("🔨 Creating data in working format...")
    
    # Agent scenarios based on what worked before
    scenarios = [
        # Customer Service Agents
        {
            "intent": "billing_support",
            "conversations": [
                {
                    "user_input": "I was charged twice for my subscription",
                    "agent_response": "I can see duplicate charges on your account. Let me process a refund for the duplicate charge.",
                    "tools": ["billing_system", "refund_processor"]
                },
                {
                    "user_input": "How do I update my payment method?", 
                    "agent_response": "You can update your payment method in account settings. Would you like me to guide you through it?",
                    "tools": ["billing_system", "account_manager"]
                },
                {
                    "user_input": "My invoice looks wrong",
                    "agent_response": "Let me review your billing history to identify any discrepancies.",
                    "tools": ["billing_system", "invoice_generator"]
                }
            ]
        },
        # Technical Support
        {
            "intent": "technical_support", 
            "conversations": [
                {
                    "user_input": "The app keeps crashing on iOS",
                    "agent_response": "This is a known issue with iOS 17.2. Please update to version 2.1.3 which fixes this crash.",
                    "tools": ["bug_tracker", "app_store"]
                },
                {
                    "user_input": "I can't login to my account",
                    "agent_response": "Let me check your account status and help reset your credentials.",
                    "tools": ["auth_system", "password_reset"]
                }
            ]
        },
        # Sales/BDR
        {
            "intent": "lead_qualification",
            "conversations": [
                {
                    "user_input": "What's your pricing for enterprise?",
                    "agent_response": "Our enterprise plans start at $500/month. Can you tell me about your team size?",
                    "tools": ["pricing_calculator", "crm_system"]
                },
                {
                    "user_input": "Do you offer custom integrations?", 
                    "agent_response": "Yes, we provide custom integrations for enterprise clients. What systems do you need?",
                    "tools": ["integration_catalog", "technical_discovery"]
                }
            ]
        },
        # Coding Assistants
        {
            "intent": "code_generation",
            "conversations": [
                {
                    "user_input": "Write a React component for authentication",
                    "agent_response": "Here's a React authentication component with hooks and proper error handling:",
                    "tools": ["code_generator", "react_docs"]
                },
                {
                    "user_input": "Fix this Python function for data processing",
                    "agent_response": "I see the issue - missing error handling. Here's the corrected version:",
                    "tools": ["code_analyzer", "python_linter"]
                }
            ]
        },
        # Data Science
        {
            "intent": "data_analysis", 
            "conversations": [
                {
                    "user_input": "Analyze customer churn patterns",
                    "agent_response": "I'll analyze your customer data to identify key churn indicators and at-risk segments.",
                    "tools": ["churn_analyzer", "customer_db", "ml_models"]
                },
                {
                    "user_input": "Create a predictive model for sales",
                    "agent_response": "I'll build a Random Forest model to predict quarterly sales with feature analysis.",
                    "tools": ["ml_framework", "feature_engineering", "sales_data"]
                }
            ]
        }
    ]
    
    # Generate sessions with unique timestamps for IDs
    all_sessions = []
    base_timestamp = int(time.time() * 1000)
    
    # Create 500 sessions with 2-4 interactions each
    for session_num in range(500):
        scenario = random.choice(scenarios)
        conversation = random.choice(scenario["conversations"])
        
        # Unique session ID with timestamp
        session_id = f"massive_{base_timestamp + session_num}"
        
        # Multiple interactions per session
        interactions_count = random.randint(2, 4)
        
        for interaction_num in range(interactions_count):
            if interaction_num == 0:
                # First interaction uses the scenario
                user_input = conversation["user_input"]
                agent_response = conversation["agent_response"]
            else:
                # Follow-up interactions
                user_input = random.choice([
                    "Can you provide more details?",
                    "What are the next steps?", 
                    "How long will this take?",
                    "Thank you for the help"
                ])
                agent_response = f"Certainly! Here's additional information for step {interaction_num + 1}."
            
            # Create interaction in the working format
            interaction = {
                "user_input": user_input,
                "agent_response": agent_response,
                "session_id": session_id,
                "response_time_ms": random.randint(400, 2000),
                "workflow_step": interaction_num + 1,
                "intent": scenario["intent"],
                "tool_calls": json.dumps([{"name": tool, "result": "success"} for tool in conversation["tools"]])
            }
            
            all_sessions.append(interaction)
    
    print(f"✅ Generated {len(all_sessions)} interactions across 500 unique sessions")
    return all_sessions

def load_in_small_batches(sessions, batch_size=10):
    """Load data in very small batches to avoid API issues"""
    
    print(f"📦 Loading {len(sessions)} interactions in batches of {batch_size}...")
    
    total_batches = (len(sessions) + batch_size - 1) // batch_size
    successful_batches = 0
    total_interactions_loaded = 0
    
    for i in range(0, len(sessions), batch_size):
        batch = sessions[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        
        try:
            print(f"🔄 Batch {batch_num}/{total_batches} ({len(batch)} interactions)...", end="")
            
            response = requests.post(
                f"{API_BASE}/ingest/json",
                json={"data": batch},
                timeout=30,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                interactions_processed = result.get("interactions_processed", 0) 
                sessions_processed = result.get("sessions_processed", 0)
                total_interactions_loaded += interactions_processed
                successful_batches += 1
                print(f" ✅ {interactions_processed} interactions, {sessions_processed} sessions")
            else:
                print(f" ❌ HTTP {response.status_code}")
                if batch_num <= 3:  # Show details for first few failures
                    try:
                        error = response.json()
                        print(f"    Error: {error.get('message', 'Unknown')[:100]}")
                    except:
                        print(f"    Raw: {response.text[:100]}")
                        
        except Exception as e:
            print(f" ❌ Error: {str(e)[:50]}")
        
        # Small delay between batches
        time.sleep(0.5)
        
        # Show progress every 20 batches
        if batch_num % 20 == 0:
            print(f"📊 Progress: {successful_batches}/{batch_num} successful, {total_interactions_loaded} interactions loaded")
    
    print("\n🎯 Final Results:")
    print(f"✅ Successful batches: {successful_batches}/{total_batches}")
    print(f"📊 Total interactions loaded: {total_interactions_loaded}")
    
    return total_interactions_loaded

def verify_data_loaded():
    """Check that the massive data is now available"""
    print("\n🔍 Verifying loaded data...")
    
    try:
        # Check intent performance
        response = requests.get(f"{API_BASE}/analytics/intent-performance", timeout=15)
        if response.status_code == 200:
            intent_data = response.json()
            total_sessions = sum(i['session_count'] for i in intent_data)
            print(f"📊 Sessions available: {total_sessions}")
            print(f"🤖 Intent types: {len(intent_data)}")
            
            # Show intent breakdown
            for intent in intent_data:
                sessions = intent['session_count']
                completion = intent['completion_rate']
                print(f"  • {intent['intent'].replace('_', ' ').title()}: {sessions} sessions ({completion:.1%} success)")
        
        # Check session volume
        response = requests.get(f"{API_BASE}/analytics/session-volume", timeout=15)
        if response.status_code == 200:
            session_data = response.json()
            total_interactions = sum(s['interaction_count'] for s in session_data)
            print(f"💬 Total interactions: {total_interactions}")
            return total_interactions > 100  # Success if we have > 100 interactions
            
    except Exception as e:
        print(f"❌ Error checking data: {e}")
        return False

if __name__ == "__main__":
    print("🚀 WORKING MASSIVE DATA LOADER")
    print("=" * 60)
    
    # Generate data in working format
    print("\n1️⃣ Generating Sessions...")
    sessions = create_working_data_format()
    
    # Load in small batches
    print("\n2️⃣ Loading Data...")
    total_loaded = load_in_small_batches(sessions, batch_size=8)
    
    if total_loaded > 0:
        # Verify the data is available
        print("\n3️⃣ Verification...")
        success = verify_data_loaded()
        
        if success:
            print("\n🎉 SUCCESS: Massive dataset loaded!")
            print("🔗 Dashboard: http://localhost:8511")
            print("📊 Now shows hundreds of sessions across multiple agent types")
        else:
            print("\n⚠️ Data loaded but not showing in analytics yet")
            print("🔄 May need to wait for processing or trigger evaluations")
    else:
        print("\n❌ FAILED: No data was loaded successfully")
        print("🔧 API issues need further debugging")