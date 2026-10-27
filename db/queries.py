"""
db/queries.py — all database operations. No SQL outside this file.
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, case, distinct, func
from sqlalchemy.orm import Session

from db.models import AgentLog, AgentOrg, AgentQualityConfig, ApiKey, EvalResult, GoldenLabel, LossPattern, Organization, User, UsageRecord

# agent_ids always visible to every authenticated user (demo / onboarding data)
DEMO_AGENT_IDS: List[str] = ["demo-agent"]


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


def insert_agent_logs(payloads: List[Dict[str, Any]], db: Session) -> None:
    """Write many AgentLog rows in one commit (the sample agent's conversations)."""
    db.add_all([
        AgentLog(
            id=p["id"], agent_id=p["agent_id"], session_id=p["session_id"],
            step_number=int(p["step_number"]), step_name=str(p["step_name"]),
            input=str(p["input"]), output=str(p["output"]),
            tool_calls=json.dumps(p["tool_calls"]) if p.get("tool_calls") else None,
            latency_ms=int(p.get("latency_ms", 0)), session_ended=bool(p.get("session_ended", False)),
            timestamp=_parse_timestamp(p.get("timestamp")),
            step_metadata=json.dumps(p["metadata"]) if p.get("metadata") else None,
        )
        for p in payloads
    ])
    db.commit()


def upsert_agent_org(agent_id: str, org_id: str, db: Session) -> bool:
    """
    Claim agent_id for this org, or confirm the org already owns it. Safe to call
    on every trace. Returns False if another org owns it (or it's a shared demo
    agent): the first org to use an agent_id keeps it, so no one can take over
    another account's agent — and its data — by sending a trace with its name.
    """
    from sqlalchemy import text
    if agent_id in DEMO_AGENT_IDS:
        return False
    now = datetime.now(timezone.utc)
    db.execute(
        text("""
            INSERT INTO agent_orgs (agent_id, org_id, first_seen, last_seen)
            VALUES (:agent_id, :org_id, :now, :now)
            ON CONFLICT (agent_id) DO NOTHING
        """),
        {"agent_id": agent_id, "org_id": org_id, "now": now},
    )
    owned = (
        db.query(AgentOrg)
        .filter(AgentOrg.agent_id == agent_id, AgentOrg.org_id == org_id)
        .update({AgentOrg.last_seen: now}, synchronize_session=False)
    )
    db.commit()
    return bool(owned)


def get_agent_ids_for_org(org_id: str, db: Session) -> List[str]:
    """Return agent_ids owned by this org, plus shared demo agents."""
    owned = [
        r.agent_id
        for r in db.query(AgentOrg.agent_id).filter(AgentOrg.org_id == org_id).all()
    ]
    combined = list(dict.fromkeys(owned + DEMO_AGENT_IDS))  # owned first, deduped
    return combined


def get_log_by_id(log_id: str, db: Session) -> Optional[AgentLog]:
    return db.query(AgentLog).filter(AgentLog.id == log_id).first()


def get_eval_for_log(log_id: str, db: Session) -> Optional[EvalResult]:
    """Most recent EvalResult attached to this log (session-mode results attach to the session_ended log)."""
    return (
        db.query(EvalResult)
        .filter(EvalResult.log_id == log_id)
        .order_by(EvalResult.evaluated_at.desc())
        .first()
    )


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


IDLE_SESSION_MINUTES = 10  # no new step for this long = the conversation is over, even if nobody said so


def get_unevaluated_sessions(agent_id: str, batch_size: int, db: Session,
                             now: Optional[datetime] = None) -> List[str]:
    """
    Session_ids ready to be judged and not judged yet: sessions marked ended, and
    sessions with no new step for IDLE_SESSION_MINUTES. Without the second kind,
    proxy traffic, crashed apps and abandoned conversations would never be judged.
    """
    evaluated_log_ids = db.query(EvalResult.log_id).filter(EvalResult.agent_id == agent_id)
    ended = [r[0] for r in (
        db.query(AgentLog.session_id)
        .filter(
            AgentLog.agent_id == agent_id,
            AgentLog.session_ended == True,  # noqa: E712
            AgentLog.id.notin_(evaluated_log_ids),
        )
        .limit(batch_size)
        .all()
    )]
    room = batch_size - len(ended)
    if room <= 0:
        return ended
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(minutes=IDLE_SESSION_MINUTES)
    judged = db.query(EvalResult.session_id).filter(EvalResult.agent_id == agent_id)
    idle = (
        db.query(AgentLog.session_id)
        .filter(AgentLog.agent_id == agent_id, AgentLog.session_id.notin_(judged))
        .group_by(AgentLog.session_id)
        .having(func.max(AgentLog.timestamp) < cutoff)
        .having(func.sum(case((AgentLog.session_ended == True, 1), else_=0)) == 0)  # noqa: E712
        .limit(room)
        .all()
    )
    return ended + [r[0] for r in idle]


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
    """
    Sessions evaluated in the window, how many passed (no failing step), and the
    number of distinct failure types seen. Counts sessions, not scored steps.
    """
    today_start = datetime.now(timezone.utc) - timedelta(hours=hours)
    base = db.query(EvalResult).filter(
        EvalResult.agent_id == agent_id,
        EvalResult.evaluated_at >= today_start,
        EvalResult.eval_error == False,  # noqa: E712
    )
    total = base.with_entities(func.count(distinct(EvalResult.session_id))).scalar() or 0
    failed = (base.filter(EvalResult.passed == False)  # noqa: E712
              .with_entities(func.count(distinct(EvalResult.session_id))).scalar() or 0)
    passed = total - failed
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
        "total": int(total),
        "passed": int(passed),
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "active_failure_types": int(active_failure_types),
    }


def get_top_failure_types(
    agent_id: str, hours: int, db: Session
) -> List[Tuple[str, int, float]]:
    """
    Failure types in the last N hours, by the number of sessions they hit.
    Returns (failure_type, sessions, share of failed sessions) tuples.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    failing = db.query(EvalResult).filter(
        EvalResult.agent_id == agent_id,
        EvalResult.evaluated_at >= since,
        EvalResult.passed == False,  # noqa: E712
        EvalResult.eval_error == False,  # noqa: E712
    )
    sessions = func.count(distinct(EvalResult.session_id))
    rows = (
        failing.filter(EvalResult.failure_type.isnot(None))
        .with_entities(EvalResult.failure_type, sessions.label("cnt"))
        .group_by(EvalResult.failure_type)
        .order_by(sessions.desc())
        .all()
    )
    total = failing.with_entities(sessions).scalar() or 0
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
    session_id: str, db: Session, agent_id: Optional[str] = None
) -> List[Tuple[AgentLog, Optional[EvalResult]]]:
    """
    All steps for one session with their eval results, ordered by step_number.
    Pass agent_id so another agent's session with the same ID never shows.
    Returns list of (AgentLog, EvalResult | None).
    """
    q = db.query(AgentLog).filter(AgentLog.session_id == session_id)
    if agent_id is not None:
        q = q.filter(AgentLog.agent_id == agent_id)
    logs = q.order_by(AgentLog.step_number).all()
    evals: Dict[str, EvalResult] = {
        ev.log_id: ev
        for ev in db.query(EvalResult)
        .filter(EvalResult.log_id.in_([log.id for log in logs]))
        .all()
    } if logs else {}
    return [(log, evals.get(log.id)) for log in logs]


# ---------------------------------------------------------------------------
# Dashboard — step-level failure breakdown and session browser
# ---------------------------------------------------------------------------

def get_failures_by_step(
    agent_id: str, hours: int, db: Session
) -> List[Tuple[int, str, int, float]]:
    """
    Sessions that failed at each (step_number, step_name) in the last N hours,
    and that as a share of the sessions that reached the step.
    Returns (step_number, step_name, failed_sessions, failure_rate), most first.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    sessions = func.count(distinct(EvalResult.session_id))
    fail_rows = (
        db.query(AgentLog.step_number, AgentLog.step_name, sessions.label("fail_count"))
        .join(EvalResult, EvalResult.log_id == AgentLog.id)
        .filter(
            EvalResult.agent_id == agent_id,
            EvalResult.evaluated_at >= since,
            EvalResult.passed == False,  # noqa: E712
            EvalResult.eval_error == False,  # noqa: E712
        )
        .group_by(AgentLog.step_number, AgentLog.step_name)
        .order_by(sessions.desc())
        .all()
    )
    total_rows = (
        db.query(AgentLog.step_number, func.count(distinct(AgentLog.session_id)).label("total"))
        .filter(AgentLog.agent_id == agent_id, AgentLog.timestamp >= since)
        .group_by(AgentLog.step_number)
        .all()
    )
    total_map = {r.step_number: int(r.total) for r in total_rows}
    return [
        (
            int(r.step_number),
            str(r.step_name),
            int(r.fail_count),
            round(r.fail_count / max(total_map.get(r.step_number, r.fail_count), r.fail_count, 1), 3),
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

    _when_it_happened(agent_id, result, db)
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


def get_session_failure_counts(agent_id: str, db: Session) -> Dict[str, Any]:
    """
    Distinct sessions, all time: {"total": sessions evaluated, "failed": failed sessions,
    "workflow_step": {step: failed sessions}, "failure_type": {type: failed sessions}}.
    Lets the Failure Feed say "12 sessions (8%)" instead of counting scored steps.
    """
    sessions = func.count(distinct(EvalResult.session_id))
    base = db.query(EvalResult).filter(EvalResult.agent_id == agent_id,
                                       EvalResult.eval_error == False)  # noqa: E712
    failing = base.filter(EvalResult.passed == False)  # noqa: E712
    by_step = failing.with_entities(EvalResult.failure_step, sessions).group_by(EvalResult.failure_step).all()
    by_type = failing.with_entities(EvalResult.failure_type, sessions).group_by(EvalResult.failure_type).all()
    return {
        "total": int(base.with_entities(sessions).scalar() or 0),
        "failed": int(failing.with_entities(sessions).scalar() or 0),
        "workflow_step": {str(k): int(n) for k, n in by_step if k is not None},
        "failure_type": {str(k): int(n) for k, n in by_type if k is not None},
    }


def get_step_names(agent_id: str, db: Session) -> Dict[str, str]:
    """{"2": "issue_refund"} — the judge reports failing steps by number; show their names."""
    rows = (
        db.query(AgentLog.step_number, AgentLog.step_name, func.count(AgentLog.id))
        .filter(AgentLog.agent_id == agent_id)
        .group_by(AgentLog.step_number, AgentLog.step_name)
        .order_by(func.count(AgentLog.id).desc())
        .all()
    )
    names: Dict[str, str] = {}
    for number, name, _ in rows:  # most common name per step number wins
        if name:
            names.setdefault(str(number), name)
    return names


def step_label(value: Optional[str], names: Dict[str, str]) -> str:
    """'2' -> 'issue_refund' when known; names pass through."""
    return names.get(str(value), str(value)) if value is not None else ""


def get_pattern_sessions(
    agent_id: str, pattern_type: str, pattern_value: str, limit: int, db: Session
) -> List[Dict[str, Any]]:
    """
    Failed sessions in one loss pattern, newest first, one entry per session:
    {session_id, failed_at, failure_type, failure_step, overall_score, failure_reason}.
    """
    column = {"workflow_step": EvalResult.failure_step,
              "action": EvalResult.failure_action}.get(pattern_type, EvalResult.failure_type)
    rows = (
        db.query(EvalResult)
        .filter(
            EvalResult.agent_id == agent_id,
            EvalResult.passed == False,  # noqa: E712
            EvalResult.eval_error == False,  # noqa: E712
            column == pattern_value,
        )
        .order_by(EvalResult.evaluated_at.desc())
        .limit(limit * 6)
        .all()
    )
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for ev in rows:
        if ev.session_id in seen:
            continue
        seen.add(ev.session_id)
        out.append({
            "session_id": ev.session_id,
            "failed_at": ev.evaluated_at,
            "failure_type": ev.failure_type,
            "failure_step": ev.failure_step,
            "overall_score": round(float(ev.overall_score or 0), 3),
            "failure_reason": ev.failure_reason,
        })
        if len(out) >= limit:
            break
    _when_it_happened(agent_id, out, db)
    return out


def _when_it_happened(agent_id: str, sessions: List[Dict[str, Any]], db: Session) -> None:
    """failed_at = when the conversation ended, not when it was judged: history read from
    Langfuse/LangSmith is judged on connect, and last week's mistakes shouldn't say '4m ago'."""
    ids = [s["session_id"] for s in sessions]
    if not ids:
        return
    ended = dict(db.query(AgentLog.session_id, func.max(AgentLog.timestamp))
                 .filter(AgentLog.agent_id == agent_id, AgentLog.session_id.in_(ids))
                 .group_by(AgentLog.session_id).all())
    for s in sessions:
        s["failed_at"] = ended.get(s["session_id"]) or s["failed_at"]


def search_sessions(agent_ids: List[str], text: str, limit: int, db: Session) -> List[Dict[str, Any]]:
    """
    Sessions of these agents whose ID contains `text`, or that failed with a
    reason containing it. Newest first:
    {session_id, agent_id, last_seen, failed, failure_reason}.
    """
    text = text.strip()
    if not text or not agent_ids:
        return []
    like = f"%{text}%"
    by_id = (
        db.query(AgentLog.session_id, AgentLog.agent_id, func.max(AgentLog.timestamp).label("last_seen"))
        .filter(AgentLog.agent_id.in_(agent_ids), AgentLog.session_id.ilike(like))
        .group_by(AgentLog.session_id, AgentLog.agent_id)
        .order_by(func.max(AgentLog.timestamp).desc())
        .limit(limit)
        .all()
    )
    by_reason = (
        db.query(EvalResult.session_id, EvalResult.agent_id, func.max(EvalResult.evaluated_at).label("last_seen"))
        .filter(EvalResult.agent_id.in_(agent_ids), EvalResult.passed == False,  # noqa: E712
                EvalResult.failure_reason.ilike(like))
        .group_by(EvalResult.session_id, EvalResult.agent_id)
        .order_by(func.max(EvalResult.evaluated_at).desc())
        .limit(limit)
        .all()
    )
    found: Dict[str, Dict[str, Any]] = {}
    for sid, aid, ts in list(by_id) + list(by_reason):
        found.setdefault(sid, {"session_id": sid, "agent_id": aid, "last_seen": ts})
    if not found:
        return []
    fails = [
        (sid, reason)
        for sid, aid, reason in db.query(EvalResult.session_id, EvalResult.agent_id, EvalResult.failure_reason)
        .filter(EvalResult.agent_id.in_(agent_ids), EvalResult.session_id.in_(list(found)),
                EvalResult.passed == False)  # noqa: E712
        .all()
        if found[sid]["agent_id"] == aid
    ]
    for item in found.values():
        item["failed"] = False
        item["failure_reason"] = None
    for sid, reason in fails:
        found[sid]["failed"] = True
        found[sid]["failure_reason"] = found[sid]["failure_reason"] or reason
    exact = [x for x in found.values() if x["session_id"] == text]
    rest = sorted((x for x in found.values() if x["session_id"] != text),
                  key=lambda x: _aware(x["last_seen"]), reverse=True)
    return (exact + rest)[:limit]


def _aware(ts: Optional[datetime]) -> datetime:
    if ts is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


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


DASHBOARD_KEY_NAME = "dashboard (Google sign-in)"


def dashboard_key_for_email(email: str, secret: str, db: Session) -> Optional[str]:
    """Google sign-in: the API key the dashboard uses for the person with this (Google-verified)
    email, or None if no active account has it. Derived from `secret`, so each person always gets
    the same key (no new key per sign-in) and it is never stored raw; created on first use."""
    import base64
    import hashlib
    import hmac

    user = (db.query(User)
            .filter(func.lower(User.email) == email.strip().lower(), User.is_active == True)  # noqa: E712
            .first())
    if user is None or not secret:
        return None
    org = db.query(Organization).filter(Organization.id == user.org_id).first()
    if org is None or not org.is_active:
        return None
    digest = hmac.new(secret.encode(), f"dashboard:{user.id}".encode(), hashlib.sha256).digest()
    raw = "kly_live_" + base64.urlsafe_b64encode(digest).decode().rstrip("=")
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    row = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
    if row is None:
        create_api_key(key_hash, raw[:16], DASHBOARD_KEY_NAME, org.id, user.id, db)
    elif not row.is_active:
        return None  # revoked: signing in again must not bring it back
    return raw


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
    """
    Increment session_count by 1 for the given org+period. Returns new count.
    Safe under concurrent requests: the increment happens in SQL, and two
    requests creating the month's row at once fall back to the increment.
    """
    from sqlalchemy.exc import IntegrityError

    def bump() -> int:
        updated = (
            db.query(UsageRecord)
            .filter(UsageRecord.org_id == org_id, UsageRecord.period == period)
            .update({UsageRecord.session_count: UsageRecord.session_count + 1,
                     UsageRecord.updated_at: datetime.now(timezone.utc)}, synchronize_session=False)
        )
        db.commit()
        return updated

    if bump():
        return _usage_count(org_id, period, db)
    try:
        db.add(UsageRecord(org_id=org_id, period=period, session_count=1))
        db.commit()
        return 1
    except IntegrityError:
        db.rollback()  # another request created it first
        bump()
        return _usage_count(org_id, period, db)


def _usage_count(org_id: str, period: str, db: Session) -> int:
    record = db.query(UsageRecord).filter(UsageRecord.org_id == org_id, UsageRecord.period == period).first()
    return int(record.session_count) if record else 0


def update_org_stripe(org_id: str, stripe_customer_id: str, subscription_id: str, tier: str, db: Session) -> None:
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if org:
        org.stripe_customer_id = stripe_customer_id
        org.stripe_subscription_id = subscription_id
        org.tier = tier
        db.commit()


def set_org_tier_for_subscription(subscription_id: str, tier: str, db: Session) -> None:
    """A plan change in Stripe (e.g. from the billing portal): the org follows its subscription."""
    org = db.query(Organization).filter(Organization.stripe_subscription_id == subscription_id).first()
    if org:
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
    """
    Record a person's verdict and make it the session's verdict: a session marked
    "not a failure" stops counting toward problems, rule suggestions and failure
    numbers (and the reverse). The judge's own verdict is kept in judge_passed, so
    judge agreement still compares against what the judge said.
    """
    row = db.query(GoldenLabel).filter(
        GoldenLabel.agent_id == agent_id,
        GoldenLabel.session_id == session_id,
    ).first()
    if row:
        row.human_passed = human_passed
        row.note = note
    else:
        db.add(GoldenLabel(agent_id=agent_id, session_id=session_id, human_passed=human_passed, note=note))
    for ev in db.query(EvalResult).filter(EvalResult.agent_id == agent_id, EvalResult.session_id == session_id,
                                          EvalResult.eval_error == False):  # noqa: E712
        if ev.judge_passed is None:
            ev.judge_passed = ev.passed
        ev.passed = human_passed
        if not human_passed and ev.judge_passed and not ev.failure_reason:
            ev.failure_reason = note or "Marked as a failure by a person."
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
        results = db.query(EvalResult).filter(
            EvalResult.agent_id == agent_id,
            EvalResult.session_id == label.session_id,
            EvalResult.eval_error == False,  # noqa: E712
        ).all()
        # The judge's own verdict, not the person's override of it.
        judge_passed = all((r.passed if r.judge_passed is None else r.judge_passed) for r in results)
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


def get_recent_session_results(agent_id: str, limit: int, db: Session) -> List[Dict[str, Any]]:
    """
    Newest scored sessions with what the user asked (step 1's input), newest first:
    [{"session_id", "passed", "failure_reason", "input", "evaluated_at"}]. Feeds the
    live list while the dashboard waits for a scoring run.
    """
    rows = (
        db.query(EvalResult, AgentLog.input)
        .outerjoin(AgentLog, and_(AgentLog.agent_id == EvalResult.agent_id,
                                  AgentLog.session_id == EvalResult.session_id,
                                  AgentLog.step_number == 1))
        .filter(EvalResult.agent_id == agent_id, EvalResult.eval_error == False)  # noqa: E712
        .order_by(EvalResult.evaluated_at.desc())
        .limit(limit * 3)  # a session can have several result rows
        .all()
    )
    out: Dict[str, Dict[str, Any]] = {}
    for ev, text in rows:
        if ev.session_id not in out:
            out[ev.session_id] = {"session_id": ev.session_id, "passed": bool(ev.passed),
                                  "failure_reason": ev.failure_reason, "input": text or "",
                                  "evaluated_at": ev.evaluated_at}
    return list(out.values())[:limit]


def delete_agent_data(agent_id: str, db: Session) -> Dict[str, int]:
    """Delete everything stored for one agent, and release its name. Returns rows deleted per table."""
    from db.models import BlockFeedback, GoldenLabel, GuardEvent, GuardRule, HeldReply

    counts: Dict[str, int] = {}
    for model in (AgentLog, EvalResult, LossPattern, GuardEvent, GuardRule, BlockFeedback, GoldenLabel,
                  HeldReply, AgentQualityConfig, AgentOrg):
        counts[model.__tablename__] = db.query(model).filter(model.agent_id == agent_id).delete(
            synchronize_session=False)
    db.commit()
    return counts


RETENTION_CHOICES = (30, 90, 180, 365)


def purge_expired_data(db: Session, now: Optional[datetime] = None) -> Dict[str, int]:
    """
    For accounts with a retention period, delete production data older than it:
    steps, verdicts, problems, rule checks, block reviews, labels and held replies.
    Rules and settings are kept. Returns rows deleted per table.
    """
    from db.models import BlockFeedback, GoldenLabel, GuardEvent, HeldReply

    now = now or datetime.now(timezone.utc)
    totals: Dict[str, int] = {}
    for org_id, days in db.query(Organization.id, Organization.retention_days).filter(
            Organization.retention_days.isnot(None)).all():
        agents = [a for (a,) in db.query(AgentOrg.agent_id).filter(AgentOrg.org_id == org_id)]
        if not agents:
            continue
        cutoff = now - timedelta(days=int(days))
        for model, column in ((AgentLog, AgentLog.timestamp), (EvalResult, EvalResult.evaluated_at),
                              (LossPattern, LossPattern.last_seen), (GuardEvent, GuardEvent.timestamp),
                              (BlockFeedback, BlockFeedback.created_at), (GoldenLabel, GoldenLabel.created_at),
                              (HeldReply, HeldReply.created_at)):
            n = db.query(model).filter(model.agent_id.in_(agents), column < cutoff).delete(synchronize_session=False)
            totals[model.__tablename__] = totals.get(model.__tablename__, 0) + n
    db.commit()
    return totals


def get_held_replies(agent_id: str, limit: int, db: Session) -> List[Any]:
    """Replies kalytera.check_reply() stopped before the customer saw them, newest first."""
    from db.models import HeldReply

    return (db.query(HeldReply).filter(HeldReply.agent_id == agent_id)
            .order_by(HeldReply.created_at.desc()).limit(limit).all())
