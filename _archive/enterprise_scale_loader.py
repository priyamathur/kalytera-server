"""
Enterprise Scale Data Loader for AgentIQ
Creates thousands of properly formatted agent sessions with all required fields
Based on ParsedInteraction requirements from ingestion/parsers.py
"""

import requests
import json
import time
import random
from datetime import datetime, timedelta

API_BASE = "https://agentiq-api-z9it.onrender.com"

class EnterpriseDataGenerator:
    """Generate enterprise-scale agent data with proper field validation"""
    
    def __init__(self):
        # Agent types representing diverse enterprise use cases
        self.agent_scenarios = {
            "customer_support": {
                "conversations": [
                    {
                        "user_input": "I need help with my billing account",
                        "agent_response": "I'll help you with your billing questions. Let me pull up your account details.",
                        "tools": ["billing_system", "account_lookup"]
                    },
                    {
                        "user_input": "My service is down and customers can't access our platform",
                        "agent_response": "This is a high priority issue. I'm escalating to our technical team immediately.",
                        "tools": ["incident_management", "escalation_system"]
                    },
                    {
                        "user_input": "I want to cancel my subscription",
                        "agent_response": "I understand you'd like to cancel. Can I help address any issues first?",
                        "tools": ["retention_system", "billing_system"]
                    }
                ]
            },
            "technical_support": {
                "conversations": [
                    {
                        "user_input": "The API is returning 500 errors intermittently", 
                        "agent_response": "I see you're experiencing API errors. Let me check our service status and logs.",
                        "tools": ["api_diagnostics", "log_analyzer", "service_monitor"]
                    },
                    {
                        "user_input": "How do I integrate your webhooks with Slack?",
                        "agent_response": "I'll guide you through webhook setup for Slack. Here's the step-by-step process.",
                        "tools": ["webhook_config", "integration_docs", "slack_api"]
                    },
                    {
                        "user_input": "Database migration failed with timeout error",
                        "agent_response": "Database timeouts during migration are serious. Let me check your instance configuration.",
                        "tools": ["db_monitor", "migration_logs", "performance_analyzer"]
                    }
                ]
            },
            "sales_bdr": {
                "conversations": [
                    {
                        "user_input": "What's your enterprise pricing model?",
                        "agent_response": "Our enterprise plans are customized for your needs. Can you tell me about your team size?",
                        "tools": ["pricing_calculator", "enterprise_config", "crm_system"]
                    },
                    {
                        "user_input": "Do you support SOC 2 compliance requirements?",
                        "agent_response": "Yes, we're SOC 2 Type II compliant. I can share our compliance documentation.",
                        "tools": ["compliance_docs", "security_center", "audit_reports"]
                    },
                    {
                        "user_input": "Can you schedule a technical demo?",
                        "agent_response": "Absolutely! I'll connect you with our solutions engineer for a custom demo.",
                        "tools": ["calendar_system", "demo_scheduler", "sales_handoff"]
                    }
                ]
            },
            "code_assistant": {
                "conversations": [
                    {
                        "user_input": "Write a FastAPI endpoint for user authentication",
                        "agent_response": "I'll create a FastAPI auth endpoint with JWT tokens and proper validation.",
                        "tools": ["code_generator", "fastapi_docs", "auth_patterns"]
                    },
                    {
                        "user_input": "Debug this React component that's causing memory leaks",
                        "agent_response": "I can see the issue - useEffect is missing cleanup. Here's the fix:",
                        "tools": ["react_analyzer", "memory_profiler", "code_fixer"]
                    },
                    {
                        "user_input": "Optimize this SQL query for better performance",
                        "agent_response": "This query can be optimized with proper indexing. Here's an improved version:",
                        "tools": ["sql_optimizer", "query_planner", "index_advisor"]
                    }
                ]
            },
            "data_analyst": {
                "conversations": [
                    {
                        "user_input": "Analyze customer churn data for Q4",
                        "agent_response": "I'll analyze your Q4 churn patterns and identify key risk factors.",
                        "tools": ["churn_analyzer", "customer_db", "ml_models", "visualization"]
                    },
                    {
                        "user_input": "Create a dashboard for sales performance metrics",
                        "agent_response": "I'll build a comprehensive sales dashboard with KPIs and trend analysis.",
                        "tools": ["dashboard_builder", "sales_data", "chart_generator"]
                    },
                    {
                        "user_input": "Predict revenue for next quarter using historical data",
                        "agent_response": "I'll build a predictive model using your historical sales and market data.",
                        "tools": ["forecasting_model", "time_series", "revenue_data"]
                    }
                ]
            },
            "hr_assistant": {
                "conversations": [
                    {
                        "user_input": "I need help with our employee onboarding process",
                        "agent_response": "I'll help streamline your onboarding workflow and checklist.",
                        "tools": ["hr_system", "onboarding_templates", "workflow_builder"]
                    },
                    {
                        "user_input": "Generate performance review templates",
                        "agent_response": "I'll create comprehensive performance review templates for different roles.",
                        "tools": ["template_generator", "performance_metrics", "role_definitions"]
                    }
                ]
            },
            "legal_research": {
                "conversations": [
                    {
                        "user_input": "Research GDPR compliance requirements for our SaaS platform",
                        "agent_response": "I'll compile GDPR requirements specific to SaaS platforms and data processing.",
                        "tools": ["legal_database", "gdpr_analyzer", "compliance_checker"]
                    },
                    {
                        "user_input": "Draft a software license agreement",
                        "agent_response": "I'll draft a comprehensive software license tailored to your business model.",
                        "tools": ["legal_templates", "contract_generator", "license_analyzer"]
                    }
                ]
            },
            "marketing_automation": {
                "conversations": [
                    {
                        "user_input": "Create an email sequence for new product launch",
                        "agent_response": "I'll design a 7-email sequence optimized for product awareness and conversion.",
                        "tools": ["email_builder", "campaign_optimizer", "a_b_tester"]
                    },
                    {
                        "user_input": "Analyze conversion rates by traffic source",
                        "agent_response": "I'll analyze your conversion funnel and identify top-performing channels.",
                        "tools": ["analytics_engine", "funnel_analyzer", "attribution_model"]
                    }
                ]
            },
            "financial_analysis": {
                "conversations": [
                    {
                        "user_input": "Calculate ROI for our enterprise software investments",
                        "agent_response": "I'll analyze your software costs and productivity gains to calculate ROI.",
                        "tools": ["roi_calculator", "cost_analyzer", "productivity_metrics"]
                    },
                    {
                        "user_input": "Generate monthly financial reports", 
                        "agent_response": "I'll create comprehensive monthly reports with P&L analysis and trends.",
                        "tools": ["financial_reporting", "chart_generator", "trend_analyzer"]
                    }
                ]
            },
            "devops_automation": {
                "conversations": [
                    {
                        "user_input": "Set up CI/CD pipeline for our microservices",
                        "agent_response": "I'll configure a robust CI/CD pipeline with testing and deployment automation.",
                        "tools": ["cicd_builder", "pipeline_templates", "deployment_manager"]
                    },
                    {
                        "user_input": "Monitor application performance in production",
                        "agent_response": "I'll set up comprehensive monitoring with alerts for key performance metrics.",
                        "tools": ["apm_tools", "alert_manager", "log_aggregator"]
                    }
                ]
            }
        }
        
        # Generate base timestamp for unique session IDs
        self.base_timestamp = int(time.time() * 1000)
        
    def generate_properly_formatted_data(self, num_sessions=1000):
        """Generate properly formatted data matching ParsedInteraction requirements"""
        
        print(f"🏗️ Generating {num_sessions} enterprise-scale sessions...")
        
        all_interactions = []
        session_counter = 0
        
        # Create sessions with realistic distribution
        for session_num in range(num_sessions):
            # Choose random agent type and scenario
            agent_type = random.choice(list(self.agent_scenarios.keys()))
            scenario = self.agent_scenarios[agent_type]
            conversation = random.choice(scenario["conversations"])
            
            # Create unique session ID
            session_id = f"enterprise_{self.base_timestamp}_{session_counter:06d}"
            session_counter += 1
            
            # Generate 2-6 interactions per session for realistic workflows
            interactions_count = random.randint(2, 6)
            base_timestamp = datetime.now() - timedelta(days=random.randint(0, 30))
            
            for step in range(interactions_count):
                # Calculate interaction timestamp
                interaction_timestamp = base_timestamp + timedelta(
                    minutes=step * random.randint(1, 5)
                )
                
                # Create interaction with proper field formatting
                if step == 0:
                    # First interaction - use the scenario
                    user_input = conversation["user_input"]
                    agent_response = conversation["agent_response"]
                    tools_used = conversation["tools"]
                else:
                    # Follow-up interactions
                    followup_inputs = [
                        "Can you provide more details about that?",
                        "What would be the next steps?",
                        "How long will this process take?",
                        "Are there any potential issues I should know about?",
                        "Can you send me documentation on this?",
                        "Thank you, that's very helpful!"
                    ]
                    user_input = random.choice(followup_inputs)
                    agent_response = f"Certainly! For step {step + 1}, here are the details..."
                    tools_used = random.sample(conversation["tools"], min(2, len(conversation["tools"])))
                
                # Format tool calls properly as JSON string (per AgentLog model requirement)
                tool_calls_json = json.dumps([
                    {"name": tool, "result": "success"} for tool in tools_used
                ]) if tools_used else None
                
                # Create interaction matching ParsedInteraction format
                interaction = {
                    "session_id": session_id,
                    "timestamp": interaction_timestamp.isoformat() + "Z",
                    "user_input": user_input,
                    "agent_response": agent_response,
                    "workflow_step": step + 1,
                    "tool_calls": tool_calls_json,
                    "response_time_ms": random.randint(400, 3000),
                    "tokens_used": random.randint(20, 150),
                    "error_occurred": False,  # Mostly successful interactions
                    "error_message": None,
                    "intent": agent_type,  # This will be used for classification
                }
                
                # Add occasional failures for realistic data (5% failure rate)
                if random.random() < 0.05:
                    interaction["error_occurred"] = True
                    interaction["error_message"] = random.choice([
                        "API timeout - please retry",
                        "Insufficient permissions for this operation",
                        "Rate limit exceeded",
                        "External service unavailable"
                    ])
                    interaction["response_time_ms"] = random.randint(5000, 10000)  # Longer for errors
                
                all_interactions.append(interaction)
        
        print(f"✅ Generated {len(all_interactions)} interactions across {num_sessions} sessions")
        print(f"🤖 Agent types: {len(self.agent_scenarios)} different enterprise use cases")
        return all_interactions
    
    def load_data_in_batches(self, interactions, batch_size=20):
        """Load data in optimized batches with proper error handling"""
        
        print(f"📦 Loading {len(interactions)} interactions in batches of {batch_size}...")
        
        total_batches = (len(interactions) + batch_size - 1) // batch_size
        successful_batches = 0
        total_loaded = 0
        errors = []
        
        for i in range(0, len(interactions), batch_size):
            batch = interactions[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            
            try:
                print(f"🔄 Batch {batch_num}/{total_batches} ({len(batch)} interactions)...", end=" ")
                
                # Make API request with proper error handling
                response = requests.post(
                    f"{API_BASE}/ingest/json",
                    json={"data": batch, "source": "enterprise_scale_loader"},
                    timeout=30,
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    interactions_processed = result.get("interactions_processed", 0)
                    sessions_processed = result.get("sessions_processed", 0) 
                    total_loaded += interactions_processed
                    successful_batches += 1
                    print(f"✅ {interactions_processed} interactions, {sessions_processed} sessions")
                    
                else:
                    error_detail = f"HTTP {response.status_code}"
                    try:
                        error_info = response.json()
                        error_detail = error_info.get("detail", error_detail)
                    except:
                        error_detail = response.text[:100]
                    
                    print(f"❌ {error_detail}")
                    errors.append(f"Batch {batch_num}: {error_detail}")
                    
                    # Show sample data for first few failures
                    if len(errors) <= 3:
                        print(f"   Sample data: {json.dumps(batch[0], indent=2)[:200]}...")
                        
            except Exception as e:
                error_msg = str(e)[:100]
                print(f"❌ Error: {error_msg}")
                errors.append(f"Batch {batch_num}: {error_msg}")
            
            # Progress indicator every 25 batches
            if batch_num % 25 == 0:
                success_rate = (successful_batches / batch_num) * 100
                print(f"📊 Progress: {successful_batches}/{batch_num} successful ({success_rate:.1f}%), {total_loaded} interactions loaded")
            
            # Small delay to avoid overwhelming the API
            time.sleep(0.3)
        
        # Final summary
        success_rate = (successful_batches / total_batches) * 100
        print("\n🎯 Final Results:")
        print(f"✅ Successful batches: {successful_batches}/{total_batches} ({success_rate:.1f}%)")
        print(f"📊 Total interactions loaded: {total_loaded}")
        
        if errors:
            print(f"❌ Errors encountered: {len(errors)}")
            if len(errors) <= 5:
                for error in errors:
                    print(f"   • {error}")
        
        return total_loaded
    
    def verify_enterprise_data(self):
        """Verify the enterprise data is loaded and accessible"""
        print("\n🔍 Verifying enterprise-scale data...")
        
        try:
            # Check intent performance analytics
            response = requests.get(f"{API_BASE}/analytics/intent-performance", timeout=15)
            if response.status_code == 200:
                intent_data = response.json()
                total_sessions = sum(i.get('session_count', 0) for i in intent_data)
                
                print("📊 Enterprise Scale Verification:")
                print(f"   • Total Sessions: {total_sessions:,}")
                print(f"   • Agent Types: {len(intent_data)}")
                
                # Show agent breakdown  
                print("🤖 Enterprise Agent Portfolio:")
                for intent in intent_data[:10]:  # Show first 10
                    agent_type = intent.get('intent', 'unknown').replace('_', ' ').title()
                    sessions = intent.get('session_count', 0)
                    completion_rate = intent.get('completion_rate', 0)
                    print(f"   • {agent_type}: {sessions:,} sessions ({completion_rate:.1%} success)")
                
                if len(intent_data) > 10:
                    remaining = len(intent_data) - 10
                    print(f"   ... and {remaining} more agent types")
                
                # Check session volume for total interactions
                volume_response = requests.get(f"{API_BASE}/analytics/session-volume", timeout=15)
                if volume_response.status_code == 200:
                    volume_data = volume_response.json()
                    total_interactions = sum(s.get('interaction_count', 0) for s in volume_data)
                    print(f"💬 Total Interactions: {total_interactions:,}")
                    
                    return total_sessions >= 500  # Success threshold
                else:
                    print(f"❌ Volume data error: {volume_response.status_code}")
                    return False
            else:
                print(f"❌ Analytics error: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ Verification error: {e}")
            return False

def main():
    """Main execution function"""
    print("🚀 ENTERPRISE SCALE DATA LOADER FOR AGENTIQ")
    print("=" * 70)
    
    generator = EnterpriseDataGenerator()
    
    # 1. Generate enterprise data
    print("\n1️⃣ Generating Enterprise Data...")
    interactions = generator.generate_properly_formatted_data(num_sessions=1200)
    
    # 2. Load in optimized batches  
    print("\n2️⃣ Loading to AgentIQ API...")
    total_loaded = generator.load_data_in_batches(interactions, batch_size=15)
    
    if total_loaded > 100:
        # 3. Verify enterprise capabilities
        print("\n3️⃣ Verifying Enterprise Capabilities...")
        success = generator.verify_enterprise_data()
        
        if success:
            print("\n🎉 SUCCESS: Enterprise-scale data loaded!")
            print("🏢 AgentIQ now demonstrates enterprise capabilities with:")
            print("   • 1000+ agent sessions across multiple business functions") 
            print("   • 10+ different agent types (support, sales, dev, data, etc.)")
            print("   • Realistic multi-step workflows and tool usage")
            print("   • Comprehensive failure patterns for evaluation")
            print()
            print("🔗 Enterprise Dashboard: http://localhost:8511")
            print("📊 View massive-scale analytics and loss pattern detection")
        else:
            print("\n⚠️ Data loaded but verification incomplete")
            print("🔄 Data may need time to process or trigger evaluations")
    else:
        print("\n❌ FAILED: Insufficient data loaded")
        print("🔧 Check API connectivity and field validation")

if __name__ == "__main__":
    main()