"""
Load 10,000 demo sessions into deployed Kalytera instance
Simulates realistic agent interactions for testing the production system
"""

import requests
import time
import random
from datetime import datetime, timedelta
from typing import List, Dict
import uuid

class DemoDataLoader:
    def __init__(self, api_base_url: str):
        self.api_base_url = api_base_url.rstrip('/')
        self.session_count = 0
        
    def generate_session_data(self) -> List[Dict]:
        """Generate realistic agent interaction data for a session"""
        
        # Intent types with realistic distributions
        intents = {
            'billing': 0.25,
            'refunds': 0.15, 
            'subscriptions': 0.20,
            'account_recovery': 0.10,
            'technical_support': 0.15,
            'general_enquiry': 0.15
        }
        
        # Sample user inputs by intent
        user_inputs = {
            'billing': [
                "I have a billing dispute on my account",
                "Why was I charged twice this month?",
                "I need to update my payment method",
                "There's an error on my invoice"
            ],
            'refunds': [
                "I want to request a refund",
                "I was charged for something I didn't order",
                "How do I get my money back?",
                "I need a refund for last month's charge"
            ],
            'subscriptions': [
                "I want to upgrade my plan",
                "How do I cancel my subscription?",
                "What plans do you offer?",
                "I need to downgrade my account"
            ],
            'account_recovery': [
                "I can't access my account",
                "I forgot my password",
                "My account has been locked",
                "I need help logging in"
            ],
            'technical_support': [
                "The app is not working properly",
                "I'm getting error messages",
                "The feature is broken",
                "Something is not loading correctly"
            ],
            'general_enquiry': [
                "How does this work?",
                "I have some questions",
                "Can you help me understand this feature?",
                "I need general information"
            ]
        }
        
        # Sample agent responses
        agent_responses = [
            "I'd be happy to help you with that. Let me look into your account details.",
            "I understand your concern. Let me check what I can do for you.",
            "Thank you for contacting us. I can assist you with this request.",
            "I can help you resolve this issue. Let me gather some information first.",
            "I'll be glad to help you with that. Let me review your account.",
            "I can see what you're referring to. Let me help you fix this."
        ]
        
        # Pick intent based on probability
        intent = random.choices(list(intents.keys()), weights=list(intents.values()))[0]
        
        # Generate 1-5 interactions per session
        num_interactions = random.choices([1, 2, 3, 4, 5], weights=[0.1, 0.3, 0.4, 0.15, 0.05])[0]
        
        session_id = str(uuid.uuid4())
        interactions = []
        
        for step in range(1, num_interactions + 1):
            # Pick realistic user input for this intent
            if step == 1:
                user_input = random.choice(user_inputs[intent])
            else:
                user_input = random.choice([
                    "Yes, that would help",
                    "Can you explain more?", 
                    "I still need help with this",
                    "What are my options?",
                    "That doesn't solve my problem"
                ])
            
            agent_response = random.choice(agent_responses)
            
            # Simulate tool usage
            tool_calls = None
            if intent == 'billing':
                tool_calls = '["billing_api", "payment_lookup"]'
            elif intent == 'refunds':
                tool_calls = '["refund_api", "transaction_history"]'
            elif intent == 'subscriptions':
                tool_calls = '["subscription_api", "plan_manager"]'
            elif intent == 'account_recovery':
                tool_calls = '["auth_api", "password_reset"]'
            elif intent == 'technical_support':
                tool_calls = '["diagnostics_api", "error_logs"]'
            
            # Realistic response times (slower for complex queries)
            base_response_time = random.randint(500, 2000)
            if step > 1:
                base_response_time += random.randint(0, 1000)  # Longer for follow-ups
            
            interaction = {
                "session_id": session_id,
                "timestamp": (datetime.now() - timedelta(
                    minutes=random.randint(0, 60*24*7),  # Random time in last week
                    seconds=step*30  # Interactions 30 seconds apart
                )).isoformat(),
                "user_input": user_input,
                "agent_response": agent_response,
                "response_time_ms": base_response_time,
                "workflow_step": step,
                "tool_calls": tool_calls,
                "tokens_used": random.randint(20, 150),
                "error_occurred": random.random() < 0.05,  # 5% error rate
                "error_message": "API timeout" if random.random() < 0.02 else None
            }
            
            interactions.append(interaction)
        
        return interactions
    
    def send_trace(self, interaction: Dict) -> bool:
        """Send a trace to the deployed API"""
        try:
            response = requests.post(
                f"{self.api_base_url}/api/trace",
                json=interaction,
                timeout=10
            )
            
            if response.status_code == 200:
                return True
            else:
                print(f"❌ Trace failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Request failed: {e}")
            return False
    
    def load_demo_sessions(self, num_sessions: int = 10000, batch_size: int = 100):
        """Load demo sessions into the deployed system"""
        
        print(f"🚀 Loading {num_sessions:,} demo sessions to {self.api_base_url}")
        print(f"📊 Processing in batches of {batch_size}")
        
        total_interactions = 0
        successful_traces = 0
        failed_traces = 0
        
        for batch in range(0, num_sessions, batch_size):
            batch_end = min(batch + batch_size, num_sessions)
            print(f"\n📈 Processing sessions {batch+1:,} to {batch_end:,}")
            
            batch_interactions = 0
            batch_successes = 0
            
            for session_num in range(batch, batch_end):
                # Generate session data
                interactions = self.generate_session_data()
                batch_interactions += len(interactions)
                
                # Send each interaction
                for interaction in interactions:
                    if self.send_trace(interaction):
                        batch_successes += 1
                        successful_traces += 1
                    else:
                        failed_traces += 1
                    
                    # Small delay to avoid overwhelming the API
                    time.sleep(0.01)
                
                # Progress update every 20 sessions
                if (session_num + 1) % 20 == 0:
                    success_rate = (batch_successes / max(batch_interactions, 1)) * 100
                    print(f"   Session {session_num + 1:,}: {success_rate:.1f}% success rate")
            
            total_interactions += batch_interactions
            
            # Batch summary
            batch_success_rate = (batch_successes / max(batch_interactions, 1)) * 100
            print(f"✅ Batch {batch//batch_size + 1} complete: {batch_successes:,}/{batch_interactions:,} traces sent ({batch_success_rate:.1f}%)")
            
            # Brief pause between batches
            time.sleep(1)
        
        # Final summary
        print("\n🎉 Demo data loading complete!")
        print(f"📊 Total sessions: {num_sessions:,}")
        print(f"📊 Total interactions: {total_interactions:,}")
        print(f"✅ Successful traces: {successful_traces:,}")
        print(f"❌ Failed traces: {failed_traces:,}")
        
        if total_interactions > 0:
            overall_success_rate = (successful_traces / total_interactions) * 100
            print(f"📈 Overall success rate: {overall_success_rate:.1f}%")
        
        # Test the API endpoints
        print("\n🧪 Testing API endpoints...")
        self.test_api_endpoints()
    
    def test_api_endpoints(self):
        """Test key API endpoints after loading data"""
        
        endpoints_to_test = [
            "/health",
            "/analytics/dashboard-summary",
            "/patterns/insights/top-intents",
            "/evaluation/failure-stats",
            "/analytics/session-volume"
        ]
        
        for endpoint in endpoints_to_test:
            try:
                response = requests.get(f"{self.api_base_url}{endpoint}", timeout=10)
                if response.status_code == 200:
                    print(f"✅ {endpoint}: OK")
                else:
                    print(f"⚠️ {endpoint}: {response.status_code}")
            except Exception as e:
                print(f"❌ {endpoint}: {e}")

def main():
    """Main function to load demo data"""
    
    # Get API URL from environment or use default
    import os
    api_url = os.getenv("API_BASE_URL", "http://localhost:8000")
    
    print("🤖 Kalytera Demo Data Loader")
    print("=" * 50)
    
    # Option to override URL
    if len(os.sys.argv) > 1:
        api_url = os.sys.argv[1]
    
    print(f"🎯 Target API: {api_url}")
    
    # Test API connectivity first
    try:
        response = requests.get(f"{api_url}/health", timeout=5)
        if response.status_code == 200:
            print("✅ API is responsive")
        else:
            print(f"⚠️ API returned {response.status_code}")
            return
    except Exception as e:
        print(f"❌ Cannot connect to API: {e}")
        return
    
    # Create loader and start
    loader = DemoDataLoader(api_url)
    
    # Load demo sessions (default 10,000)
    num_sessions = int(os.getenv("DEMO_SESSIONS", "10000"))
    loader.load_demo_sessions(num_sessions)

if __name__ == "__main__":
    main()