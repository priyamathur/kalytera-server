"""
db/queries.py — all database operations. No SQL outside this file.
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import case, distinct, func
from sqlalchemy.orm import Session

from db.models import AgentLog, AgentQualityConfig, EvalResult, LossPattern


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


def get_todays_stats(agent_id: str, db: Session) -> Dict[str, Any]:
    """Pass rate, total evals, and distinct active failure types for today."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
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
        q = q.filter(EvalResult.failure_step.in_(step_numbers))

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
