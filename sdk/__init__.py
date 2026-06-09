"""
AgentIQ SDK - Lightweight tracing for production AI agents

Usage:
    import agentiq
    
    # One line, fire-and-forget tracing
    agentiq.trace(
        session_id="session_123",
        user_input="Help me with my billing",
        agent_response="I can help you with that...",
        response_time_ms=1200
    )
    
The trace call:
- Never blocks your agent 
- Never raises exceptions
- Fails silently if AgentIQ is down
- Logs locally for debugging
"""

from .client import trace, configure

__version__ = "1.0.0"
__all__ = ["trace", "configure"]