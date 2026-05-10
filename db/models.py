from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

Base = declarative_base()

class AgentLog(Base):
    """Raw agent interaction logs - every request/response pair"""
    __tablename__ = "agent_logs"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    user_input = Column(Text, nullable=False)
    agent_response = Column(Text, nullable=False)
    intent = Column(String, nullable=True)  # classified intent
    workflow_step = Column(Integer, default=1)  # step in conversation
    tool_calls = Column(Text, nullable=True)  # JSON string of tool calls made
    response_time_ms = Column(Integer, nullable=False)
    tokens_used = Column(Integer, nullable=True)
    error_occurred = Column(Boolean, default=False)
    error_message = Column(Text, nullable=True)
    
# Relationships removed for simplicity - not needed for core functionality
    
    def __repr__(self):
        return f"<AgentLog(session_id={self.session_id}, intent={self.intent}, step={self.workflow_step})>"


class SessionSummary(Base):
    """Aggregated session-level analytics"""
    __tablename__ = "session_summaries"
    
    id = Column(String, primary_key=True)  # same as session_id
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    total_interactions = Column(Integer, default=0)
    primary_intent = Column(String, nullable=True)  # most likely intent for session
    intent_confidence = Column(Float, nullable=True)  # confidence in intent classification
    workflow_completed = Column(Boolean, default=False)
    drop_off_step = Column(Integer, nullable=True)  # step where user dropped off
    total_tokens = Column(Integer, default=0)
    avg_response_time_ms = Column(Float, nullable=True)
    errors_count = Column(Integer, default=0)
    success_score = Column(Float, nullable=True)  # overall session success (0-1)
    
# Relationships removed for simplicity - not needed for core functionality
    
    def __repr__(self):
        return f"<SessionSummary(id={self.id}, intent={self.primary_intent}, completed={self.workflow_completed})>"


class EvalResult(Base):
    """LLM-as-a-Judge evaluation results for each interaction"""
    __tablename__ = "eval_results"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_log_id = Column(String, ForeignKey("agent_logs.id"), nullable=False)
    evaluated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Core evaluation metrics (0-1 scale)
    accuracy_score = Column(Float, nullable=False)  # factual correctness
    relevance_score = Column(Float, nullable=False)  # relevance to user query
    helpfulness_score = Column(Float, nullable=False)  # how helpful the response is
    goal_alignment_score = Column(Float, nullable=False)  # alignment with user intent
    
    # Overall quality score (weighted average)
    overall_score = Column(Float, nullable=False)
    
    # Evaluation reasoning and feedback
    evaluation_reasoning = Column(Text, nullable=True)  # why these scores
    improvement_suggestions = Column(Text, nullable=True)  # what could be better
    
    # Evaluation metadata
    evaluator_model = Column(String, default="claude-3-sonnet", nullable=False)
    evaluation_version = Column(String, default="1.0", nullable=False)
    
    def __repr__(self):
        return f"<EvalResult(log_id={self.agent_log_id}, overall_score={self.overall_score})>"


class LossPattern(Base):
    """Automatically detected patterns where agents consistently fail"""
    __tablename__ = "loss_patterns"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    detected_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    pattern_type = Column(String, nullable=False)  # 'intent', 'workflow_step', 'tool_call', 'time_based'
    
    # Pattern identification
    pattern_name = Column(String, nullable=False)  # human-readable pattern name
    pattern_description = Column(Text, nullable=False)  # detailed description
    
    # Pattern specifics
    intent_type = Column(String, nullable=True)  # if pattern is intent-specific
    workflow_step = Column(Integer, nullable=True)  # if pattern is step-specific
    tool_name = Column(String, nullable=True)  # if pattern is tool-specific
    
    # Pattern metrics
    failure_count = Column(Integer, nullable=False)  # how many failures observed
    total_occurrences = Column(Integer, nullable=False)  # total times pattern occurred
    failure_rate = Column(Float, nullable=False)  # failure_count / total_occurrences
    avg_quality_score = Column(Float, nullable=True)  # average eval score for this pattern
    
    # Root cause analysis
    root_cause = Column(String, nullable=True)  # identified root cause category
    root_cause_confidence = Column(Float, nullable=True)  # confidence in root cause (0-1)
    suggested_fix = Column(Text, nullable=True)  # recommended action to fix
    
    # Pattern status
    is_active = Column(Boolean, default=True)  # whether pattern is still occurring
    severity = Column(String, default="medium")  # low, medium, high, critical
    
    def __repr__(self):
        return f"<LossPattern(name={self.pattern_name}, failure_rate={self.failure_rate}, severity={self.severity})>"