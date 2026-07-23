"""
db/queries.py — all database operations. No SQL outside this file.
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import case, distinct, func
from sqlalchemy.orm import Session

from db.models import AgentLog, AgentQualityConfig, ApiKey, EvalResult, GoldenLabel, LossPattern, Organization, User, UsageRecord


# ---------------------------------------------------------------------------
# Tracer / ingestion
# ---------------------------------------------------------------------------

def insert_agent_log(payload: Dict[str, Any], db: Session) -> AgentLog:
    """Write one AgentLog row from a tracer payload dict. Returns the inserted row."""
    tool_calls = payload.get("tool_calls") or []
    metadata = payload.get("metadata") or {}

    row = AgentLog(
        id=payload["id"],
        agent_id=payload["agent_id"],
        session_id=payload["session_id"],
        step_number=int(payload["step_number"]),
        step_name=str(payload["step_name"]),
        input=str(payload["input"]),
        output=str(payload["output"]),
        tool_calls=json.dumps(tool_calls) if tool_calls else None,
        latency_ms=int(payload.get("latency_ms", 0)),
        session_ended=bool(payload.get("session_ended", False)),
        timestamp=_parse_timestamp(payload.get("timestamp")),
        step_metadata=json.dumps(metadata) if metadata else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_unevaluated_logs(agent_id: str, batch_size: int, db: Session) -> List[AgentLog]:
    """Return AgentLog rows that have no corresponding EvalResult yet."""
    evaluated_ids = db.query(EvalResult.log_id).filter(EvalResult.agent_id == agent_id)
    return (
        db.query(AgentLog)
        .filter(
            AgentLog.agent_id == agent_id,
            AgentLog.id.notin_(evaluated_ids),
        )
        .order_by(AgentLog.timestamp)
        .limit(batch_size)
        .all()
    )


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

def get_patterns_for_agent(agent_id: str, db: Session) -> List[LossPattern]:
    """Return all LossPattern rows for an agent, sorted by pct_of_all_failures desc."""
    return (
        db.query(LossPattern)
        .filter(LossPattern.agent_id == agent_id)
        .order_by(LossPattern.pct_of_all_failures.desc())
        .all()
    )


# ---------------------------------------------------------------------------
# Dashboard — Agent Overview
# ---------------------------------------------------------------------------

def get_quality_trend(
    agent_id: str, days: int, db: Session
) -> List[Dict[str, Any]]:
    """
    Daily avg overall_score and pass_rate for the last N days.
    Returns list of {date, avg_score, pass_rate, total} dicts, oldest first.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(
            func.date(EvalResult.evaluated_at).label("date"),
            func.avg(EvalResult.overall_score).label("avg_score"),
            func.avg(case((EvalResult.passed == True, 1.0), else_=0.0)).label("pass_rate"),  # noqa: E712
            func.count(EvalResult.id).label("total"),
        )
        .filter(
            EvalResult.agent_id == agent_id,
            EvalResult.evaluated_at >= since,
            EvalResult.eval_error == False,  # noqa: E712
        )
        .group_by(func.date(EvalResult.evaluated_at))
        .order_by(func.date(EvalResult.evaluated_at))
        .all()
    )
    return [
        {
            "date": str(r.date),
            "avg_score": round(float(r.avg_score or 0), 3),
            "pass_rate": round(float(r.pass_rate or 0), 3),
            "total": int(r.total),
        }
        for r in rows
    ]


def get_todays_stats(agent_id: str, db: Session, hours: int = 24) -> Dict[str, Any]:
    """Pass rate, total evals, and distinct active failure types for the given window."""
    today_start = datetime.now(timezone.utc) - timedelta(hours=hours)
    base = (
        db.query(EvalResult)
        .filter(
            EvalResult.agent_id == agent_id,
            EvalResult.evaluated_at >= today_start,
            EvalResult.eval_error == False,  # noqa: E712
        )
    )
    total = base.count()
    passed = base.filter(EvalResult.passed == True).count()  # noqa: E712
    active_failure_types = (
        db.query(func.count(func.distinct(EvalResult.failure_type)))
        .filter(
            EvalResult.agent_id == agent_id,
            EvalResult.evaluated_at >= today_start,
            EvalResult.passed == False,  # noqa: E712
            EvalResult.failure_type.isnot(None),
        )
        .scalar()
        or 0
    )
    return {
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "active_failure_types": int(active_failure_types),
    }


def get_top_failure_types(
    agent_id: str, hours: int, db: Session
) -> List[Tuple[str, int, float]]:
    """
    Top failure types in the last N hours by frequency.
    Returns list of (failure_type, count, pct_of_all_failures) tuples.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        db.query(
            EvalResult.failure_type,
            func.count(EvalResult.id).label("cnt"),
        )
        .filter(
            EvalResult.agent_id == agent_id,
            EvalResult.evaluated_at >= since,
            EvalResult.passed == False,  # noqa: E712
            EvalResult.failure_type.isnot(None),
        )
        .group_by(EvalResult.failure_type)
        .order_by(func.count(EvalResult.id).desc())
        .all()
    )
    total = sum(r.cnt for r in rows)
    return [
        (r.failure_type, int(r.cnt), round(r.cnt / total, 3) if total else 0.0)
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Dashboard — Failure Feed
# ---------------------------------------------------------------------------

def get_recent_eval_failures(
    agent_id: str, limit: int, db: Session
) -> List[Tuple[EvalResult, AgentLog]]:
    """
    Return recent failed EvalResult rows joined with their AgentLog.
    Sorted newest first.
    """
    rows = (
        db.query(EvalResult, AgentLog)
        .join(AgentLog, EvalResult.log_id == AgentLog.id)
        .filter(
            EvalResult.agent_id == agent_id,
            EvalResult.passed == False,  # noqa: E712
            EvalResult.eval_error == False,  # noqa: E712
        )
        .order_by(EvalResult.evaluated_at.desc())
        .limit(limit)
        .all()
    )
    return [(ev, log) for ev, log in rows]


# ---------------------------------------------------------------------------
# Dashboard — Interaction Detail
# ---------------------------------------------------------------------------

def get_session_steps(
    session_id: str, db: Session
) -> List[Tuple[AgentLog, Optional[EvalResult]]]:
    """
    All steps for one session with their eval results, ordered by step_number.
    Returns list of (AgentLog, EvalResult | None).
    """
    logs = (
        db.query(AgentLog)
        .filter(AgentLog.session_id == session_id)
        .order_by(AgentLog.step_number)
        .all()
    )
    evals: Dict[str, EvalResult] = {
        ev.log_id: ev
        for ev in db.query(EvalResult)
        .filter(EvalResult.session_id == session_id)
        .all()
    }
    return [(log, evals.get(log.id)) for log in logs]


# ---------------------------------------------------------------------------
# Dashboard — step-level failure breakdown and session browser
# ---------------------------------------------------------------------------

def get_failures_by_step(
    agent_id: str, hours: int, db: Session
) -> List[Tuple[int, str, int, float]]:
    """
    Failure count and rate per (step_number, step_name) for the last N hours.
    Returns list of (step_number, step_name, failure_count, failure_rate), highest failure_count first.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    fail_rows = (
        db.query(
            AgentLog.step_number,
            AgentLog.step_name,
            func.count(EvalResult.id).label("fail_count"),
        )
        .join(EvalResult, EvalResult.log_id == AgentLog.id)
        .filter(
            EvalResult.agent_id == agent_id,
            EvalResult.evaluated_at >= since,
            EvalResult.passed == False,  # noqa: E712
            EvalResult.eval_error == False,  # noqa: E712
        )
        .group_by(AgentLog.step_number, AgentLog.step_name)
        .order_by(func.count(EvalResult.id).desc())
        .all()
    )
    total_rows = (
        db.query(
            AgentLog.step_number,
            func.count(EvalResult.id).label("total"),
        )
        .join(EvalResult, EvalResult.log_id == AgentLog.id)
        .filter(
            EvalResult.agent_id == agent_id,
            EvalResult.evaluated_at >= since,
            EvalResult.eval_error == False,  # noqa: E712
        )
        .group_by(AgentLog.step_number)
        .all()
    )
    total_map = {r.step_number: int(r.total) for r in total_rows}
    return [
        (
            int(r.step_number),
            str(r.step_name),
            int(r.fail_count),
            round(r.fail_count / max(total_map.get(r.step_number, r.fail_count), 1), 3),
        )
        for r in fail_rows
    ]


def get_recent_failing_sessions(
    agent_id: str,
    limit: int,
    db: Session,
    failure_types: Optional[List[str]] = None,
    step_numbers: Optional[List[int]] = None,
    since_hours: Optional[int] = None,
    sort_by: str = "newest",
) -> List[Dict[str, Any]]:
    """
    Most recently failed sessions — one entry per session_id.
    Optional filters: failure_types, step_numbers, since_hours.
    sort_by: 'newest' | 'score_asc' | 'failure_type'.
    Returns list of {session_id, failed_at, failure_type, failure_step,
                     overall_score, failure_reason}.
    """
    q = db.query(EvalResult).filter(
        EvalResult.agent_id == agent_id,
        EvalResult.passed == False,  # noqa: E712
        EvalResult.eval_error == False,  # noqa: E712
    )
    if since_hours is not None:
        since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        q = q.filter(EvalResult.evaluated_at >= since)
    if failure_types:
        q = q.filter(EvalResult.failure_type.in_(failure_types))
    if step_numbers:
        q = q.filter(EvalResult.failure_step.in_([str(n) for n in step_numbers]))

    rows = q.order_by(EvalResult.evaluated_at.desc()).limit(limit * 6).all()

    seen: set = set()
    result: List[Dict[str, Any]] = []
    for ev in rows:
        if ev.session_id not in seen:
            seen.add(ev.session_id)
            result.append(
                {
                    "session_id": ev.session_id,
                    "failed_at": ev.evaluated_at,
                    "failure_type": ev.failure_type,
                    "failure_step": ev.failure_step,
                    "overall_score": round(float(ev.overall_score or 0), 3),
                    "failure_reason": ev.failure_reason,
                }
            )
        if len(result) >= limit * 2:
            break

    if sort_by == "score_asc":
        result.sort(key=lambda s: s["overall_score"])
    elif sort_by == "failure_type":
        result.sort(key=lambda s: s["failure_type"] or "")

    return result[:limit]


# ---------------------------------------------------------------------------
# Multi-agent support
# ---------------------------------------------------------------------------

def get_all_agent_ids(db: Session) -> List[str]:
    """All distinct agent_ids that have at least one AgentLog, alphabetical."""
    rows = (
        db.query(distinct(AgentLog.agent_id))
        .filter(AgentLog.agent_id.isnot(None), AgentLog.agent_id != "")
        .order_by(AgentLog.agent_id)
        .all()
    )
    return [r[0] for r in rows]


def get_session_and_latency_stats(agent_id: str, hours: int, db: Session) -> Dict[str, Any]:
    """Distinct session count and avg step latency for the last N hours."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    session_count = (
        db.query(func.count(distinct(AgentLog.session_id)))
        .filter(AgentLog.agent_id == agent_id, AgentLog.timestamp >= since)
        .scalar()
        or 0
    )
    avg_latency = (
        db.query(func.avg(AgentLog.latency_ms))
        .filter(AgentLog.agent_id == agent_id, AgentLog.timestamp >= since)
        .scalar()
        or 0
    )
    avg_score = (
        db.query(func.avg(EvalResult.overall_score))
        .filter(
            EvalResult.agent_id == agent_id,
            EvalResult.evaluated_at >= since,
            EvalResult.eval_error == False,  # noqa: E712
        )
        .scalar()
        or 0
    )
    return {
        "session_count": int(session_count),
        "avg_latency_ms": int(avg_latency),
        "avg_score": round(float(avg_score) * 100, 1),
    }


# ---------------------------------------------------------------------------
# Dashboard — Latency / score distributions + search
# ---------------------------------------------------------------------------

def get_avg_score_by_step(agent_id: str, hours: int, db: Session) -> List[Tuple[str, float, int]]:
    """
    Avg quality score per step_name, sorted lowest first (most concerning at top).
    Returns (step_name, avg_score_0_to_1, eval_count).
    Unique to Kalytera — shows which workflow step is the quality bottleneck.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        db.query(
            AgentLog.step_name,
            func.avg(EvalResult.overall_score).label("avg_score"),
            func.count(EvalResult.id).label("cnt"),
        )
        .join(EvalResult, EvalResult.log_id == AgentLog.id)
        .filter(
            EvalResult.agent_id == agent_id,
            EvalResult.evaluated_at >= since,
            EvalResult.eval_error == False,  # noqa: E712
        )
        .group_by(AgentLog.step_name)
        .order_by(func.avg(EvalResult.overall_score))
        .limit(12)
        .all()
    )
    return [(str(r.step_name), round(float(r.avg_score or 0), 3), int(r.cnt)) for r in rows]


def get_latency_values(agent_id: str, hours: int, db: Session) -> List[int]:
    """Raw step latency_ms values for computing percentiles in-process."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        db.query(AgentLog.latency_ms)
        .filter(
            AgentLog.agent_id == agent_id,
            AgentLog.timestamp >= since,
            AgentLog.latency_ms > 0,
        )
        .all()
    )
    return [int(r[0]) for r in rows]


def get_score_buckets(agent_id: str, hours: int, db: Session) -> List[Dict[str, Any]]:
    """Score distribution: count of evals per 10-point bucket (0-9, 10-19, … 90-100)."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        db.query(EvalResult.overall_score)
        .filter(
            EvalResult.agent_id == agent_id,
            EvalResult.evaluated_at >= since,
            EvalResult.eval_error == False,  # noqa: E712
        )
        .all()
    )
    buckets: Dict[int, int] = {i: 0 for i in range(0, 100, 10)}
    for (score,) in rows:
        if score is not None:
            bucket = min(int(float(score) * 100) // 10 * 10, 90)
            buckets[bucket] = buckets.get(bucket, 0) + 1
    return [
        {"range": f"{k}–{k+9}", "count": v, "bucket": k}
        for k, v in sorted(buckets.items())
        if v > 0
    ]


def search_eval_failures(
    agent_id: str, query_text: str, limit: int, db: Session
) -> List[Tuple["EvalResult", "AgentLog"]]:
    """Full-text search over failure_reason. Returns (EvalResult, AgentLog) pairs."""
    rows = (
        db.query(EvalResult, AgentLog)
        .join(AgentLog, EvalResult.log_id == AgentLog.id)
        .filter(
            EvalResult.agent_id == agent_id,
            EvalResult.passed == False,  # noqa: E712
            EvalResult.eval_error == False,  # noqa: E712
            EvalResult.failure_reason.ilike(f"%{query_text}%"),
        )
        .order_by(EvalResult.evaluated_at.desc())
        .limit(limit)
        .all()
    )
    return [(ev, log) for ev, log in rows]


# ---------------------------------------------------------------------------
# Billing — organizations, users, API keys, usage
# ---------------------------------------------------------------------------

def create_organization(name: str, db: Session) -> Organization:
    org = Organization(name=name)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def get_org_by_id(org_id: str, db: Session) -> Optional[Organization]:
    return db.query(Organization).filter(Organization.id == org_id, Organization.is_active == True).first()  # noqa: E712


def list_organizations(db: Session) -> List[Organization]:
    return db.query(Organization).order_by(Organization.created_at.desc()).all()


def create_user(email: str, org_id: str, role: str, db: Session) -> User:
    user = User(email=email, org_id=org_id, role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_email(email: str, db: Session) -> Optional[User]:
    return db.query(User).filter(User.email == email, User.is_active == True).first()  # noqa: E712


def list_users_for_org(org_id: str, db: Session) -> List[User]:
    return db.query(User).filter(User.org_id == org_id, User.is_active == True).all()  # noqa: E712


def create_api_key(key_hash: str, key_prefix: str, name: str, org_id: str, created_by: Optional[str], db: Session) -> ApiKey:
    key = ApiKey(key_hash=key_hash, key_prefix=key_prefix, name=name, org_id=org_id, created_by=created_by)
    db.add(key)
    db.commit()
    db.refresh(key)
    return key


def get_apikey_by_hash(key_hash: str, db: Session) -> Optional[ApiKey]:
    return (
        db.query(ApiKey)
        .filter(ApiKey.key_hash == key_hash, ApiKey.is_active == True)  # noqa: E712
        .first()
    )


def list_keys_for_org(org_id: str, db: Session) -> List[ApiKey]:
    return db.query(ApiKey).filter(ApiKey.org_id == org_id, ApiKey.is_active == True).all()  # noqa: E712


def revoke_api_key(key_id: str, db: Session) -> None:
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if key:
        key.is_active = False
        db.commit()


def get_current_usage(org_id: str, period: str, db: Session) -> Optional[UsageRecord]:
    return (
        db.query(UsageRecord)
        .filter(UsageRecord.org_id == org_id, UsageRecord.period == period)
        .first()
    )


def increment_session_count(org_id: str, period: str, db: Session) -> int:
    """Increment session_count by 1 for the given org+period. Returns new count."""
    record = (
        db.query(UsageRecord)
        .filter(UsageRecord.org_id == org_id, UsageRecord.period == period)
        .first()
    )
    if record is None:
        record = UsageRecord(org_id=org_id, period=period, session_count=1)
        db.add(record)
        db.commit()
        return 1
    record.session_count += 1
    record.updated_at = datetime.now(timezone.utc)
    db.commit()
    return record.session_count


def update_org_stripe(org_id: str, stripe_customer_id: str, subscription_id: str, tier: str, db: Session) -> None:
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if org:
        org.stripe_customer_id = stripe_customer_id
        org.stripe_subscription_id = subscription_id
        org.tier = tier
        db.commit()


def downgrade_org(subscription_id: str, db: Session) -> None:
    org = db.query(Organization).filter(Organization.stripe_subscription_id == subscription_id).first()
    if org:
        org.tier = "free"
        org.stripe_subscription_id = None
        db.commit()


# ---------------------------------------------------------------------------
# Agent quality config
# ---------------------------------------------------------------------------

_DEFAULTS = dict(
    industry="default",
    weight_accuracy=0.25,
    weight_goal_alignment=0.25,
    weight_decision=0.15,
    weight_completeness=0.15,
    weight_helpfulness=0.10,
    weight_factuality=0.10,
    pass_threshold=0.70,
    custom_metrics=[],
)


def get_quality_config(agent_id: str, db: Session) -> Dict[str, Any]:
    row = db.query(AgentQualityConfig).filter(AgentQualityConfig.agent_id == agent_id).first()
    if row is None:
        return {"agent_id": agent_id, **_DEFAULTS}
    custom: List[Any] = []
    if getattr(row, "custom_metrics", None):
        try:
            custom = json.loads(row.custom_metrics)
        except (json.JSONDecodeError, TypeError):
            custom = []
    return {
        "agent_id": row.agent_id,
        "industry": row.industry,
        "weight_accuracy": row.weight_accuracy,
        "weight_goal_alignment": row.weight_goal_alignment,
        "weight_decision": row.weight_decision,
        "weight_completeness": row.weight_completeness,
        "weight_helpfulness": getattr(row, "weight_helpfulness", 0.10) or 0.10,
        "weight_factuality": getattr(row, "weight_factuality", 0.10) or 0.10,
        "pass_threshold": row.pass_threshold,
        "custom_metrics": custom,
    }


def upsert_quality_config(agent_id: str, updates: Dict[str, Any], db: Session) -> None:
    row = db.query(AgentQualityConfig).filter(AgentQualityConfig.agent_id == agent_id).first()
    init = {**_DEFAULTS, **updates}
    if "custom_metrics" in init and isinstance(init["custom_metrics"], list):
        init["custom_metrics"] = json.dumps(init["custom_metrics"])
    if row is None:
        row = AgentQualityConfig(agent_id=agent_id, **init)
        db.add(row)
    else:
        for k, v in updates.items():
            if hasattr(row, k):
                setattr(row, k, json.dumps(v) if k == "custom_metrics" and isinstance(v, list) else v)
    db.commit()


# ---------------------------------------------------------------------------
# Golden labels — judge calibration
# ---------------------------------------------------------------------------

def upsert_golden_label(
    agent_id: str, session_id: str, human_passed: bool, note: str, db: Session
) -> None:
    row = db.query(GoldenLabel).filter(
        GoldenLabel.agent_id == agent_id,
        GoldenLabel.session_id == session_id,
    ).first()
    if row:
        row.human_passed = human_passed
        row.note = note
    else:
        db.add(GoldenLabel(agent_id=agent_id, session_id=session_id, human_passed=human_passed, note=note))
    db.commit()


def get_golden_label(agent_id: str, session_id: str, db: Session) -> Optional[GoldenLabel]:
    return db.query(GoldenLabel).filter(
        GoldenLabel.agent_id == agent_id,
        GoldenLabel.session_id == session_id,
    ).first()


def get_calibration_stats(agent_id: str, db: Session) -> Dict[str, Any]:
    """
    Returns judge–human agreement stats for this agent.
    Agreement: judge's session verdict (any failed step → session failed) vs human label.
    """
    labels = db.query(GoldenLabel).filter(GoldenLabel.agent_id == agent_id).all()
    if not labels:
        return {"total_labeled": 0, "agreement_count": 0, "agreement_rate": None, "status": "unlabeled"}

    agreement = 0
    for label in labels:
        any_fail = db.query(EvalResult).filter(
            EvalResult.agent_id == agent_id,
            EvalResult.session_id == label.session_id,
            EvalResult.passed == False,  # noqa: E712
            EvalResult.eval_error == False,  # noqa: E712
        ).first()
        judge_passed = any_fail is None
        if judge_passed == label.human_passed:
            agreement += 1

    total = len(labels)
    rate = agreement / total
    status = "excellent" if rate >= 0.90 else ("good" if rate >= 0.80 else "needs_calibration")
    return {
        "total_labeled": total,
        "agreement_count": agreement,
        "agreement_rate": round(rate, 3),
        "status": status,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _float_type() -> Any:
    from sqlalchemy import Float
    return Float
