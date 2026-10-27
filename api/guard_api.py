"""
Guard rules API — storage and server-side evaluation for kalytera.guard().

  GET    /rules?agent_id=X              — current rules (the SDK caches these)
  POST   /rules                         — create a rule (version 1, shadow by default)
  GET    /rules/{rule_id}?agent_id=X    — current rule + version history
  PUT    /rules/{rule_id}               — edit: new version, mode unchanged
  POST   /rules/{rule_id}/promote       — shadow → enforce (new version)
  POST   /rules/{rule_id}/demote        — enforce → shadow (new version)
  DELETE /rules/{rule_id}?agent_id=X    — deactivate every version
  GET    /rules/{rule_id}/stats?agent_id=X — would-block / deny counts
  POST   /rules/draft                   — draft a rule from a LossPattern (not saved)
  GET    /rules/suggestions?agent_id=X  — drafts for every detected pattern, deduped, cited;
                                          by_pattern says what each pattern can get
  GET    /rules/starter?agent_id=X      — before anything goes wrong: "a person approves it first" for the
                                          agent's actions that move money, delete things or change accounts
  POST   /guard                         — evaluate one call server-side (non-Python callers)
  POST   /guard/events                  — decisions reported by the SDK

Scoped by org: a key only sees its own org's rules. Guard traffic never
counts against the monthly session limit. See docs/specs/failure-to-rule.md.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.database import get_db
from db.models import AgentLog, EvalResult, GuardEvent, GuardRule, LossPattern
from db.queries import get_step_names, step_label
from kalytera.drafts import draft_rule
from kalytera.starter import starter_rules
from kalytera.rules import ALLOW, ENFORCE, SHADOW, RuleError, SessionHistory, evaluate, parse_rule

MAX_EVENTS_PER_BATCH = 500
MAX_SUGGESTIONS = 5
MAX_PASSING_SHARE = 0.1   # skip suggestions that would match more than 10% of successful sessions
DRAFT_SESSION_LIMIT = 200
STARTER_LOG_LIMIT = 2000  # recent steps read to see which actions an agent takes


class GuardRequest(BaseModel):
    agent_id: str
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)
    session_id: str = ""


class DraftRequest(BaseModel):
    pattern_id: str


class GuardEventIn(BaseModel):
    agent_id: str
    session_id: str = ""
    tool: str
    args_hash: str = ""
    decision: str
    rule_id: Optional[str] = None
    rule_version: Optional[int] = None
    shadow_hits: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None
    timestamp: Optional[datetime] = None


class GuardEventsIn(BaseModel):
    events: List[GuardEventIn]


def args_hash(args: Dict[str, Any]) -> str:
    """Stable short hash of call arguments — events record this, never raw args."""
    raw = json.dumps(args, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _org_id(org: Any) -> Optional[str]:
    return org.id if org is not None else None


def _current_rows(db: Session, org_id: Optional[str], agent_id: str) -> List[GuardRule]:
    """Highest active version of every rule for this org + agent."""
    rows = (
        db.query(GuardRule)
        .filter(GuardRule.org_id.is_(None) if org_id is None else GuardRule.org_id == org_id)
        .filter(GuardRule.agent_id == agent_id, GuardRule.is_active.is_(True))
        .order_by(GuardRule.rule_id, GuardRule.version.desc())
        .all()
    )
    latest: Dict[str, GuardRule] = {}
    for row in rows:
        latest.setdefault(row.rule_id, row)
    return sorted(latest.values(), key=lambda r: r.created_at)


def _versions(db: Session, org_id: Optional[str], agent_id: str, rule_id: str) -> List[GuardRule]:
    return (
        db.query(GuardRule)
        .filter(GuardRule.org_id.is_(None) if org_id is None else GuardRule.org_id == org_id)
        .filter(GuardRule.agent_id == agent_id, GuardRule.rule_id == rule_id, GuardRule.is_active.is_(True))
        .order_by(GuardRule.version.desc())
        .all()
    )


def _body(row: GuardRule) -> Dict[str, Any]:
    return json.loads(row.body)


def _validate(raw: Dict[str, Any]) -> Dict[str, Any]:
    try:
        parse_rule(raw)
    except RuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return raw


def _insert(db: Session, org_id: Optional[str], raw: Dict[str, Any]) -> Dict[str, Any]:
    raw = _validate(raw)
    db.add(GuardRule(
        org_id=org_id, agent_id=raw["agent_id"], rule_id=raw["id"],
        version=raw["version"], mode=raw["mode"], body=json.dumps(raw),
    ))
    db.commit()
    return raw


def _require_current(db: Session, org_id: Optional[str], agent_id: str, rule_id: str) -> GuardRule:
    versions = _versions(db, org_id, agent_id, rule_id)
    if not versions:
        raise HTTPException(status_code=404, detail=f"rule {rule_id} not found for agent {agent_id}")
    return versions[0]


def _new_version(db: Session, org_id: Optional[str], current: GuardRule, changes: Dict[str, Any]) -> Dict[str, Any]:
    raw = {**_body(current), **changes, "version": current.version + 1}
    return _insert(db, org_id, raw)


def _history_from_events(db: Session, org_id: Optional[str], agent_id: str, session_id: str,
                         window_seconds: float) -> SessionHistory:
    """Allowed calls in this session, for count_in_window when evaluating server-side."""
    history = SessionHistory()
    if not session_id:
        return history
    since = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    rows = (
        db.query(GuardEvent.tool, GuardEvent.timestamp)
        .filter(GuardEvent.org_id.is_(None) if org_id is None else GuardEvent.org_id == org_id)
        .filter(GuardEvent.agent_id == agent_id, GuardEvent.session_id == session_id,
                GuardEvent.decision == ALLOW, GuardEvent.timestamp >= since)
        .all()
    )
    for tool, ts in rows:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        history.record(session_id, tool, ts.timestamp())
    return history


def _record(db: Session, org_id: Optional[str], ev: GuardEventIn, source: str) -> None:
    db.add(GuardEvent(
        org_id=org_id, agent_id=ev.agent_id, session_id=ev.session_id or "", tool=ev.tool,
        args_hash=ev.args_hash, decision=ev.decision, rule_id=ev.rule_id or None,
        rule_version=ev.rule_version, shadow_hits=json.dumps(ev.shadow_hits) if ev.shadow_hits else None,
        error=ev.error, source=source, timestamp=ev.timestamp or datetime.now(timezone.utc),
    ))


def _session_tool_calls(db: Session, agent_id: str, session_ids: List[str]) -> List[List[Dict[str, Any]]]:
    """Tool calls of each session, in step order."""
    if not session_ids:
        return []
    by_session: Dict[str, List[Dict[str, Any]]] = {sid: [] for sid in session_ids}
    rows = (
        db.query(AgentLog.session_id, AgentLog.tool_calls)
        .filter(AgentLog.agent_id == agent_id, AgentLog.session_id.in_(session_ids))
        .order_by(AgentLog.session_id, AgentLog.step_number)
        .all()
    )
    for sid, raw in rows:
        try:
            calls = json.loads(raw) if raw else []
        except ValueError:
            calls = []
        by_session[sid].extend(c for c in calls if isinstance(c, dict))
    return list(by_session.values())


def _draft_for_pattern(db: Session, pattern: LossPattern) -> Dict[str, Any]:
    base = db.query(EvalResult.session_id).filter(EvalResult.agent_id == pattern.agent_id)
    if pattern.pattern_type == "workflow_step":
        failing_q = base.filter(EvalResult.passed.is_(False), EvalResult.failure_step == pattern.pattern_value)
    elif pattern.pattern_type == "action":
        failing_q = base.filter(EvalResult.passed.is_(False), EvalResult.failure_action == pattern.pattern_value)
    else:
        failing_q = base.filter(EvalResult.passed.is_(False), EvalResult.failure_type == pattern.pattern_value)
    failing = [r[0] for r in failing_q.distinct().limit(DRAFT_SESSION_LIMIT).all()]
    passing = [r[0] for r in base.filter(EvalResult.passed.is_(True)).distinct().limit(DRAFT_SESSION_LIMIT).all()]
    passing = [s for s in passing if s not in set(failing)]
    label = pattern.pattern_value
    if pattern.pattern_type == "workflow_step":
        label = step_label(label, get_step_names(pattern.agent_id, db))
    return draft_rule(
        pattern.agent_id, pattern.pattern_type, label,
        _session_tool_calls(db, pattern.agent_id, failing),
        _session_tool_calls(db, pattern.agent_id, passing),
        root_cause=pattern.root_cause,
    )


def _rule_key(rule: Dict[str, Any]) -> str:
    return json.dumps({k: rule.get(k) or None for k in ("match", "session_conditions", "action")}, sort_keys=True)


def _suggestions(db: Session, org_id: Optional[str], agent_id: str) -> Dict[str, Any]:
    """
    {"suggestions": [...], "by_pattern": {pattern_id: {...}}}

    suggestions: one per distinct drafted rule, most failures first. Patterns
    that draft the same rule are merged; rules the agent already has are skipped.
    by_pattern: for every pattern, what can be done about it — status
    "suggested" (with the rule and its coverage), "exists" (an existing rule
    already does this) or "none" (with the reason, in plain English).
    """
    existing = {_rule_key(_body(r)): (r.rule_id, r.mode) for r in _current_rows(db, org_id, agent_id)}
    patterns = (db.query(LossPattern).filter(LossPattern.agent_id == agent_id)
                .order_by(LossPattern.failure_count.desc()).all())
    merged: Dict[str, Dict[str, Any]] = {}
    by_pattern: Dict[str, Dict[str, Any]] = {}
    for p in patterns:
        draft = _draft_for_pattern(db, p)
        rule = draft.get("rule")
        cov = draft.get("coverage") or {}
        if not rule:
            by_pattern[p.id] = {"status": "none", "reason": " ".join(draft.get("warnings", [])[:1])
                                or "No rule could be drafted from these sessions."}
            continue
        if not cov.get("failing_matched"):
            by_pattern[p.id] = {"status": "none",
                                "reason": "No tool call or argument separates these sessions from successful ones."}
            continue
        # Only suggest rules that would rarely touch sessions that went fine.
        if cov.get("passing_total") and cov["passing_matched"] / cov["passing_total"] > MAX_PASSING_SHARE:
            by_pattern[p.id] = {"status": "none",
                                "reason": f"The closest rule would also hit {cov['passing_matched']} of "
                                          f"{cov['passing_total']} successful sessions, so it isn't suggested."}
            continue
        key = _rule_key(rule)
        if key in existing:
            rule_id, mode = existing[key]
            by_pattern[p.id] = {"status": "exists", "rule_id": rule_id, "mode": mode, "rule": rule, "coverage": cov}
            continue
        by_pattern[p.id] = {"status": "suggested", "rule": rule, "coverage": cov,
                            "evidence": draft.get("evidence", []), "warnings": draft.get("warnings", [])}
        cite = {"pattern_id": p.id, "pattern_type": p.pattern_type, "pattern_value": p.pattern_value,
                "failure_count": p.failure_count, "root_cause": p.root_cause}
        if key in merged:
            merged[key]["patterns"].append(cite)
            continue
        merged[key] = {**draft, "patterns": [cite]}
    ranked = sorted(merged.values(), key=lambda d: (-(d["coverage"] or {}).get("failing_matched", 0),
                                                    (d["coverage"] or {}).get("passing_matched", 0)))
    return {"suggestions": ranked[:MAX_SUGGESTIONS], "by_pattern": by_pattern}


def _starter(db: Session, org_id: Optional[str], agent_id: str) -> List[Dict[str, Any]]:
    """Starter rules for actions that don't have a rule yet."""
    ruled = {_body(r).get("match", {}).get("tool") for r in _current_rows(db, org_id, agent_id)}
    rows = (db.query(AgentLog.tool_calls).filter(AgentLog.agent_id == agent_id, AgentLog.tool_calls.isnot(None))
            .order_by(AgentLog.timestamp.desc()).limit(STARTER_LOG_LIMIT).all())
    actions = []
    for (raw,) in rows:
        try:
            calls = json.loads(raw) if raw else []
        except ValueError:
            continue
        for c in calls if isinstance(calls, list) else []:
            if isinstance(c, dict) and c.get("name"):
                args = c.get("input", c.get("args"))
                actions.append((str(c["name"]), args if isinstance(args, dict) else {}))
    return [s for s in starter_rules(agent_id, actions) if s["rule"]["match"]["tool"] not in ruled]


def build_router(resolve_org: Callable[..., Any],
                 agent_ids_for_org: Optional[Callable[[str, Session], List[str]]] = None) -> APIRouter:
    """
    resolve_org: the API-key dependency (no session-limit check).
    agent_ids_for_org: agents an org may read patterns for (None = no check).
    """
    router = APIRouter(tags=["guard"])

    @router.get("/rules/suggestions")
    async def suggestions(agent_id: str, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        if org is not None and agent_ids_for_org is not None and agent_id not in agent_ids_for_org(org.id, db):
            raise HTTPException(status_code=404, detail="agent not found")
        return {"agent_id": agent_id, **_suggestions(db, _org_id(org), agent_id)}

    @router.get("/rules/starter")
    async def starter(agent_id: str, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        if org is not None and agent_ids_for_org is not None and agent_id not in agent_ids_for_org(org.id, db):
            raise HTTPException(status_code=404, detail="agent not found")
        return {"agent_id": agent_id, "starter": _starter(db, _org_id(org), agent_id)}

    @router.post("/rules/draft")
    async def draft(req: DraftRequest, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        pattern = db.query(LossPattern).filter(LossPattern.id == req.pattern_id).first()
        allowed = (org is None or agent_ids_for_org is None
                   or (pattern is not None and pattern.agent_id in agent_ids_for_org(org.id, db)))
        if pattern is None or not allowed:
            raise HTTPException(status_code=404, detail="pattern not found")
        return _draft_for_pattern(db, pattern)

    @router.get("/rules")
    async def list_rules(agent_id: str, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        return {"agent_id": agent_id, "rules": [_body(r) for r in _current_rows(db, _org_id(org), agent_id)]}

    @router.post("/rules", status_code=201)
    async def create_rule(rule: Dict[str, Any], org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        if not isinstance(rule.get("agent_id"), str) or not rule["agent_id"]:
            raise HTTPException(status_code=422, detail="agent_id is required")
        if _versions(db, _org_id(org), rule["agent_id"], str(rule.get("id", ""))):
            raise HTTPException(status_code=409, detail=f"rule {rule.get('id')} already exists — use PUT to edit")
        # New rules always start in shadow mode; enforcing needs an explicit promote.
        # A re-created (previously deleted) rule continues its version numbers; history is kept.
        oid = _org_id(org)
        last = (
            db.query(func.max(GuardRule.version))
            .filter(GuardRule.org_id.is_(None) if oid is None else GuardRule.org_id == oid)
            .filter(GuardRule.agent_id == rule["agent_id"], GuardRule.rule_id == str(rule.get("id", "")))
            .scalar()
        )
        return _insert(db, oid, {**rule, "version": (last or 0) + 1, "mode": SHADOW})

    @router.get("/rules/{rule_id}")
    async def get_rule(rule_id: str, agent_id: str, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        versions = _versions(db, _org_id(org), agent_id, rule_id)
        if not versions:
            raise HTTPException(status_code=404, detail=f"rule {rule_id} not found for agent {agent_id}")
        return {
            "rule": _body(versions[0]),
            "versions": [{"version": v.version, "mode": v.mode, "created_at": v.created_at, "rule": _body(v)}
                         for v in versions],
        }

    @router.put("/rules/{rule_id}")
    async def edit_rule(rule_id: str, rule: Dict[str, Any], org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        current = _require_current(db, _org_id(org), str(rule.get("agent_id", "")), rule_id)
        # Mode only changes through promote/demote.
        changes = {k: v for k, v in rule.items() if k not in ("id", "agent_id", "version", "mode")}
        return _new_version(db, _org_id(org), current, changes)

    @router.post("/rules/{rule_id}/promote")
    async def promote_rule(rule_id: str, agent_id: str, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        current = _require_current(db, _org_id(org), agent_id, rule_id)
        if current.mode == ENFORCE:
            raise HTTPException(status_code=409, detail=f"rule {rule_id} is already in enforce mode")
        return {"rule": _new_version(db, _org_id(org), current, {"mode": ENFORCE}),
                "shadow_summary": _stats(db, _org_id(org), agent_id, rule_id)}

    @router.post("/rules/{rule_id}/demote")
    async def demote_rule(rule_id: str, agent_id: str, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        current = _require_current(db, _org_id(org), agent_id, rule_id)
        if current.mode == SHADOW:
            raise HTTPException(status_code=409, detail=f"rule {rule_id} is already in shadow mode")
        return {"rule": _new_version(db, _org_id(org), current, {"mode": SHADOW})}

    @router.delete("/rules/{rule_id}")
    async def delete_rule(rule_id: str, agent_id: str, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        versions = _versions(db, _org_id(org), agent_id, rule_id)
        if not versions:
            raise HTTPException(status_code=404, detail=f"rule {rule_id} not found for agent {agent_id}")
        for v in versions:
            v.is_active = False
        db.commit()
        return {"rule_id": rule_id, "status": "deleted"}

    @router.get("/rules/{rule_id}/stats")
    async def rule_stats(rule_id: str, agent_id: str, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        _require_current(db, _org_id(org), agent_id, rule_id)
        return _stats(db, _org_id(org), agent_id, rule_id)

    @router.post("/guard")
    async def guard(req: GuardRequest, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        oid = _org_id(org)
        rules = [parse_rule(_body(r)) for r in _current_rows(db, oid, req.agent_id)]
        window = max((c["window_seconds"] for r in rules for c in r.session_conditions), default=0)
        history = _history_from_events(db, oid, req.agent_id, req.session_id, window) if window else None
        d = evaluate(rules, req.tool, req.args, req.session_id, history)
        hits = [{"rule_id": h.rule_id, "rule_version": h.rule_version, "action": h.action} for h in d.shadow_hits]
        _record(db, oid, GuardEventIn(
            agent_id=req.agent_id, session_id=req.session_id, tool=req.tool, args_hash=args_hash(req.args),
            decision=d.decision, rule_id=d.rule_id or None, rule_version=d.rule_version or None, shadow_hits=hits,
        ), source="api")
        db.commit()
        return {"decision": d.decision, "rule_id": d.rule_id, "rule_version": d.rule_version,
                "reason": d.reason, "shadow_hits": hits}

    @router.post("/guard/events", status_code=202)
    async def guard_events(batch: GuardEventsIn, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        events = batch.events[:MAX_EVENTS_PER_BATCH]
        for ev in events:
            _record(db, _org_id(org), ev, source="sdk")
        db.commit()
        return {"accepted": len(events)}

    return router


def _stats(db: Session, org_id: Optional[str], agent_id: str, rule_id: str) -> Dict[str, Any]:
    """Shadow would-blocks and enforce decisions for one rule, across all its versions."""
    base = (
        db.query(GuardEvent)
        .filter(GuardEvent.org_id.is_(None) if org_id is None else GuardEvent.org_id == org_id)
        .filter(GuardEvent.agent_id == agent_id)
        .filter(~GuardEvent.session_id.startswith("dashboard-test-"))  # the dashboard's live checks
    )
    enforced = dict(
        base.filter(GuardEvent.rule_id == rule_id)
        .with_entities(GuardEvent.decision, func.count())
        .group_by(GuardEvent.decision).all()
    )
    # shadow_hits is JSON text; LIKE narrows, json.loads confirms.
    would_block_sessions: set = set()
    would_block = 0
    for session_id, hits in base.filter(GuardEvent.shadow_hits.like(f'%"{rule_id}"%')).with_entities(
        GuardEvent.session_id, GuardEvent.shadow_hits
    ):
        if any(h.get("rule_id") == rule_id for h in json.loads(hits or "[]")):
            would_block += 1
            would_block_sessions.add(session_id)
    failed = 0
    if would_block_sessions:
        failed = (
            db.query(func.count(func.distinct(EvalResult.session_id)))
            .filter(EvalResult.agent_id == agent_id, EvalResult.session_id.in_(would_block_sessions),
                    EvalResult.passed.is_(False))
            .scalar() or 0
        )
    return {
        "rule_id": rule_id,
        "would_block": would_block,
        "would_block_sessions": len(would_block_sessions),
        "would_block_sessions_that_failed": failed,
        "denied": enforced.get("DENY", 0),
        "escalated": enforced.get("ESCALATE", 0),
    }
