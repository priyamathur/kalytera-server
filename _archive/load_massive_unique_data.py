"""
Load Massive AgentIQ Data with Unique Session IDs
Fix API errors and load thousands of agent sessions successfully
"""

import requests
import json
import random
import time
from datetime import datetime, timedelta
from typing import List, Dict

API_BASE = "https://agentiq-api-z9it.onrender.com"

def generate_unique_session_id() -> str:
    """Generate truly unique session ID"""
    timestamp = int(time.time() * 1000)  # milliseconds
    random_suffix = random.randint(1000, 9999)
    return f"session_{timestamp}_{random_suffix}"

def generate_massive_agent_data() -> List[Dict]:
    """Generate thousands of realistic agent interactions with unique IDs"""
    
    # Enterprise agent scenarios with realistic patterns
    agent_templates = {
        "customer_support": [
            {"intent": "billing_support", "quality_range": (0.75, 0.95), "tools": ["billing_system", "payment_processor"]},
            {"intent": "technical_support", "quality_range": (0.7, 0.9), "tools": ["diagnostic_tool", "knowledge_base"]},
            {"intent": "account_management", "quality_range": (0.8, 0.95), "tools": ["user_database", "account_manager"]},
        ],
        "sales": [
            {"intent": "lead_qualification", "quality_range": (0.8, 0.95), "tools": ["crm_system", "lead_scoring"]},
            {"intent": "demo_scheduling", "quality_range": (0.85, 0.98), "tools": ["calendar_system", "demo_platform"]},
            {"intent": "pricing_inquiry", "quality_range": (0.75, 0.9), "tools": ["pricing_engine", "proposal_generator"]},
        ],
        "engineering": [
            {"intent": "code_generation", "quality_range": (0.7, 0.9), "tools": ["code_generator", "documentation"]},
            {"intent": "debugging_assistance", "quality_range": (0.65, 0.85), "tools": ["debugger", "error_analyzer"]},
            {"intent": "code_review", "quality_range": (0.8, 0.95), "tools": ["static_analyzer", "best_practices"]},
        ],
        "data_science": [
            {"intent": "data_analysis", "quality_range": (0.8, 0.95), "tools": ["analytics_engine", "visualization"]},
            {"intent": "model_training", "quality_range": (0.75, 0.9), "tools": ["ml_framework", "feature_engineering"]},
            {"intent": "data_visualization", "quality_range": (0.85, 0.95), "tools": ["plotting_library", "dashboard"]},
        ],
        "marketing": [
            {"intent": "content_creation", "quality_range": (0.8, 0.92), "tools": ["content_generator", "seo_optimizer"]},
            {"intent": "campaign_optimization", "quality_range": (0.75, 0.9), "tools": ["ad_manager", "analytics"]},
            {"intent": "audience_analysis", "quality_range": (0.8, 0.95), "tools": ["customer_insights", "segmentation"]},
        ]
    }
    
    # Generate user input/response templates
    conversation_templates = {
        "billing_support": [
            ("I was charged twice for my subscription", "I can see the duplicate charge on your account. I'll process a refund for the duplicate payment right away."),
            ("How do I update my payment method?", "You can update your payment method in your account settings under the Billing section. Would you like me to walk you through it?"),
            ("My invoice seems incorrect", "Let me review your billing history to identify any discrepancies and resolve this for you."),
        ],
        "technical_support": [
            ("The app keeps crashing on iOS", "This is a known issue with iOS 17.2. Please update to app version 2.1.3 which includes the fix for this crash."),
            ("I can't login to my account", "Let me check your account status and help you reset your credentials if needed."),
            ("Features are missing after the update", "Some features were reorganized in the latest update. Let me guide you to their new locations."),
        ],
        "lead_qualification": [
            ("What's your pricing for enterprise?", "Our enterprise plans start at $500/month. Can you tell me about your team size and specific requirements?"),
            ("Do you offer custom integrations?", "Yes, we provide custom integrations for enterprise clients. What systems do you need to integrate with?"),
            ("What's your implementation timeline?", "Typical enterprise implementations take 2-4 weeks. Let me assess your specific requirements."),
        ],
        "code_generation": [
            ("Write a React component for user auth", "Here's a React authentication component with hooks and proper error handling."),
            ("Create a Python function for data processing", "I'll create a robust data processing function with validation and error handling."),
            ("Generate SQL query for analytics", "Here's an optimized SQL query for your analytics requirements with proper indexing."),
        ],
        "data_analysis": [
            ("Analyze customer churn patterns", "I'll analyze your customer data to identify key churn indicators and at-risk segments."),
            ("Create a predictive model for sales", "I'll build a machine learning model to forecast sales with feature importance analysis."),
            ("Generate insights from user behavior", "Let me analyze user behavior patterns and provide actionable insights for improvement."),
        ]
    }
    
    sessions = []
    session_counter = 0
    
    print("🏗️ Generating massive agent dataset...")
    
    # Generate thousands of sessions over the past 30 days
    for days_ago in range(0, 30):
        date = datetime.now() - timedelta(days=days_ago)
        
        # More activity on recent days and business hours
        if days_ago < 7:
            daily_sessions = random.randint(150, 300)  # Recent week: high activity
        elif days_ago < 14:
            daily_sessions = random.randint(100, 200)  # Previous week: medium activity
        else:
            daily_sessions = random.randint(50, 120)   # Older: lower activity
        
        for _ in range(daily_sessions):
            session_counter += 1
            
            # Select random domain and agent type
            domain = random.choice(list(agent_templates.keys()))
            agent_config = random.choice(agent_templates[domain])
            
            intent = agent_config["intent"]
            quality_min, quality_max = agent_config["quality_range"]
            tools = agent_config["tools"]
            
            # Generate unique session ID
            session_id = generate_unique_session_id()
            
            # Get conversation template if available
            if intent in conversation_templates:
                conversation = random.choice(conversation_templates[intent])
                user_input, agent_response = conversation
            else:
                user_input = f"Help me with {intent.replace('_', ' ')}"
                agent_response = f"I'll help you with {intent.replace('_', ' ')}. Let me gather the necessary information."
            
            # Generate realistic quality score
            quality_score = random.uniform(quality_min, quality_max)
            
            # Response time varies by complexity
            base_response_time = {
                "billing_support": 800,
                "technical_support": 1200,
                "lead_qualification": 600,
                "demo_scheduling": 400,
                "code_generation": 2000,
                "debugging_assistance": 1500,
                "data_analysis": 1800,
                "content_creation": 1000
            }.get(intent, 1000)
            
            response_time = base_response_time + random.randint(-200, 500)
            
            # Some sessions have multiple workflow steps
            workflow_steps = random.choices([1, 2, 3, 4], weights=[40, 30, 20, 10])[0]
            
            for step in range(workflow_steps):
                # Generate timestamp within business hours
                hour = random.randint(8, 18)
                minute = random.randint(0, 59)
                interaction_time = date + timedelta(hours=hour, minutes=minute, seconds=step*30)
                
                if step == 0:
                    current_input = user_input
                    current_response = agent_response
                else:
                    # Follow-up interactions
                    followups = [
                        "Can you provide more details?",
                        "What are the next steps?",
                        "How long will this take?", 
                        "Is there anything else I should know?",
                        "Can you help with something related?",
                        "Thank you, that's helpful"
                    ]
                    current_input = random.choice(followups)
                    current_response = f"Certainly! Let me provide additional information for step {step + 1}."
                
                # Quality degrades slightly in longer workflows
                step_quality = quality_score - (step * 0.03)
                step_quality = max(0.4, min(0.98, step_quality))
                
                interaction = {
                    "user_input": current_input,
                    "agent_response": current_response,
                    "session_id": session_id,
                    "response_time_ms": response_time + random.randint(-100, 200),
                    "workflow_step": step + 1,
                    "intent": intent,
                    "timestamp": interaction_time.isoformat(),
                    "tool_calls": json.dumps([{"name": tool, "result": "success"} for tool in tools]),
                    "quality_score": step_quality,
                    "domain": domain
                }
                
                sessions.append(interaction)
    
    print(f"✅ Generated {len(sessions):,} interactions across {session_counter:,} unique sessions")
    return sessions

def load_data_safely(sessions: List[Dict], batch_size: int = 25) -> int:
    """Load data in small batches to avoid API timeouts and conflicts"""
    
    print(f"📊 Loading {len(sessions):,} interactions to AgentIQ...")
    print(f"🔧 Using batch size: {batch_size}")
    
    total_batches = (len(sessions) + batch_size - 1) // batch_size
    successful_loads = 0
    total_loaded = 0
    
    for i in range(0, len(sessions), batch_size):
        batch = sessions[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        
        print(f"📦 Loading batch {batch_num}/{total_batches} ({len(batch)} interactions)...")
        
        try:
            response = requests.post(
                f"{API_BASE}/ingest/json",
                json={"data": batch},
                timeout=45,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                interactions_processed = result.get("interactions_processed", 0)
                total_loaded += interactions_processed
                successful_loads += 1
                print(f"✅ Batch {batch_num} success: {interactions_processed} interactions loaded")
            else:
                print(f"❌ Batch {batch_num} failed: HTTP {response.status_code}")
                if response.status_code == 400:
                    try:
                        error_detail = response.json()
                        print(f"   Error: {error_detail.get('message', 'Unknown error')}")
                    except:
                        print(f"   Raw error: {response.text[:200]}")
                
        except requests.exceptions.Timeout:
            print(f"⏰ Batch {batch_num} timed out - server processing large batch")
        except Exception as e:
            print(f"❌ Batch {batch_num} error: {str(e)[:100]}")
        
        # Small delay between batches to prevent overwhelming the server
        time.sleep(1)
        
        # Progress update every 10 batches
        if batch_num % 10 == 0:
            print(f"📈 Progress: {batch_num}/{total_batches} batches ({total_loaded:,} interactions loaded)")
    
    print("\n🎯 Loading Complete!")
    print(f"✅ Successful batches: {successful_loads}/{total_batches}")
    print(f"📊 Total interactions loaded: {total_loaded:,}")
    
    return total_loaded

if __name__ == "__main__":
    print("🚀 Loading Massive AgentIQ Dataset")
    print("=" * 60)
    
    # Generate massive dataset
    sessions = generate_massive_agent_data()
    
    # Show summary
    intents = set(s["intent"] for s in sessions)
    domains = set(s["domain"] for s in sessions)
    unique_sessions = set(s["session_id"] for s in sessions)
    
    print("\n📋 Dataset Summary:")
    print(f"🔢 Total interactions: {len(sessions):,}")
    print(f"🆔 Unique sessions: {len(unique_sessions):,}")
    print(f"🤖 Agent intents: {len(intents)} types")
    print(f"🏢 Business domains: {len(domains)} areas")
    print()
    
    # Load in manageable batches
    total_loaded = load_data_safely(sessions, batch_size=20)
    
    if total_loaded > 0:
        print(f"\n🎉 SUCCESS: {total_loaded:,} interactions loaded to AgentIQ")
        print("🔗 View enterprise dashboard: http://localhost:8511")
        print("📈 This is the massive scale AgentIQ platform you requested")
    else:
        print("\n❌ FAILED: No data was loaded successfully")
        print("🔧 Check API status and try again with smaller batches")