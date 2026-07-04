"""
Kalytera Judge Module - Main interface for evaluation system
Exports necessary components for tests and background jobs
"""

from api.database import SessionLocal
import os

# Lazy import to avoid circular dependencies
_judge_instance = None

def get_judge_instance():
    """Get the judge instance, creating it if necessary"""
    global _judge_instance
    if _judge_instance is None:
        from evaluation.agent_judge import AgentJudge
        _judge_instance = AgentJudge(api_key=os.getenv('ANTHROPIC_API_KEY'))
    return _judge_instance

async def evaluate_interaction(
    log_id: str,
    user_input: str,
    agent_response: str,
    conversation_context: list = None,
    tool_results: str = None,
    intent: str = None,
    session_id: str = None
):
    """
    Evaluate a single agent interaction
    Wrapper function that tests expect
    """
    judge = get_judge_instance()
    return await judge.evaluate_interaction(
        user_input=user_input,
        agent_response=agent_response,
        conversation_context=conversation_context or [],
        tool_results=tool_results,
        intent=intent,
        session_id=session_id,
        log_id=log_id
    )

def get_agent_config(agent_id: str):
    """
    Get agent-specific configuration
    Placeholder function that tests expect
    """
    # Default configuration for healthcare industry
    return {
        'accuracy_weight': 0.5,
        'safety_weight': 0.3,
        'completeness_weight': 0.1,
        'decision_quality_weight': 0.1
    }

# Export everything tests expect
__all__ = ['SessionLocal', 'evaluate_interaction', 'get_agent_config']