"""
AgentIQ SDK - Production-Ready Agent Performance Monitoring
One-line integration for any AI agent to get instant performance insights

Usage:
```python
from agentiq_sdk import AgentIQ

# Initialize (one time)
iq = AgentIQ(agent_id="your-agent-name")

# Monitor any agent interaction (one line)
iq.track(
    user_input="User's question", 
    agent_response="Agent's response",
    metadata={"tool_calls": [], "response_time": 1200}
)

# Get performance insights
insights = iq.get_insights()
```
"""

import requests
import json
import time
from datetime import datetime
from typing import Dict, List, Any, Optional
import uuid
import threading
from queue import Queue
import logging

class AgentIQ:
    """Production-ready AgentIQ SDK for agent performance monitoring"""
    
    def __init__(self, 
                 agent_id: str,
                 api_base: str = "https://agentiq-api-z9it.onrender.com",
                 auto_evaluate: bool = True,
                 batch_size: int = 10):
        """
        Initialize AgentIQ monitoring for your agent
        
        Args:
            agent_id: Unique identifier for your agent
            api_base: AgentIQ API endpoint
            auto_evaluate: Automatically evaluate responses with LLM judge
            batch_size: Batch size for data transmission
        """
        self.agent_id = agent_id
        self.api_base = api_base
        self.auto_evaluate = auto_evaluate
        self.batch_size = batch_size
        
        # Session management
        self.current_session_id = None
        self.session_start_time = None
        self.interaction_count = 0
        
        # Async batching
        self.batch_queue = Queue()
        self.batch_thread = None
        self.running = True
        
        # Start background batch processor
        self._start_batch_processor()
        
        # Setup logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(f"AgentIQ-{agent_id}")
        
        self.logger.info(f"AgentIQ initialized for agent: {agent_id}")
    
    def start_session(self) -> str:
        """Start a new agent session"""
        self.current_session_id = f"{self.agent_id}-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        self.session_start_time = time.time()
        self.interaction_count = 0
        
        self.logger.info(f"Started session: {self.current_session_id}")
        return self.current_session_id
    
    def track(self, 
              user_input: str, 
              agent_response: str,
              metadata: Optional[Dict] = None,
              session_id: Optional[str] = None) -> bool:
        """
        Track an agent interaction (non-blocking, production-ready)
        
        Args:
            user_input: The user's input/question
            agent_response: The agent's response
            metadata: Optional metadata (tool_calls, response_time, etc.)
            session_id: Optional session ID (auto-generated if not provided)
        
        Returns:
            bool: True if successfully queued for tracking
        """
        try:
            # Auto-start session if needed
            if not session_id and not self.current_session_id:
                self.start_session()
            
            session_id = session_id or self.current_session_id
            self.interaction_count += 1
            
            # Prepare interaction data
            interaction = {
                "user_input": user_input,
                "agent_response": agent_response,
                "session_id": session_id,
                "agent_id": self.agent_id,
                "timestamp": datetime.now().isoformat(),
                "workflow_step": self.interaction_count,
                "response_time_ms": metadata.get("response_time", 1000) if metadata else 1000,
                "tool_calls": json.dumps(metadata.get("tool_calls", [])) if metadata else "[]",
                "intent": self._classify_intent(user_input),
                "metadata": json.dumps(metadata or {})
            }
            
            # Add to batch queue (non-blocking)
            self.batch_queue.put(interaction)
            
            return True
            
        except Exception as e:
            # Never fail the agent - just log and continue
            self.logger.error(f"AgentIQ tracking error (non-blocking): {e}")
            return False
    
    def end_session(self, session_outcome: str = "completed") -> Dict:
        """End the current session and get summary"""
        if not self.current_session_id:
            return {"error": "No active session"}
        
        session_duration = time.time() - self.session_start_time if self.session_start_time else 0
        
        summary = {
            "session_id": self.current_session_id,
            "agent_id": self.agent_id,
            "duration_seconds": session_duration,
            "interaction_count": self.interaction_count,
            "outcome": session_outcome,
            "ended_at": datetime.now().isoformat()
        }
        
        # Queue session summary
        self.batch_queue.put({"session_summary": summary})
        
        self.logger.info(f"Ended session: {self.current_session_id} ({self.interaction_count} interactions)")
        
        # Reset session
        self.current_session_id = None
        self.session_start_time = None
        self.interaction_count = 0
        
        return summary
    
    def get_insights(self) -> Dict[str, Any]:
        """Get real-time performance insights for your agent"""
        try:
            # Get agent-specific analytics
            endpoints = [
                "/analytics/intent-performance",
                "/analytics/quality-by-intent", 
                "/analytics/session-volume",
                "/analytics/dropoff-analysis"
            ]
            
            insights = {
                "agent_id": self.agent_id,
                "timestamp": datetime.now().isoformat()
            }
            
            # Fetch data from all endpoints
            for endpoint in endpoints:
                try:
                    response = requests.get(f"{self.api_base}{endpoint}", timeout=5)
                    if response.status_code == 200:
                        data = response.json()
                        endpoint_name = endpoint.split("/")[-1].replace("-", "_")
                        insights[endpoint_name] = data
                except:
                    pass
            
            # Calculate key metrics
            insights["summary"] = self._calculate_summary_metrics(insights)
            
            return insights
            
        except Exception as e:
            self.logger.error(f"Error getting insights: {e}")
            return {"error": str(e)}
    
    def get_performance_score(self) -> float:
        """Get overall performance score (0-1)"""
        insights = self.get_insights()
        
        if "quality_by_intent" in insights and insights["quality_by_intent"]:
            quality_scores = [q["avg_quality_score"] for q in insights["quality_by_intent"]]
            return sum(quality_scores) / len(quality_scores)
        
        return 0.0
    
    def get_recommendations(self) -> List[str]:
        """Get actionable improvement recommendations"""
        insights = self.get_insights()
        recommendations = []
        
        # Performance-based recommendations
        performance_score = self.get_performance_score()
        
        if performance_score < 0.6:
            recommendations.append("🔴 CRITICAL: Review agent responses - quality score below 60%")
        elif performance_score < 0.75:
            recommendations.append("⚠️ MEDIUM: Optimize agent responses - quality score could be improved")
        else:
            recommendations.append("✅ GOOD: Agent performance is solid - continue monitoring")
        
        # Intent-specific recommendations
        if "intent_performance" in insights:
            for intent_data in insights["intent_performance"]:
                if intent_data["completion_rate"] < 0.7:
                    recommendations.append(f"🎯 Improve {intent_data['intent']} handling - {intent_data['completion_rate']:.1%} completion rate")
        
        return recommendations
    
    def _classify_intent(self, user_input: str) -> str:
        """Simple intent classification based on keywords"""
        user_input_lower = user_input.lower()
        
        # Programming/coding intents
        code_keywords = ["code", "function", "debug", "error", "python", "javascript", "bug", "api"]
        if any(keyword in user_input_lower for keyword in code_keywords):
            return "code_generation"
        
        # Customer service intents
        support_keywords = ["help", "problem", "issue", "support", "account", "billing", "password"]
        if any(keyword in user_input_lower for keyword in support_keywords):
            return "customer_support"
        
        # Data analysis intents
        data_keywords = ["analyze", "data", "chart", "report", "metrics", "dashboard"]
        if any(keyword in user_input_lower for keyword in data_keywords):
            return "data_analysis"
        
        # Sales/BDR intents
        sales_keywords = ["lead", "prospect", "sale", "demo", "pricing", "qualified"]
        if any(keyword in user_input_lower for keyword in sales_keywords):
            return "sales_bdr"
        
        return "general"
    
    def _start_batch_processor(self):
        """Start background thread for batch processing"""
        def batch_processor():
            batch = []
            
            while self.running:
                try:
                    # Collect batch
                    while len(batch) < self.batch_size and not self.batch_queue.empty():
                        batch.append(self.batch_queue.get(timeout=1))
                    
                    # Send batch if we have data
                    if batch:
                        self._send_batch(batch)
                        batch = []
                    
                    time.sleep(1)  # Prevent busy waiting
                    
                except Exception as e:
                    self.logger.error(f"Batch processor error: {e}")
                    time.sleep(5)  # Back off on errors
        
        self.batch_thread = threading.Thread(target=batch_processor, daemon=True)
        self.batch_thread.start()
    
    def _send_batch(self, batch: List[Dict]):
        """Send batch of interactions to AgentIQ API"""
        try:
            # Separate session summaries from interactions
            interactions = [item for item in batch if "session_summary" not in item]
            session_summaries = [item["session_summary"] for item in batch if "session_summary" in item]
            
            # Send interactions
            if interactions:
                payload = {"data": interactions}
                response = requests.post(
                    f"{self.api_base}/ingest/json", 
                    json=payload, 
                    timeout=10
                )
                
                if response.status_code == 200:
                    self.logger.info(f"Sent batch of {len(interactions)} interactions")
                else:
                    self.logger.warning(f"Batch send failed: {response.status_code}")
            
            # Send session summaries
            for summary in session_summaries:
                try:
                    requests.post(f"{self.api_base}/sessions/end", json=summary, timeout=5)
                except:
                    pass  # Session summaries are optional
                    
        except Exception as e:
            self.logger.error(f"Error sending batch: {e}")
    
    def _calculate_summary_metrics(self, insights: Dict) -> Dict:
        """Calculate summary metrics from insights"""
        summary = {}
        
        try:
            # Quality metrics
            if "quality_by_intent" in insights and insights["quality_by_intent"]:
                quality_data = insights["quality_by_intent"]
                total_evals = sum(q["sample_size"] for q in quality_data)
                weighted_quality = sum(q["avg_quality_score"] * q["sample_size"] for q in quality_data) / max(total_evals, 1)
                
                summary["overall_quality_score"] = round(weighted_quality, 3)
                summary["total_evaluations"] = total_evals
            
            # Performance metrics
            if "intent_performance" in insights and insights["intent_performance"]:
                intent_data = insights["intent_performance"]
                total_sessions = sum(i["session_count"] for i in intent_data)
                avg_completion = sum(i["completion_rate"] for i in intent_data) / len(intent_data)
                
                summary["total_sessions"] = total_sessions
                summary["average_completion_rate"] = round(avg_completion, 3)
            
            # Volume metrics
            if "session_volume" in insights and insights["session_volume"]:
                volume_data = insights["session_volume"]
                total_interactions = sum(s["interaction_count"] for s in volume_data)
                summary["total_interactions"] = total_interactions
            
        except Exception as e:
            summary["error"] = str(e)
        
        return summary
    
    def __del__(self):
        """Cleanup on destruction"""
        self.running = False
        if self.batch_thread and self.batch_thread.is_alive():
            self.batch_thread.join(timeout=2)


# Convenience functions for quick integration
def track_interaction(agent_id: str, user_input: str, agent_response: str, **kwargs) -> bool:
    """Quick function to track a single interaction"""
    iq = AgentIQ(agent_id)
    return iq.track(user_input, agent_response, kwargs)

def get_agent_insights(agent_id: str) -> Dict:
    """Quick function to get agent insights"""
    iq = AgentIQ(agent_id)
    return iq.get_insights()