"""
Quick Fix: Load Massive Data Directly to AgentIQ
Bypass API issues and get thousands of sessions loaded immediately
"""

import requests
import json
import time
import random

API_BASE = "https://agentiq-api-z9it.onrender.com"

def seed_massive_sample_data():
    """Use the admin endpoint to seed massive sample data directly"""
    print("🚀 Seeding Massive Sample Data via Admin Endpoint...")
    
    try:
        response = requests.post(
            f"{API_BASE}/admin/seed-sample-data",
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Sample data seeded successfully!")
            print(f"📊 Check the response: {result}")
        else:
            print(f"❌ Failed to seed data: HTTP {response.status_code}")
            print(f"Response: {response.text}")
            
    except Exception as e:
        print(f"❌ Error seeding data: {e}")

def load_simple_massive_batch():
    """Load simple massive batch with unique timestamps"""
    print("📊 Loading Simple Massive Batch...")
    
    # Generate 100 unique sessions with multiple interactions each
    batch_data = []
    
    for i in range(100):
        session_id = f"massive_session_{int(time.time())}_{i}"
        
        # Each session has 3-5 interactions
        interactions_per_session = random.randint(3, 5)
        
        for j in range(interactions_per_session):
            interaction = {
                "user_input": f"User request {j+1} for session {i+1}",
                "agent_response": f"Agent response handling request {j+1} for session {i+1}",
                "session_id": session_id,
                "response_time_ms": random.randint(500, 2000),
                "workflow_step": j + 1,
                "intent": random.choice([
                    "customer_support", "technical_support", "billing_inquiry",
                    "code_generation", "debugging_help", "data_analysis",
                    "sales_inquiry", "demo_request", "pricing_question"
                ]),
                "tool_calls": json.dumps([{"name": "tool", "result": "success"}])
            }
            batch_data.append(interaction)
    
    print(f"🔢 Generated {len(batch_data)} interactions across 100 unique sessions")
    
    try:
        response = requests.post(
            f"{API_BASE}/ingest/json",
            json={"data": batch_data},
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Batch loaded successfully!")
            print(f"📊 Interactions processed: {result.get('interactions_processed', 0)}")
            print(f"📋 Sessions processed: {result.get('sessions_processed', 0)}")
            return True
        else:
            print(f"❌ Batch failed: HTTP {response.status_code}")
            try:
                error = response.json()
                print(f"Error details: {error}")
            except:
                print(f"Raw response: {response.text[:300]}")
            return False
            
    except Exception as e:
        print(f"❌ Error loading batch: {e}")
        return False

def check_current_data():
    """Check what data is currently available"""
    print("🔍 Checking Current Data...")
    
    try:
        # Check analytics
        response = requests.get(f"{API_BASE}/analytics/intent-performance", timeout=15)
        if response.status_code == 200:
            intent_data = response.json()
            total_sessions = sum(i['session_count'] for i in intent_data)
            print(f"📊 Current sessions: {total_sessions}")
            print(f"🤖 Intent types: {len(intent_data)}")
            
        # Check session volume
        response = requests.get(f"{API_BASE}/analytics/session-volume", timeout=15)
        if response.status_code == 200:
            session_data = response.json()
            total_interactions = sum(s['interaction_count'] for s in session_data)
            print(f"💬 Total interactions: {total_interactions}")
            
        return True
        
    except Exception as e:
        print(f"❌ Error checking data: {e}")
        return False

def trigger_evaluation():
    """Trigger evaluation on all the new data"""
    print("🧠 Triggering LLM Evaluations...")
    
    try:
        response = requests.post(
            f"{API_BASE}/evaluation/evaluate-batch",
            json={"hours_back": 1},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Evaluation triggered: {result}")
            return True
        else:
            print(f"❌ Evaluation failed: HTTP {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Error triggering evaluation: {e}")
        return False

if __name__ == "__main__":
    print("🚨 QUICK MASSIVE DATA FIX")
    print("=" * 50)
    
    # Check initial state
    print("\n1️⃣ Initial Data Check:")
    check_current_data()
    
    # Try admin seeding first
    print("\n2️⃣ Admin Data Seeding:")
    seed_massive_sample_data()
    
    # Load simple batch
    print("\n3️⃣ Simple Batch Loading:")
    success = load_simple_massive_batch()
    
    if success:
        # Wait a moment then check results
        print("\n⏳ Waiting for data processing...")
        time.sleep(3)
        
        print("\n4️⃣ Post-Load Data Check:")
        check_current_data()
        
        print("\n5️⃣ Triggering Evaluations:")
        trigger_evaluation()
        
        print("\n✅ MASSIVE DATA LOADED!")
        print("🔗 Check dashboard: http://localhost:8511")
        print("📊 Should now show hundreds of sessions")
        
    else:
        print("\n❌ BATCH LOADING FAILED")
        print("🔧 Need to debug API issues further")