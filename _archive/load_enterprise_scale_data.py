"""
Load Enterprise-Scale AgentIQ Data
Generates thousands of realistic agent interactions across multiple domains
to demonstrate full evaluation platform capabilities
"""

import requests
import json
import random
from datetime import datetime, timedelta
from typing import List, Dict
import time

API_BASE = "https://agentiq-api-z9it.onrender.com"

def generate_enterprise_agent_sessions() -> List[Dict]:
    """Generate thousands of realistic enterprise agent interactions"""
    
    # Enterprise agent types with realistic usage patterns
    agent_scenarios = [
        # Customer Support Agents
        {
            "intent": "billing_support",
            "domain": "customer_service", 
            "scenarios": [
                {"user": "I was charged twice for my subscription", "response": "I can see duplicate charges on your account. Let me process a refund for the duplicate charge.", "quality": 0.9, "tools": ["billing_system", "refund_processor"]},
                {"user": "How do I cancel my subscription?", "response": "I can help you cancel. Would you like to cancel immediately or at the end of your billing cycle?", "quality": 0.85, "tools": ["subscription_manager"]},
                {"user": "My bill seems wrong", "response": "Let me review your billing history to identify any discrepancies.", "quality": 0.8, "tools": ["billing_system", "usage_analytics"]},
            ]
        },
        {
            "intent": "technical_support", 
            "domain": "customer_service",
            "scenarios": [
                {"user": "The app keeps crashing on iOS", "response": "This is a known issue with iOS 17.2. Please update to version 2.1.3 which fixes this crash.", "quality": 0.88, "tools": ["bug_tracker", "app_store_api"]},
                {"user": "I can't login to my account", "response": "Let me check your account status and help reset your password if needed.", "quality": 0.82, "tools": ["auth_system", "password_reset"]},
                {"user": "Features are missing after update", "response": "Some features were moved in the latest update. Let me guide you to their new locations.", "quality": 0.75, "tools": ["feature_mapper"]},
            ]
        },
        
        # Sales & BDR Agents
        {
            "intent": "lead_qualification",
            "domain": "sales",
            "scenarios": [
                {"user": "What's your pricing for enterprise?", "response": "Our enterprise plans start at $500/month. Can you tell me about your team size and specific needs?", "quality": 0.9, "tools": ["pricing_calculator", "crm_system"]},
                {"user": "Do you offer custom integrations?", "response": "Yes, we provide custom integrations for enterprise clients. What systems do you need to integrate with?", "quality": 0.92, "tools": ["integration_catalog", "technical_discovery"]},
                {"user": "What's your implementation timeline?", "response": "Typical enterprise implementations take 2-4 weeks depending on complexity. Let me assess your specific requirements.", "quality": 0.88, "tools": ["project_timeline", "technical_assessment"]},
            ]
        },
        {
            "intent": "demo_scheduling",
            "domain": "sales", 
            "scenarios": [
                {"user": "Can we schedule a demo?", "response": "Absolutely! I have availability next Tuesday or Wednesday. What time works best for you?", "quality": 0.95, "tools": ["calendar_system", "demo_scheduler"]},
                {"user": "I need to show this to my team", "response": "Perfect! I can set up a team demo. How many people will be joining and what are their roles?", "quality": 0.91, "tools": ["team_demo_setup", "stakeholder_mapping"]},
                {"user": "What should I prepare for the demo?", "response": "Please prepare your current workflow details and key pain points. This helps me customize the demo for maximum relevance.", "quality": 0.89, "tools": ["demo_prep_guide"]},
            ]
        },
        
        # Coding Assistant Agents
        {
            "intent": "code_generation", 
            "domain": "engineering",
            "scenarios": [
                {"user": "Write a React component for user authentication", "response": "Here's a React authentication component with hooks:\n\n```jsx\nconst AuthComponent = () => {\n  const [user, setUser] = useState(null);\n  // Authentication logic here\n};\n```", "quality": 0.87, "tools": ["code_generator", "react_docs"]},
                {"user": "Fix this Python function for data processing", "response": "I see the issue - you're missing error handling for null values. Here's the corrected version with proper validation.", "quality": 0.85, "tools": ["code_analyzer", "python_linter"]},
                {"user": "Optimize this SQL query performance", "response": "This query can be optimized by adding an index on the join column and restructuring the WHERE clause.", "quality": 0.89, "tools": ["query_optimizer", "database_analyzer"]},
            ]
        },
        {
            "intent": "debugging_assistance",
            "domain": "engineering", 
            "scenarios": [
                {"user": "Getting 'Cannot read property of undefined' error", "response": "This error occurs when accessing properties on null/undefined objects. Add optional chaining: `obj?.property`", "quality": 0.83, "tools": ["error_analyzer", "javascript_debugger"]},
                {"user": "Memory leak in my Node.js app", "response": "Memory leaks often come from unclosed database connections or event listeners. Let me check your connection pooling.", "quality": 0.78, "tools": ["memory_profiler", "node_analyzer"]},
                {"user": "Docker container won't start", "response": "Check the container logs with 'docker logs container_name'. Common issues include port conflicts or missing environment variables.", "quality": 0.85, "tools": ["docker_analyzer", "container_logs"]},
            ]
        },
        
        # Data Science Agents  
        {
            "intent": "data_analysis",
            "domain": "analytics",
            "scenarios": [
                {"user": "Analyze customer churn patterns", "response": "I'll analyze your customer data to identify churn indicators. Key factors often include usage decline, support tickets, and payment delays.", "quality": 0.92, "tools": ["churn_analyzer", "customer_db", "ml_models"]},
                {"user": "Create a predictive model for sales", "response": "Based on your historical data, I'll build a Random Forest model to predict quarterly sales with feature importance analysis.", "quality": 0.88, "tools": ["ml_framework", "feature_engineering", "sales_data"]},
                {"user": "Visualize revenue trends", "response": "I'll create an interactive dashboard showing revenue trends by segment, with year-over-year comparisons and forecasting.", "quality": 0.90, "tools": ["visualization_engine", "revenue_db", "forecasting"]},
            ]
        },
        
        # HR & Recruitment Agents
        {
            "intent": "candidate_screening", 
            "domain": "human_resources",
            "scenarios": [
                {"user": "Screen candidates for Software Engineer role", "response": "I'll evaluate candidates based on technical skills, experience, and cultural fit. Here's my assessment framework.", "quality": 0.86, "tools": ["resume_analyzer", "skills_matcher", "interview_scheduler"]},
                {"user": "Check reference for candidate John Smith", "response": "I've contacted the provided references. Two confirmed strong performance, one mentioned areas for improvement in communication.", "quality": 0.91, "tools": ["reference_checker", "background_system"]},
                {"user": "Schedule interviews for next week", "response": "I've coordinated with the interview panel. Available slots are Tuesday 2-4pm and Thursday 10am-12pm.", "quality": 0.89, "tools": ["calendar_coordinator", "interview_panel"]},
            ]
        },
        
        # Marketing Agents
        {
            "intent": "content_creation",
            "domain": "marketing", 
            "scenarios": [
                {"user": "Create email campaign for product launch", "response": "I've drafted a 3-email sequence with personalization. Email 1 builds anticipation, Email 2 announces launch, Email 3 includes social proof.", "quality": 0.87, "tools": ["email_composer", "personalization_engine", "ab_testing"]},
                {"user": "Optimize ad copy for better CTR", "response": "Current copy focuses on features. I recommend benefit-focused headlines with emotional triggers and clear CTAs.", "quality": 0.84, "tools": ["copy_optimizer", "ctr_analyzer", "ad_performance"]},
                {"user": "Analyze competitor marketing strategies", "response": "Competitors focus heavily on social media and influencer partnerships. Opportunity exists in SEO content and email marketing.", "quality": 0.88, "tools": ["competitor_intel", "market_analyzer", "seo_tools"]},
            ]
        }
    ]
    
    sessions = []
    session_count = 0
    
    # Generate 5000+ interactions across different time periods
    for days_ago in range(0, 30):  # 30 days of data
        date = datetime.now() - timedelta(days=days_ago)
        
        # More activity during business hours and recent days
        daily_volume = random.randint(50, 200) if days_ago < 7 else random.randint(20, 100)
        
        for _ in range(daily_volume):
            # Select random agent scenario
            scenario_group = random.choice(agent_scenarios)
            scenario = random.choice(scenario_group["scenarios"])
            
            session_id = f"session_{session_count:06d}"
            session_count += 1
            
            # Add some variation to quality and response times
            base_quality = scenario["quality"]
            quality_variation = random.uniform(-0.1, 0.1)
            final_quality = max(0.4, min(0.98, base_quality + quality_variation))
            
            response_time = random.randint(300, 3000)  # 300ms to 3s
            
            # Some sessions have multi-step workflows
            workflow_steps = random.randint(1, 4)
            
            for step in range(workflow_steps):
                if step == 0:
                    user_input = scenario["user"]
                    agent_response = scenario["response"]
                else:
                    # Follow-up interactions
                    user_input = random.choice([
                        "Can you explain more?", "What are the next steps?", 
                        "How long will this take?", "Is there anything else I should know?",
                        "Can you help with something else?", "Thank you for the help"
                    ])
                    agent_response = random.choice([
                        "Certainly! Let me provide more details.", 
                        "The next step is to...", "This typically takes 24-48 hours.",
                        "Yes, also consider...", "Of course! What else can I help with?",
                        "You're welcome! Feel free to reach out anytime."
                    ])
                
                interaction = {
                    "user_input": user_input,
                    "agent_response": agent_response, 
                    "session_id": session_id,
                    "response_time_ms": response_time + random.randint(-100, 200),
                    "workflow_step": step + 1,
                    "intent": scenario_group["intent"],
                    "domain": scenario_group["domain"],
                    "timestamp": (date + timedelta(hours=random.randint(8, 18), minutes=random.randint(0, 59))).isoformat(),
                    "tool_calls": json.dumps([{"name": tool, "result": "success"} for tool in scenario.get("tools", [])]),
                    "quality_score": final_quality - (step * 0.02),  # Quality may decline in longer workflows
                    "business_impact_score": random.uniform(0.6, 0.95),
                    "user_satisfaction": random.uniform(0.7, 0.98) if final_quality > 0.8 else random.uniform(0.3, 0.7)
                }
                
                sessions.append(interaction)
    
    return sessions

def load_data_in_batches(sessions: List[Dict], batch_size: int = 100):
    """Load data in batches to avoid timeout issues"""
    
    print(f"Loading {len(sessions):,} enterprise agent sessions...")
    
    total_batches = (len(sessions) + batch_size - 1) // batch_size
    
    for i in range(0, len(sessions), batch_size):
        batch = sessions[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        
        print(f"Loading batch {batch_num}/{total_batches} ({len(batch)} interactions)...")
        
        try:
            response = requests.post(
                f"{API_BASE}/ingest/json",
                json={"data": batch}, 
                timeout=30
            )
            
            if response.status_code == 200:
                print(f"✅ Batch {batch_num} loaded successfully")
            else:
                print(f"❌ Batch {batch_num} failed: {response.status_code}")
                
        except Exception as e:
            print(f"❌ Batch {batch_num} error: {e}")
            
        # Small delay between batches 
        time.sleep(0.5)
    
    print("\n🎯 Enterprise data loading complete!")
    print(f"📊 {len(sessions):,} total interactions loaded")
    
    # Get unique counts
    intents = set(s["intent"] for s in sessions)
    domains = set(s["domain"] for s in sessions) 
    sessions_count = set(s["session_id"] for s in sessions)
    
    print(f"🤖 {len(intents)} different agent types")
    print(f"🏢 {len(domains)} business domains")
    print(f"💬 {len(sessions_count)} unique sessions")

if __name__ == "__main__":
    print("🏢 Generating Enterprise-Scale AgentIQ Data...")
    print("=" * 60)
    
    # Generate diverse enterprise sessions
    sessions = generate_enterprise_agent_sessions()
    
    print(f"Generated {len(sessions):,} interactions across:")
    intents = set(s["intent"] for s in sessions)
    domains = set(s["domain"] for s in sessions)
    print(f"- {len(intents)} agent types: {', '.join(intents)}")
    print(f"- {len(domains)} domains: {', '.join(domains)}")
    print()
    
    # Load data
    load_data_in_batches(sessions, batch_size=50)
    
    print("\n🔗 View results at: http://localhost:8511")
    print("📈 This demonstrates the full-scale AgentIQ evaluation platform")