"""
Final Working Data Loader for Kalytera
Uses the exact same format as the successful test endpoints
"""

import requests
import time
import random
from datetime import datetime, timedelta

API_BASE = "https://agentiq-api-z9it.onrender.com"

def create_sample_data():
    """Create data in the exact format that works"""
    
    # Enterprise agent scenarios
    scenarios = [
        {
            "intent": "customer_support",
            "examples": [
                {
                    "user_input": "I need help with my billing account",
                    "agent_response": "I'll help you with your billing questions. Let me pull up your account details and resolve this for you."
                },
                {
                    "user_input": "My service is down and customers can't access our platform", 
                    "agent_response": "This is a high priority issue. I'm escalating to our technical team immediately and will monitor the resolution."
                }
            ]
        },
        {
            "intent": "technical_support",
            "examples": [
                {
                    "user_input": "The API is returning 500 errors intermittently",
                    "agent_response": "I see you're experiencing API errors. Let me check our service status and logs to identify the root cause."
                },
                {
                    "user_input": "How do I integrate your webhooks with Slack?",
                    "agent_response": "I'll guide you through webhook setup for Slack. Here's the step-by-step process with authentication details."
                }
            ]
        },
        {
            "intent": "sales_support", 
            "examples": [
                {
                    "user_input": "What's your enterprise pricing model?",
                    "agent_response": "Our enterprise plans are customized for your needs. Can you tell me about your team size and requirements?"
                },
                {
                    "user_input": "Do you support SOC 2 compliance requirements?",
                    "agent_response": "Yes, we're SOC 2 Type II compliant. I can share our compliance documentation and security details."
                }
            ]
        },
        {
            "intent": "code_assistance",
            "examples": [
                {
                    "user_input": "Write a FastAPI endpoint for user authentication",
                    "agent_response": "I'll create a FastAPI auth endpoint with JWT tokens, proper validation, and error handling."
                },
                {
                    "user_input": "Debug this React component that's causing memory leaks",
                    "agent_response": "I can see the issue - useEffect is missing cleanup. Here's the corrected version with proper dependency management."
                }
            ]
        },
        {
            "intent": "data_analysis",
            "examples": [
                {
                    "user_input": "Analyze customer churn data for Q4",
                    "agent_response": "I'll analyze your Q4 churn patterns, identify key risk factors, and provide actionable insights for retention."
                },
                {
                    "user_input": "Create a dashboard for sales performance metrics",
                    "agent_response": "I'll build a comprehensive sales dashboard with KPIs, trend analysis, and real-time performance tracking."
                }
            ]
        }
    ]
    
    # Generate sessions using the EXACT format that works
    all_data = []
    base_timestamp = datetime.now()
    
    for i in range(100):  # Create 100 sessions
        scenario = random.choice(scenarios)
        example = random.choice(scenario["examples"])
        
        # Create unique session ID
        session_id = f"enterprise_demo_{int(time.time())}_{i:03d}"
        
        # Create 2-4 interactions per session
        interactions_count = random.randint(2, 4)
        
        for step in range(interactions_count):
            # Calculate timestamp
            interaction_time = base_timestamp - timedelta(
                days=random.randint(0, 7),
                hours=random.randint(0, 23),
                minutes=step * random.randint(1, 10)
            )
            
            if step == 0:
                # First interaction - use the scenario
                user_input = example["user_input"] 
                agent_response = example["agent_response"]
            else:
                # Follow-up interactions
                followups = [
                    "Can you provide more details about that?",
                    "What would be the next steps?", 
                    "How long will this process take?",
                    "Are there any potential issues I should know about?",
                    "Thank you, that's very helpful!"
                ]
                user_input = random.choice(followups)
                agent_response = f"Certainly! For step {step + 1}, here are the additional details and next actions you should take."
            
            # Use EXACT format from successful test endpoint
            interaction = {
                "session_id": session_id,
                "timestamp": interaction_time.isoformat() + "Z",
                "user_input": user_input,
                "agent_response": agent_response,
                "response_time_ms": random.randint(400, 2000),
                "tokens_used": random.randint(20, 100)
            }
            
            all_data.append(interaction)
    
    return all_data

def load_data_batch(data, batch_size=5):
    """Load data in small batches with proper error handling"""
    
    print(f"📦 Loading {len(data)} interactions in batches of {batch_size}...")
    
    total_batches = (len(data) + batch_size - 1) // batch_size
    successful_batches = 0
    total_loaded = 0
    
    for i in range(0, len(data), batch_size):
        batch = data[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        
        try:
            print(f"🔄 Batch {batch_num}/{total_batches} ({len(batch)} interactions)...", end=" ")
            
            response = requests.post(
                f"{API_BASE}/ingest/json",
                json={"data": batch},
                timeout=30,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    interactions_processed = result.get("interactions_processed", 0)
                    sessions_processed = result.get("sessions_processed", 0)
                    total_loaded += interactions_processed
                    successful_batches += 1
                    print(f"✅ {interactions_processed} interactions, {sessions_processed} sessions")
                else:
                    print(f"❌ {result.get('message', 'Unknown error')}")
            else:
                print(f"❌ HTTP {response.status_code}")
                # Show error for first few failures only
                if batch_num <= 3:
                    try:
                        error_detail = response.json()
                        print(f"    Details: {error_detail.get('detail', 'No details')[:100]}")
                    except:
                        print(f"    Raw response: {response.text[:100]}")
                        
        except Exception as e:
            print(f"❌ Error: {str(e)[:50]}")
        
        # Small delay between batches
        time.sleep(0.5)
        
        # Progress update every 10 batches
        if batch_num % 10 == 0:
            success_rate = (successful_batches / batch_num) * 100
            print(f"📊 Progress: {successful_batches}/{batch_num} successful ({success_rate:.1f}%), {total_loaded} interactions loaded")
    
    # Final results
    success_rate = (successful_batches / total_batches) * 100
    print("\n🎯 Final Results:")
    print(f"✅ Successful batches: {successful_batches}/{total_batches} ({success_rate:.1f}%)")
    print(f"📊 Total interactions loaded: {total_loaded}")
    
    return total_loaded

def verify_data():
    """Verify the data was loaded successfully"""
    print("\n🔍 Verifying loaded data...")
    
    try:
        # Check intent performance
        response = requests.get(f"{API_BASE}/analytics/intent-performance", timeout=15)
        if response.status_code == 200:
            intent_data = response.json()
            total_sessions = sum(i.get('session_count', 0) for i in intent_data)
            
            print("📊 Data verification successful:")
            print(f"   • Total sessions: {total_sessions}")
            print(f"   • Agent types: {len(intent_data)}")
            
            if intent_data:
                print("🤖 Agent types found:")
                for intent in intent_data[:5]:
                    agent_type = intent.get('intent', 'unknown').replace('_', ' ').title()
                    sessions = intent.get('session_count', 0)
                    completion = intent.get('completion_rate', 0)
                    print(f"   • {agent_type}: {sessions} sessions ({completion:.1%} success)")
                
                if len(intent_data) > 5:
                    remaining = len(intent_data) - 5
                    print(f"   ... and {remaining} more agent types")
            
            return total_sessions > 0
        else:
            print(f"❌ Analytics check failed: HTTP {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Verification error: {e}")
        return False

def trigger_evaluations():
    """Trigger LLM evaluations on the loaded data"""
    print("\n🧠 Triggering LLM evaluations...")
    
    try:
        response = requests.post(
            f"{API_BASE}/evaluation/evaluate-batch",
            json={"hours_back": 24},
            timeout=60,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            result = response.json()
            evaluations_completed = result.get("evaluations_completed", 0)
            avg_score = result.get("quality_summary", {}).get("avg_overall_score", 0)
            
            print(f"✅ Evaluations completed: {evaluations_completed}")
            print(f"📊 Average quality score: {avg_score:.2f}")
            return True
        else:
            print(f"❌ Evaluation failed: HTTP {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Evaluation error: {e}")
        return False

def main():
    """Main execution with complete workflow"""
    print("🚀 FINAL WORKING AGENTIQ DATA LOADER")
    print("=" * 60)
    
    # Step 1: Generate properly formatted data
    print("\n1️⃣ Generating Enterprise Data...")
    data = create_sample_data()
    print(f"✅ Generated {len(data)} interactions from 5 enterprise agent types")
    
    # Step 2: Load data in small batches
    print("\n2️⃣ Loading Data...")
    total_loaded = load_data_batch(data, batch_size=3)  # Very small batches
    
    if total_loaded > 0:
        # Step 3: Verify data loading
        print("\n3️⃣ Verifying Data...")
        verification_success = verify_data()
        
        if verification_success:
            # Step 4: Trigger evaluations
            print("\n4️⃣ Running LLM Evaluations...")
            evaluation_success = trigger_evaluations()
            
            # Step 5: Final summary
            print("\n🎉 AGENTIQ ENTERPRISE DEMO READY!")
            print("=" * 60)
            print(f"✅ Data Loading: {total_loaded} interactions loaded")
            print("✅ Analytics: Multiple agent types available")
            print(f"✅ LLM Evaluation: {'Active' if evaluation_success else 'Pending'}")
            print()
            print("🔗 Enterprise Dashboard: http://localhost:8511")
            print(f"📊 API Endpoint: {API_BASE}")
            print("🧪 Test Suite: python3 comprehensive_agentiq_test.py")
            print()
            print("🎯 Ready for end-to-end testing!")
        else:
            print("\n⚠️ Data loaded but verification incomplete")
    else:
        print("\n❌ Data loading failed - check API connectivity")

if __name__ == "__main__":
    main()