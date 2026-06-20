"""
Four tables. Nothing more.
AgentLog ← tracer.py only
EvalResult ← judge.py only
LossPattern ← analyzer.py only
AgentQualityConfig ← dashboard weight editor
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Float, Integer, String, Text
from sqlalchemy import DateTime as SADateTime
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id = Column(String, primary_key=True, default=_uuid)
    agent_id = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=False, index=True)
    step_number = Column(Integer, nullable=False)
    step_name = Column(String, nullable=False)
    input = Column(Text, nullable=False)
    output = Column(Text, nullable=False)
    tool_calls = Column(Text, nullable=True)   # JSON: [{name, input, output, success, latency_ms}]
    latency_ms = Column(Integer, nullable=False, default=0)
    session_ended = Column(Boolean, default=False, nullable=False)
    timestamp = Column(SADateTime(timezone=True), default=_now, nullable=False)
    step_metadata = Column(Text, nullable=True)  # JSON: developer-provided context


class EvalResult(Base):
    __tablename__ = "eval_results"

    id = Column(String, primary_key=True, default=_uuid)
    log_id = Column(String, nullable=False, index=True)   # FK to AgentLog.id
    session_id = Column(String, nullable=False, index=True)
    agent_id = Column(String, nullable=False, index=True)
    accuracy = Column(Float, nullable=False)
    goal_alignment = Column(Float, nullable=False)
    decision_quality = Column(Float, nullable=False)
    completeness = Column(Float, nullable=False)
    overall_score = Column(Float, nullable=False)   # weighted average, 0.0–1.0
    passed = Column(Boolean, nullable=False)        # overall_score >= pass_threshold
    failure_type = Column(String, nullable=True)    # null if passed
    failure_step = Column(Integer, nullable=True)
    failure_reason = Column(String, nullable=True)  # one plain English sentence
    confidence = Column(Float, nullable=True)
    eval_error = Column(Boolean, default=False, nullable=False)
    evaluated_at = Column(SADateTime(timezone=True), default=_now, nullable=False)


class LossPattern(Base):
    __tablename__ = "loss_patterns"

    id = Column(String, primary_key=True, default=_uuid)
    agent_id = Column(String, nullable=False, index=True)
    pattern_type = Column(String, nullable=False)   # intent | workflow_step | tool_call
    pattern_value = Column(String, nullable=False)  # e.g. 'billing_dispute' or 'step_3'
    failure_count = Column(Integer, nullable=False)
    total_count = Column(Integer, nullable=False)
    failure_rate = Column(Float, nullable=False)
    pct_of_all_failures = Column(Float, nullable=False)
    root_cause = Column(String, nullable=True)      # one plain English sentence
    is_worsening = Column(Boolean, default=False, nullable=False)
    first_seen = Column(SADateTime(timezone=True), nullable=False)
    last_seen = Column(SADateTime(timezone=True), nullable=False)


class AgentQualityConfig(Base):
    __tablename__ = "agent_quality_configs"

    agent_id = Column(String, primary_key=True)
    industry = Column(String, nullable=False, default="default")
    weight_accuracy = Column(Float, nullable=False, default=0.35)
    weight_goal_alignment = Column(Float, nullable=False, default=0.35)
    weight_decision = Column(Float, nullable=False, default=0.15)
    weight_completeness = Column(Float, nullable=False, default=0.15)
    pass_threshold = Column(Float, nullable=False, default=0.7)
