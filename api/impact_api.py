"""
Did blocking help? The numbers nothing else in Kalytera reports, measured from
judged sessions, rule history and guard decisions (not reported by the customer):

- per rule made from a Failure Feed problem: that problem's failed sessions per
  day before vs after the rule started blocking;
- the agent's failure rate before vs after the first rule started blocking;
- people's verdicts on blocks ("this block was wrong"), so false blocks are counted.

Watch-mode counts ("would have blocked") stay in GET /rules/{id}/stats.

GET  /agents/{agent_id}/impact            before/after, per rule and overall
GET  /agents/{agent_id}/blocks            recent blocked calls, with any verdict
POST /agents/{agent_id}/blocks/feedback   mark a block right or wrong
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.database import get_db
from api.guard_api import ENFORCE, _body, _current_rows, _org_id, _versions
from db.models import BlockFeedback, EvalResult, GuardEvent

DASHBOARD_TEST_PREFIX = "dashboard-test-"  # the dashboard's live checks, not real traffic
BLOCKING = ("DENY", "ESCALATE")
LOOKBACK_DAYS = 182
MIN_DAYS_TO_COMPARE = 7  # less than a week before or after blocking is too little to compare


class FeedbackIn(BaseModel):
    session_id: str
    rule_id: str
    wrong: bool
    note: Optional[str] = None


def _utc(ts: Optional[datetime]) -> Optional[datetime]:
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _org_filter(query: Any, model: Any, org_id: Optional[str]) -> Any:
    return query.filter(model.org_id.is_(None) if org_id is None else model.org_id == org_id)


def _session_verdicts(db: Session, agent_id: str, since: datetime) -> Dict[str, Tuple[bool, datetime, Any, Any]]:
    """session_id -> (failed, judged_at, failure_type, failure_step); a session fails if any result failed."""
    rows = (
        db.query(EvalResult.session_id, EvalResult.passed, EvalResult.evaluated_at,
                 EvalResult.failure_type, EvalResult.failure_step)
        .filter(EvalResult.agent_id == agent_id, EvalResult.eval_error.is_(False), EvalResult.evaluated_at >= since)
        .all()
    )
    out: Dict[str, Tuple[bool, datetime, Any, Any]] = {}
    for sid, passed, at, ftype, fstep in rows:
        prev = out.get(sid)
        failed = not passed
        if prev is None or (failed and not prev[0]):
            out[sid] = (failed, _utc(at), ftype if failed else None, fstep if failed else None)  # type: ignore[assignment]
    return out


def _blocked_sessions(db: Session, org_id: Optional[str], agent_id: str, rule_id: str) -> set:
    q = _org_filter(db.query(GuardEvent.session_id), GuardEvent, org_id).filter(
        GuardEvent.agent_id == agent_id, GuardEvent.rule_id == rule_id, GuardEvent.decision.in_(BLOCKING),
        ~GuardEvent.session_id.startswith(DASHBOARD_TEST_PREFIX))
    return {s for (s,) in q.distinct()}


def _matches_problem(verdict: Tuple[bool, datetime, Any, Any], source: Dict[str, Any]) -> bool:
    failed, _, ftype, fstep = verdict
    if not failed:
        return False
    column = fstep if source.get("pattern_type") == "workflow_step" else ftype
    return str(column) == str(source.get("pattern_value"))


def _per_day_rate(times: List[datetime], start: datetime, end: datetime) -> Optional[float]:
    days = (end - start).total_seconds() / 86400
    if days < MIN_DAYS_TO_COMPARE:
        return None
    return round(sum(1 for t in times if start <= t < end) / days, 2)


def build_report(db: Session, org_id: Optional[str], agent_id: str,
                 now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    verdicts = _session_verdicts(db, agent_id, now - timedelta(days=LOOKBACK_DAYS))
    first_seen = min([v[1] for v in verdicts.values()], default=now)
    feedback = {(f.session_id, f.rule_id): f.wrong for f in _org_filter(
        db.query(BlockFeedback), BlockFeedback, org_id).filter(BlockFeedback.agent_id == agent_id)}

    rules = []
    for row in _current_rows(db, org_id, agent_id):
        rid, source = row.rule_id, _body(row).get("source") or None
        versions = sorted(_versions(db, org_id, agent_id, rid), key=lambda v: v.version)
        enforce = [_utc(v.created_at) for v in versions if v.mode == ENFORCE]
        blocking_since = enforce[0] if enforce else None
        compare = None
        if source and blocking_since:
            times = [v[1] for v in verdicts.values() if _matches_problem(v, source)]
            compare = {"before_per_day": _per_day_rate(times, first_seen, blocking_since),
                       "after_per_day": _per_day_rate(times, blocking_since, now),
                       "days_before": round((blocking_since - first_seen).total_seconds() / 86400, 1),
                       "days_after": round((now - blocking_since).total_seconds() / 86400, 1)}
        blocked = _blocked_sessions(db, org_id, agent_id, rid)
        wrong = sum(1 for s in blocked if feedback.get((s, rid)) is True)
        right = sum(1 for s in blocked if feedback.get((s, rid)) is False)
        rules.append({"rule_id": rid, "mode": row.mode, "problem": source,
                      "blocking_since": blocking_since.isoformat() if blocking_since else None,
                      "problem_before_after": compare,
                      "blocked_sessions": len(blocked), "marked_wrong": wrong, "marked_right": right,
                      "unreviewed": len(blocked) - wrong - right})

    overall = None
    starts = [datetime.fromisoformat(r["blocking_since"]) for r in rules if r["blocking_since"]]
    if starts:
        cut = min(starts)
        before = [v[0] for v in verdicts.values() if v[1] < cut]
        after = [v[0] for v in verdicts.values() if v[1] >= cut]
        overall = {"since": cut.isoformat(),
                   "comparable": (cut - first_seen).days >= MIN_DAYS_TO_COMPARE
                   and (now - cut).days >= MIN_DAYS_TO_COMPARE,
                   "before_sessions": len(before), "before_failed": sum(before),
                   "after_sessions": len(after), "after_failed": sum(after)}
    return {"agent_id": agent_id, "rules": rules, "before_after_blocking": overall,
            "min_days_to_compare": MIN_DAYS_TO_COMPARE}


def recent_blocks(db: Session, org_id: Optional[str], agent_id: str, rule_id: Optional[str],
                  limit: int) -> List[Dict[str, Any]]:
    q = _org_filter(db.query(GuardEvent), GuardEvent, org_id).filter(
        GuardEvent.agent_id == agent_id, GuardEvent.decision.in_(BLOCKING),
        ~GuardEvent.session_id.startswith(DASHBOARD_TEST_PREFIX))
    if rule_id:
        q = q.filter(GuardEvent.rule_id == rule_id)
    events = q.order_by(GuardEvent.timestamp.desc()).limit(limit).all()
    feedback = {(f.session_id, f.rule_id): f for f in _org_filter(
        db.query(BlockFeedback), BlockFeedback, org_id).filter(BlockFeedback.agent_id == agent_id)}
    out = []
    for ev in events:
        f = feedback.get((ev.session_id, ev.rule_id))
        out.append({"session_id": ev.session_id, "tool": ev.tool, "rule_id": ev.rule_id,
                    "decision": ev.decision, "at": _utc(ev.timestamp).isoformat(),  # type: ignore[union-attr]
                    "verdict": None if f is None else ("wrong" if f.wrong else "right"),
                    "note": f.note if f else None})
    return out


def build_router(resolve_org: Callable[..., Any],
                 agent_ids_for_org: Callable[[str, Session], List[str]]) -> APIRouter:
    router = APIRouter(tags=["impact"])

    def _check(agent_id: str, org: Any, db: Session) -> None:
        if org is not None and agent_id not in agent_ids_for_org(org.id, db):
            raise HTTPException(status_code=404, detail="agent not found")

    @router.get("/agents/{agent_id}/impact")
    async def impact(agent_id: str, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        _check(agent_id, org, db)
        return build_report(db, _org_id(org), agent_id)

    @router.get("/agents/{agent_id}/blocks")
    async def blocks(agent_id: str, rule_id: Optional[str] = None, limit: int = 20, org=Depends(resolve_org),
                     db: Session = Depends(get_db)) -> Dict[str, Any]:
        _check(agent_id, org, db)
        return {"blocks": recent_blocks(db, _org_id(org), agent_id, rule_id, max(1, min(limit, 100)))}

    @router.post("/agents/{agent_id}/blocks/feedback")
    async def block_feedback(agent_id: str, body: FeedbackIn, org=Depends(resolve_org),
                             db: Session = Depends(get_db)) -> Dict[str, Any]:
        _check(agent_id, org, db)
        oid = _org_id(org)
        seen = _org_filter(db.query(GuardEvent.id), GuardEvent, oid).filter(
            GuardEvent.agent_id == agent_id, GuardEvent.session_id == body.session_id,
            GuardEvent.rule_id == body.rule_id, GuardEvent.decision.in_(BLOCKING)).first()
        if seen is None:
            raise HTTPException(status_code=404, detail="no block by that rule in that session")
        row = _org_filter(db.query(BlockFeedback), BlockFeedback, oid).filter(
            BlockFeedback.agent_id == agent_id, BlockFeedback.session_id == body.session_id,
            BlockFeedback.rule_id == body.rule_id).first()
        if row is None:
            row = BlockFeedback(org_id=oid, agent_id=agent_id, session_id=body.session_id, rule_id=body.rule_id,
                                wrong=body.wrong, note=body.note)
            db.add(row)
        else:
            row.wrong, row.note = body.wrong, body.note
        db.commit()
        return {"session_id": body.session_id, "rule_id": body.rule_id,
                "verdict": "wrong" if body.wrong else "right"}

    return router
