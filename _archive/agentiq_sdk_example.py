#!/usr/bin/env python3
"""
AgentIQ SDK Integration Example
Demonstrates how developers integrate AgentIQ into their agent systems
"""

import requests
from datetime import datetime
from typing import Dict, Any, Optional

class AgentIQSDK:
    """
    AgentIQ SDK for seamless agent monitoring integration
    Usage: Add 1-2 lines to your existing agent code for full observability
    """
    
    def __init__(self, agentiq_url: str, api_key: Optional[str] = None):
        self.url = agentiq_url.rstrip('/')
        self.api_key = api_key
        
    def trace(self, session_id: str, step_name: str, input_data: str, 
             output_data: str, metadata: Dict[str, Any] = None):
        """
        ONE LINE INTEGRATION: Add to any agent interaction
        
        agentiq.trace(session_id, step_name, user_input, agent_output, metadata)
        """
        payload = {
            "data": [{
                "session_id": session_id,
                "step_name": step_name,
                "input": input_data,
                "output": output_data,
                "metadata": {
                    "timestamp": datetime.now().isoformat(),
                    **(metadata or {})
                }
            }],
            "source": "sdk_integration"
        }
        
        try:
            response = requests.post(f"{self.url}/ingest/json", json=payload, timeout=5)
            return response.status_code == 200
        except:
            # Non-blocking: Agent continues working even if AgentIQ is down
            return False

# Initialize SDK (one line in your app)
agentiq = AgentIQSDK("https://agentiq-api-z9it.onrender.com")

# Example 1: Single Agent Integration
def my_customer_service_agent(user_message: str, session_id: str):
    """Your existing agent with AgentIQ integration"""
    
    # Your existing agent logic
    if "billing" in user_message.lower():
        agent_response = "Let me check your billing details and resolve this issue."
        success = True
    else:
        agent_response = "I can help you with various topics. Could you provide more details?"
        success = False
    
    # ONE LINE AGENTIQ INTEGRATION ⭐
    agentiq.trace(
        session_id=session_id,
        step_name="customer_service_response",
        input_data=user_message,
        output_data=agent_response,
        metadata={"successful": success, "intent": "billing" if "billing" in user_message.lower() else "general"}
    )
    
    return agent_response

# Example 2: Multi-Agent Orchestration
class MultiAgentOrchestrator:
    """Multi-agent system with AgentIQ monitoring"""
    
    def __init__(self):
        self.session_counter = 0
    
    def process_request(self, user_input: str):
        """Complete multi-agent workflow with monitoring"""
        
        session_id = f"orchestration_{self.session_counter}"
        self.session_counter += 1
        
        # Agent 1: Router
        if "payment" in user_input.lower():
            route = "payment_agent"
        elif "technical" in user_input.lower():
            route = "technical_agent"
        else:
            route = "general_agent"
        
        agentiq.trace(session_id, "router", user_input, f"Routed to: {route}", 
                     {"route": route, "confidence": 0.9})
        
        # Agent 2: Specialist
        if route == "payment_agent":
            specialist_response = "I'll help you with your payment issue. Let me access your account."
        elif route == "technical_agent":
            specialist_response = "I can assist with technical problems. What specific issue are you experiencing?"
        else:
            specialist_response = "How can I help you today?"
        
        agentiq.trace(session_id, f"{route}_response", user_input, specialist_response,
                     {"agent_type": route, "processing_time_ms": 1200})
        
        return specialist_response

# Example 3: Error Tracking
def error_prone_agent(user_input: str, session_id: str):
    """Agent that sometimes fails - AgentIQ tracks failures"""
    
    try:
        # Simulate agent processing
        if "complex" in user_input:
            raise Exception("Complex query processing failed")
        
        response = "Successfully processed your request."
        
        agentiq.trace(session_id, "process_request", user_input, response,
                     {"success": True, "processing_time": 800})
        
        return response
        
    except Exception as e:
        error_response = f"I encountered an error: {str(e)}. Please try again."
        
        agentiq.trace(session_id, "process_request", user_input, error_response,
                     {"success": False, "error": str(e), "error_type": "processing_failure"})
        
        return error_response

def demonstrate_integrations():
    """Demonstrate various AgentIQ integrations"""
    
    print("🤖 AgentIQ SDK Integration Demonstrations")
    print("=" * 50)
    
    # Demo 1: Single Agent
    print("\n1. Single Agent Integration:")
    response1 = my_customer_service_agent("I have a billing issue with my account", "demo_session_1")
    print("   User: I have a billing issue with my account")
    print(f"   Agent: {response1}")
    
    # Demo 2: Multi-Agent System
    print("\n2. Multi-Agent Orchestration:")
    orchestrator = MultiAgentOrchestrator()
    response2 = orchestrator.process_request("I'm having payment problems")
    print("   User: I'm having payment problems")
    print(f"   System: {response2}")
    
    # Demo 3: Error Handling
    print("\n3. Error Tracking:")
    response3 = error_prone_agent("This is a complex query", "demo_session_3")
    print("   User: This is a complex query")
    print(f"   Agent: {response3}")
    
    print("\n✅ All interactions logged to AgentIQ!")
    print("📊 View analytics: https://agentiq-api-z9it.onrender.com/patterns/insights/top-intents")

if __name__ == "__main__":
    demonstrate_integrations()