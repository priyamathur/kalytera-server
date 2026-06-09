"""
Production Demo Data Generator for AgentIQ
Creates 500 realistic agent sessions for deployment demonstration
"""

import requests
import json
import random
from datetime import datetime, timedelta
from typing import Dict, List
import time

class ProductionDemoDataGenerator:
    """Generate realistic demo data for production deployment"""
    
    def __init__(self, api_base_url: str):
        self.api_base_url = api_base_url.rstrip('/')
        
        # Realistic conversation templates by intent
        self.conversation_templates = {
            "billing": [
                {
                    "user_inputs": [
                        "I have a question about my last bill",
                        "There's a charge for ${amount} that I don't recognize", 
                        "Can you explain what this charge is for?",
                        "I want to dispute this billing charge",
                        "Why did my bill go up this month?"
                    ],
                    "agent_responses": [
                        "I'd be happy to help you with your billing question. Let me pull up your account details.",
                        "I can see that charge on your account. Let me look up the details of that transaction for you.",
                        "I see the charge you're referring to. Let me explain what this covers.",
                        "I understand your concern about this charge. Let me investigate this for you.",
                        "I apologize, but I'm currently unable to access the billing system to get the detailed breakdown."
                    ],
                    "tools": ["billing_api", "account_lookup", "payment_processor"],
                    "common_failures": ["tool_failure", "incomplete", "wrong_answer"]
                }
            ],
            "refunds": [
                {
                    "user_inputs": [
                        "I want a refund for this purchase",
                        "How do I return this product?",
                        "Can I get my money back?",
                        "I'm not satisfied with this service",
                        "I want to cancel and get a refund"
                    ],
                    "agent_responses": [
                        "I can help you with your refund request. Let me review your purchase details.",
                        "I understand you'd like to return this item. Let me check our refund policy for this product.",
                        "I'll be happy to process your refund. Let me verify your eligibility.",
                        "I see you're not satisfied with your purchase. Let me see what options we have.",
                        "I apologize that you're not happy with the service. Let me check your refund options."
                    ],
                    "tools": ["refund_processor", "order_lookup", "policy_checker"],
                    "common_failures": ["wrong_answer", "goal_drift", "incomplete"]
                }
            ],
            "subscriptions": [
                {
                    "user_inputs": [
                        "I want to cancel my subscription",
                        "How do I upgrade my plan?",
                        "When does my subscription renew?",
                        "I want to pause my subscription",
                        "Can I change my billing cycle?"
                    ],
                    "agent_responses": [
                        "I can help you manage your subscription. Let me pull up your current plan details.",
                        "I'd be happy to help you with your subscription changes.",
                        "Let me check your subscription status and available options.",
                        "I can assist you with modifying your subscription settings.",
                        "I'll help you with your subscription management. Let me access your account."
                    ],
                    "tools": ["subscription_manager", "billing_cycle_api", "plan_changer"],
                    "common_failures": ["tool_failure", "context_loss", "incomplete"]
                }
            ],
            "account_recovery": [
                {
                    "user_inputs": [
                        "I can't log into my account",
                        "I forgot my password",
                        "I need to reset my account",
                        "My account is locked",
                        "I can't access my account"
                    ],
                    "agent_responses": [
                        "I can help you regain access to your account. Let me verify your identity first.",
                        "I'll assist you with password recovery. I need to confirm some details first.",
                        "Let me help you reset your account access. First, I need to verify who you are.",
                        "I can help unlock your account. For security, I need to verify your identity.",
                        "I'll help you recover your account access safely and securely."
                    ],
                    "tools": ["identity_verifier", "password_reset", "account_unlock", "security_check"],
                    "common_failures": ["incomplete", "hallucination", "wrong_answer"]
                }
            ],
            "general_inquiry": [
                {
                    "user_inputs": [
                        "What are your business hours?",
                        "How do I contact support?",
                        "Do you have a mobile app?",
                        "What services do you offer?",
                        "How does your platform work?"
                    ],
                    "agent_responses": [
                        "Our business hours are Monday through Friday, 9 AM to 6 PM EST.",
                        "You can contact our support team through several channels.",
                        "Yes, we have mobile apps available for both iOS and Android.",
                        "We offer a comprehensive platform for agent observability and analytics.",
                        "Our platform helps you monitor and improve your AI agent performance."
                    ],
                    "tools": ["knowledge_base", "contact_info", "app_store_api"],
                    "common_failures": ["hallucination", "wrong_answer", "context_loss"]
                }
            ]
        }
    
    def generate_realistic_session(self, session_id: str, intent: str) -> List[Dict]:
        """Generate realistic conversation session"""
        
        template = self.conversation_templates[intent][0]
        
        # Random conversation length (1-7 steps)
        steps = random.randint(1, 7)
        interactions = []
        
        base_time = datetime.now() - timedelta(
            hours=random.randint(1, 168),  # Last week
            minutes=random.randint(0, 59)
        )
        
        for step in range(1, steps + 1):
            # Select appropriate user input and agent response
            user_input = random.choice(template["user_inputs"])
            agent_response = random.choice(template["agent_responses"])
            
            # Add variability to responses
            if step > 1:
                if intent == "billing":
                    amounts = ["$47.99", "$23.50", "$89.95", "$15.00", "$199.99"]
                    user_input = user_input.replace("${amount}", random.choice(amounts))
            
            # Determine if tools are used
            tools_used = []
            if random.random() < 0.6:  # 60% chance of tool usage
                tools_used = random.sample(template["tools"], random.randint(1, 2))
            
            # Simulate response times (realistic distribution)
            response_time = max(300, int(random.lognormvariate(7.0, 0.5)))
            
            # Simulate token usage
            tokens = random.randint(20, 80)
            
            # Determine failure patterns
            tool_calls = None
            if tools_used:
                if random.random() < 0.3:  # 30% chance of tool failure
                    tool_calls = f"Error: {random.choice(tools_used)} timeout after 30 seconds"
                else:
                    tool_calls = json.dumps(tools_used)
            
            interaction = {
                "session_id": session_id,
                "timestamp": (base_time + timedelta(minutes=step * 2)).isoformat() + "Z",
                "user_input": user_input,
                "agent_response": agent_response,
                "intent": intent,
                "workflow_step": step,
                "response_time_ms": response_time,
                "tokens_used": tokens
            }
            
            if tool_calls:
                interaction["tool_calls"] = tool_calls
            
            interactions.append(interaction)
        
        return interactions
    
    def generate_demo_sessions(self, total_sessions: int = 500) -> List[List[Dict]]:
        """Generate specified number of demo sessions"""
        
        print(f"🏭 Generating {total_sessions} demo sessions...")
        
        # Intent distribution (realistic business distribution)
        intent_distribution = {
            "billing": 0.30,      # 30% - Most common
            "refunds": 0.25,      # 25% - High frequency  
            "subscriptions": 0.20, # 20% - Regular occurrence
            "account_recovery": 0.15, # 15% - Security/access issues
            "general_inquiry": 0.10   # 10% - Least specific
        }
        
        sessions = []
        
        for i in range(total_sessions):
            # Select intent based on distribution
            rand = random.random()
            cumulative = 0
            selected_intent = "general_inquiry"  # Default
            
            for intent, probability in intent_distribution.items():
                cumulative += probability
                if rand <= cumulative:
                    selected_intent = intent
                    break
            
            # Generate session
            session_id = f"demo_session_{i+1:04d}"
            session_interactions = self.generate_realistic_session(session_id, selected_intent)
            sessions.append(session_interactions)
            
            if (i + 1) % 50 == 0:
                print(f"Generated {i+1}/{total_sessions} sessions...")
        
        print(f"✅ Generated {total_sessions} sessions with realistic conversation patterns")
        return sessions
    
    def upload_sessions_to_production(self, sessions: List[List[Dict]], batch_size: int = 25):
        """Upload generated sessions to production API"""
        
        print(f"🚀 Uploading {len(sessions)} sessions to {self.api_base_url}...")
        
        uploaded_sessions = 0
        failed_uploads = 0
        
        for i in range(0, len(sessions), batch_size):
            batch = sessions[i:i + batch_size]
            
            # Flatten interactions for API
            batch_interactions = []
            for session in batch:
                batch_interactions.extend(session)
            
            try:
                response = requests.post(
                    f"{self.api_base_url}/ingest/json",
                    json={
                        "data": batch_interactions,
                        "source": "production_demo",
                        "format_hint": "json"
                    },
                    timeout=30
                )
                response.raise_for_status()
                
                result = response.json()
                uploaded_sessions += result.get("sessions_processed", 0)
                
                print(f"📤 Uploaded batch {i//batch_size + 1}: {result.get('sessions_processed', 0)} sessions")
                
                # Rate limiting
                time.sleep(1)
                
            except Exception as e:
                print(f"❌ Failed to upload batch {i//batch_size + 1}: {e}")
                failed_uploads += len(batch)
        
        print(f"✅ Upload complete: {uploaded_sessions} sessions uploaded, {failed_uploads} failed")
        return uploaded_sessions
    
    def trigger_evaluation_and_analysis(self):
        """Trigger evaluation and pattern analysis on uploaded data"""
        
        print("🧠 Triggering evaluation and pattern analysis...")
        
        try:
            # Trigger batch evaluation
            eval_response = requests.post(
                f"{self.api_base_url}/evaluation/evaluate-batch",
                params={"hours_back": 24},
                timeout=60
            )
            
            if eval_response.status_code == 200:
                eval_result = eval_response.json()
                print(f"✅ Evaluation complete: {eval_result.get('evaluations_completed', 0)} interactions evaluated")
            else:
                print(f"⚠️ Evaluation failed: {eval_response.status_code}")
            
            # Trigger pattern analysis
            pattern_response = requests.post(
                f"{self.api_base_url}/patterns/analyze",
                params={"hours_back": 24, "min_pattern_count": 3},
                timeout=60
            )
            
            if pattern_response.status_code == 200:
                pattern_result = pattern_response.json()
                print(f"✅ Pattern analysis complete: {pattern_result.get('patterns_detected', 0)} patterns detected")
            else:
                print(f"⚠️ Pattern analysis failed: {pattern_response.status_code}")
                
        except Exception as e:
            print(f"❌ Post-processing failed: {e}")
    
    def generate_and_upload_demo_data(self, total_sessions: int = 500):
        """Complete demo data generation and upload process"""
        
        print("🎯 AgentIQ Production Demo Data Generation")
        print("=" * 50)
        
        start_time = datetime.now()
        
        # Generate sessions
        sessions = self.generate_demo_sessions(total_sessions)
        
        # Upload to production
        uploaded = self.upload_sessions_to_production(sessions)
        
        # Wait a bit for processing
        print("⏳ Waiting for data processing...")
        time.sleep(10)
        
        # Trigger analysis
        self.trigger_evaluation_and_analysis()
        
        # Summary
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print("\n" + "=" * 50)
        print("🎉 Demo Data Generation Complete!")
        print(f"Sessions generated: {len(sessions)}")
        print(f"Sessions uploaded: {uploaded}")
        print(f"Duration: {duration:.1f} seconds")
        print(f"Production URL: {self.api_base_url}")

def main():
    """Generate and upload production demo data"""
    
    import sys
    
    # Get production URL (default to localhost for testing)
    api_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    session_count = int(sys.argv[2]) if len(sys.argv) > 2 else 500
    
    print(f"Target API: {api_url}")
    print(f"Sessions to generate: {session_count}")
    
    # Generate and upload
    generator = ProductionDemoDataGenerator(api_url)
    generator.generate_and_upload_demo_data(session_count)

if __name__ == "__main__":
    main()