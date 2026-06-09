"""
Complete AgentIQ Integration Example
Production-ready example showing how to use AgentIQ SDK and Testing Framework

This demonstrates:
1. Agent integration with AgentIQ monitoring
2. Autonomous testing and evaluation  
3. Performance insights and recommendations
4. Continuous monitoring setup
"""

from agentiq_sdk import AgentIQ
from agent_testing_framework import AgentTester
import time

# Example 1: Simple Agent with AgentIQ Integration
class CodingAgent:
    """Example coding agent with AgentIQ monitoring"""
    
    def __init__(self):
        self.agentiq = AgentIQ(agent_id="production-coding-agent")
        self.session_id = None
    
    def start_conversation(self):
        """Start a new conversation session"""
        self.session_id = self.agentiq.start_session()
        return self.session_id
    
    def respond(self, user_input: str) -> str:
        """Generate response with AgentIQ tracking"""
        start_time = time.time()
        
        # Your agent logic here
        response = self._generate_response(user_input)
        
        # Calculate response time
        response_time = int((time.time() - start_time) * 1000)
        
        # Track with AgentIQ (non-blocking, production-safe)
        self.agentiq.track(
            user_input=user_input,
            agent_response=response,
            metadata={
                "response_time": response_time,
                "model": "claude-3.5-sonnet",
                "tools_used": ["code_execution", "web_search"]
            },
            session_id=self.session_id
        )
        
        return response
    
    def end_conversation(self):
        """End conversation and get session summary"""
        summary = self.agentiq.end_session("completed")
        return summary
    
    def get_performance_insights(self):
        """Get real-time performance insights"""
        return self.agentiq.get_insights()
    
    def _generate_response(self, user_input: str) -> str:
        """Your actual agent implementation"""
        # Simulate different types of responses
        if "debug" in user_input.lower() or "error" in user_input.lower():
            return "I can help you debug that error. The issue is likely in your variable declaration. Make sure all variables are defined before use."
        
        elif "function" in user_input.lower() or "write" in user_input.lower():
            return """Here's a function that should solve your problem:

def solve_problem(input_data):
    result = process_data(input_data)
    return result

This function takes your input, processes it, and returns the result."""
        
        elif "optimize" in user_input.lower():
            return "To optimize this code, consider: 1) Using more efficient algorithms, 2) Caching repeated calculations, 3) Reducing memory usage. Would you like me to show specific optimizations?"
        
        else:
            return "I can help you with coding questions, debugging, and optimization. What specific programming challenge are you facing?"


# Example 2: Customer Service Agent
class CustomerServiceAgent:
    """Example customer service agent with AgentIQ monitoring"""
    
    def __init__(self):
        self.agentiq = AgentIQ(agent_id="customer-service-agent")
    
    def handle_request(self, customer_input: str) -> str:
        """Handle customer request with tracking"""
        start_time = time.time()
        
        response = self._generate_response(customer_input)
        response_time = int((time.time() - start_time) * 1000)
        
        # Track with AgentIQ
        self.agentiq.track(
            user_input=customer_input,
            agent_response=response,
            metadata={"response_time": response_time, "department": "support"}
        )
        
        return response
    
    def _generate_response(self, customer_input: str) -> str:
        """Generate appropriate customer service response"""
        if "password" in customer_input.lower():
            return "I can help you reset your password. I'm sending a password reset link to your registered email address. Please check your inbox and follow the instructions."
        
        elif "billing" in customer_input.lower() or "charged" in customer_input.lower():
            return "I understand your billing concern. Let me review your account and process a refund for any incorrect charges. You should see the refund within 3-5 business days."
        
        elif "cancel" in customer_input.lower():
            return "I'm sorry to hear you're considering cancellation. Let me understand your concerns and see how I can help resolve them. What specifically is causing issues for you?"
        
        else:
            return "Thank you for contacting our support team. I'm here to help you with any questions or concerns. Can you please provide more details about what you need assistance with?"


def demo_agent_with_testing():
    """Demonstrate complete AgentIQ integration with testing"""
    
    print("🚀 AgentIQ Complete Integration Demo")
    print("=" * 50)
    
    # Create agent
    coding_agent = CodingAgent()
    
    # Start conversation
    session_id = coding_agent.start_conversation()
    print(f"📝 Started session: {session_id}")
    
    # Simulate agent interactions
    test_inputs = [
        "Help me debug this Python error: NameError: name 'x' is not defined",
        "Write a function to reverse a string",
        "How can I optimize this slow sorting algorithm?",
        "Explain the difference between lists and tuples in Python"
    ]
    
    print("\n💬 Agent Interactions:")
    for i, user_input in enumerate(test_inputs, 1):
        print(f"\nUser {i}: {user_input}")
        response = coding_agent.respond(user_input)
        print(f"Agent: {response[:100]}...")
    
    # End conversation
    summary = coding_agent.end_conversation()
    print(f"\n📊 Session Summary: {summary['interaction_count']} interactions in {summary['duration_seconds']:.1f}s")
    
    # Get performance insights
    insights = coding_agent.get_performance_insights()
    print(f"\n📈 Performance Insights: {insights['summary']}")
    
    return coding_agent


def demo_autonomous_testing():
    """Demonstrate autonomous agent testing"""
    
    print("\n🧪 Autonomous Agent Testing Demo")
    print("=" * 50)
    
    # Create agent for testing
    def test_agent_function(user_input: str) -> str:
        """Simple test agent function"""
        agent = CodingAgent()
        return agent._generate_response(user_input)
    
    # Create tester
    tester = AgentTester("demo-coding-agent")
    tester.register_agent(test_agent_function)
    
    # Run comprehensive test suite
    print("Running comprehensive test suite...")
    full_results = tester.run_full_test_suite()
    
    # Generate performance report
    print("\n📋 Performance Report:")
    report = tester.generate_performance_report(full_results)
    print(report)
    
    return full_results


def demo_continuous_monitoring():
    """Demonstrate continuous monitoring setup"""
    
    print("\n🔄 Continuous Monitoring Demo")
    print("=" * 50)
    
    # Create agent
    agent = CustomerServiceAgent()
    
    # Simulate ongoing customer interactions
    customer_inputs = [
        "I forgot my password",
        "Why was I charged twice?",
        "I want to cancel my subscription",
        "I need help with my account"
    ]
    
    print("Simulating customer service interactions...")
    for input_text in customer_inputs:
        response = agent.handle_request(input_text)
        print(f"✓ Handled: {input_text[:50]}...")
        time.sleep(1)  # Simulate real-time interactions
    
    # Get insights
    insights = agent.agentiq.get_insights()
    performance_score = agent.agentiq.get_performance_score()
    recommendations = agent.agentiq.get_recommendations()
    
    print(f"\n📊 Real-time Performance Score: {performance_score:.2f}")
    print(f"💡 Recommendations: {recommendations}")
    
    return insights


def demo_production_ready_setup():
    """Show production-ready AgentIQ setup"""
    
    print("\n🏭 Production-Ready Setup Example")
    print("=" * 50)
    
    # Production agent with comprehensive monitoring
    class ProductionAgent:
        def __init__(self, agent_id: str):
            self.agentiq = AgentIQ(
                agent_id=agent_id,
                auto_evaluate=True,  # Automatic LLM evaluation
                batch_size=50        # Efficient batching
            )
            self.tester = AgentTester(agent_id)
            
        def handle_request(self, user_input: str, metadata: dict = None) -> dict:
            """Production-ready request handling"""
            start_time = time.time()
            
            try:
                # Generate response
                response = self._generate_response(user_input)
                response_time = int((time.time() - start_time) * 1000)
                
                # Track with AgentIQ (non-blocking)
                self.agentiq.track(
                    user_input=user_input,
                    agent_response=response,
                    metadata={
                        "response_time": response_time,
                        **(metadata or {})
                    }
                )
                
                return {
                    "response": response,
                    "response_time": response_time,
                    "status": "success"
                }
                
            except Exception as e:
                # Error tracking
                self.agentiq.track(
                    user_input=user_input,
                    agent_response=f"ERROR: {str(e)}",
                    metadata={"error": str(e), "response_time": int((time.time() - start_time) * 1000)}
                )
                
                return {
                    "response": "I'm experiencing technical difficulties. Please try again.",
                    "status": "error",
                    "error": str(e)
                }
        
        def run_health_check(self) -> dict:
            """Run automated health check"""
            self.tester.register_agent(lambda x: self._generate_response(x))
            return self.tester.run_test_suite("general")
        
        def get_dashboard_url(self) -> str:
            """Get dashboard URL for monitoring"""
            return "http://localhost:8509"
        
        def _generate_response(self, user_input: str) -> str:
            # Your production agent logic here
            return f"Production response to: {user_input}"
    
    # Create production agent
    prod_agent = ProductionAgent("production-agent-v1")
    
    # Test production setup
    result = prod_agent.handle_request("Test production request")
    print(f"✅ Production request handled: {result['status']}")
    
    # Run health check
    health = prod_agent.run_health_check()
    print(f"🏥 Health Check: {health['pass_rate']:.1%} pass rate")
    
    # Show monitoring dashboard
    dashboard_url = prod_agent.get_dashboard_url()
    print(f"📊 Monitoring Dashboard: {dashboard_url}")
    
    return prod_agent


if __name__ == "__main__":
    print("🎯 AgentIQ Complete Integration Examples")
    print("=" * 60)
    
    # Run all demos
    agent = demo_agent_with_testing()
    test_results = demo_autonomous_testing()
    monitoring_insights = demo_continuous_monitoring()
    production_agent = demo_production_ready_setup()
    
    print("\n🎉 AgentIQ Integration Complete!")
    print("\n📋 Quick Start Summary:")
    print("1. Import: from agentiq_sdk import AgentIQ")
    print("2. Initialize: iq = AgentIQ(agent_id='your-agent')")
    print("3. Track: iq.track(user_input, agent_response)")
    print("4. Monitor: iq.get_insights()")
    print("5. Test: AgentTester(agent_id).run_full_test_suite()")
    print("6. Dashboard: http://localhost:8509")
    
    print("\n🚀 Your agents are now production-ready with AgentIQ!")