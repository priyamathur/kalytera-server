"""
Seven tables.
AgentLog           ← tracer.py only
EvalResult         ← judge.py only
LossPattern        ← analyzer.py only
AgentQualityConfig ← dashboard weight editor
Organization       ← billing unit (company or solo dev); holds Stripe subscription
User               ← person with an email/login; belongs to one org
ApiKey             ← what developers put in kalytera.configure(); scoped to an org
UsageRecord        ← monthly session counters per org (shared across all org's keys)
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Index
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
    helpfulness = Column(Float, nullable=True)
    factuality = Column(Float, nullable=True)
    overall_score = Column(Float, nullable=False)   # weighted average, 0.0–1.0
    passed = Column(Boolean, nullable=False)        # overall_score >= pass_threshold
    failure_type = Column(String, nullable=True)    # null if passed
    failure_step = Column(String, nullable=True)   # step name or number as string
    failure_reason = Column(String, nullable=True)  # one plain English sentence
    confidence = Column(Float, nullable=True)
    eval_error = Column(Boolean, default=False, nullable=False)
    evaluated_at = Column(SADateTime(timezone=True), default=_now, nullable=False)
    custom_scores = Column(Text, nullable=True)  # JSON: {"helpfulness": 0.85}


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
    weight_accuracy = Column(Float, nullable=False, default=0.25)
    weight_goal_alignment = Column(Float, nullable=False, default=0.25)
    weight_decision = Column(Float, nullable=False, default=0.15)
    weight_completeness = Column(Float, nullable=False, default=0.15)
    weight_helpfulness = Column(Float, nullable=False, default=0.10)
    weight_factuality = Column(Float, nullable=False, default=0.10)
    pass_threshold = Column(Float, nullable=False, default=0.7)
    custom_metrics = Column(Text, nullable=True)  # JSON: [{"name":"helpfulness","weight":0.2,"description":"..."}]


class GoldenLabel(Base):
    """Human ground-truth labels for calibrating the LLM judge."""
    __tablename__ = "golden_labels"

    id = Column(String, primary_key=True, default=_uuid)
    agent_id = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=False, index=True)
    human_passed = Column(Boolean, nullable=False)
    note = Column(String, nullable=True)
    created_at = Column(SADateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (UniqueConstraint("agent_id", "session_id", name="uq_golden_agent_session"),)


class Organization(Base):
    """
    The billing unit. One Stripe subscription lives here.
    Can be a solo developer (name = their name) or a company (name = "Acme Corp").
    All API keys under an org share the org's monthly session limit.
    """
    __tablename__ = "organizations"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    tier = Column(String, nullable=False, default="free")  # free | starter | growth | scale
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    created_at = Column(SADateTime(timezone=True), default=_now, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)


class User(Base):
    """
    A person — developer, admin, or viewer — who belongs to one org.
    Role admin can create/revoke API keys and manage billing.
    """
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_uuid)
    email = Column(String, nullable=False, unique=True, index=True)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    role = Column(String, nullable=False, default="admin")  # admin | member
    created_at = Column(SADateTime(timezone=True), default=_now, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)


class ApiKey(Base):
    """
    A key developers put in kalytera.configure(api_key=...).
    Scoped to an org. Multiple keys per org (e.g. production, staging).
    Usage is tracked at org level, not per key.
    """
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, default=_uuid)
    key_hash = Column(String, nullable=False, unique=True, index=True)  # SHA256, never store raw
    key_prefix = Column(String, nullable=False)   # first 16 chars for display, e.g. "kly_live_xxxx"
    name = Column(String, nullable=False, default="default")  # "production", "staging", etc.
    org_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)  # null for system-generated
    created_at = Column(SADateTime(timezone=True), default=_now, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)


class UsageRecord(Base):
    """Monthly session counter per org. All keys in an org share one record."""
    __tablename__ = "usage_records"

    id = Column(String, primary_key=True, default=_uuid)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    period = Column(String, nullable=False)   # "YYYY-MM"
    session_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(SADateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (UniqueConstraint("org_id", "period", name="uq_usage_org_period"),)
