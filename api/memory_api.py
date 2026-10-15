"""
Memory beyond one agent.

Account: a rule proven on one of your agents is offered to your other agents that
take the same action — only after it's checked on that agent's own conversations.

All agents (anonymous): with "Anonymous pattern sharing" on (the default; one click
off), each account contributes anonymous facts — a mistake type from Kalytera's fixed
list, an action category (refund, payment…), a rule shape ("blocked above an amount")
— by industry, agent type and system. Never text, names, IDs, tool or agent names,
custom dimension names or anyone's limits. A fact is shown only when at least
MIN_COMPANIES different accounts share it. Turning sharing off deletes the account's facts.

  GET/PUT /agents/{agent_id}/profile          industry, agent type, system
  GET/PUT /account/sharing                    the sharing switch
  GET     /agents/{agent_id}/known-problems   what similar agents get wrong (≥ MIN_COMPANIES)
  GET     /agents/{agent_id}/rules/from-account  rules from your other agents, checked here
"""
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.database import get_db
from db.models import AgentLog, AgentOrg, EvalResult, GlobalFact, LossPattern, Organization
from kalytera.prompts import FAILURE_TYPES

MIN_COMPANIES = 5
SAMPLE_SESSIONS = 200  # sessions read when checking a rule on another agent

INDUSTRIES = {"retail": "Retail & e-commerce", "fintech": "Fintech & banking", "insurance": "Insurance",
              "healthcare": "Healthcare", "travel": "Travel & hospitality", "saas": "SaaS & software",
              "telecom": "Telecom", "education": "Education", "other": "Other"}
AGENT_TYPES = {"support": "Customer support", "sales": "Sales", "operations": "Operations", "voice": "Voice",
               "research": "Research", "coding": "Coding", "other": "Other"}
SYSTEMS = {"openai_agents": "OpenAI Agents SDK", "langchain": "LangGraph / LangChain", "langfuse": "Langfuse",
           "langsmith": "LangSmith", "custom": "Custom"}

_CATEGORIES: List[Tuple[str, Tuple[str, ...]]] = [
    ("refund", ("refund", "reimburs", "chargeback")),
    ("payment", ("pay", "charge", "invoice", "billing", "transfer", "withdraw", "deposit")),
    ("booking", ("book", "reserv", "appointment", "schedule", "cancel_booking")),
    ("order", ("order", "cart", "checkout", "ship", "deliver", "return")),
    ("account", ("account", "user", "profile", "password", "login", "subscription", "plan")),
    ("message", ("email", "sms", "message", "send", "notify", "slack", "reply")),
    ("handoff", ("ticket", "escalat", "handoff", "human", "agent_transfer")),
    ("data_write", ("update", "create", "delete", "write", "insert", "save", "modify", "set_")),
    ("search", ("search", "lookup", "find", "get", "fetch", "query", "retrieve", "read", "list")),
]


def org_hash(org_id: str) -> str:
    return hashlib.sha256(f"kalytera-share:{org_id}".encode()).hexdigest()[:24]


def action_category(tool_name: str) -> str:
    name = (tool_name or "").lower()
    for category, words in _CATEGORIES:
        if any(w in name for w in words):
            return category
    return "other"


def rule_shape(rule: Dict[str, Any]) -> str:
    """'amount_above' / 'repeated' / 'value_match' — the kind of limit, never its value."""
    if rule.get("session_conditions"):
        return "repeated"
    args = (rule.get("match") or {}).get("args") or []
    if not args:
        return "always"
    a = args[0]
    field = str(a.get("field", "")).lower()
    if re.search(r"amount|price|total|sum|cost|value|fee|refund", field):
        kind = "amount"
    elif isinstance(a.get("value"), (int, float)):
        kind = "number"
    else:
        kind = "value"
    op = a.get("op")
    return f"{kind}_{'above' if op in ('>', '>=') else 'below' if op in ('<', '<=') else 'match'}"


def _fact_id(h: str, seg: Tuple[str, str, str], kind: str, ft: str, cat: str, shape: str) -> str:
    return hashlib.sha256("|".join((h, *seg, kind, ft, cat, shape)).encode()).hexdigest()[:32]


def _failed_categories(db: Session, agent_id: str, session_ids: List[str]) -> Counter:
    counts: Counter = Counter()
    for (raw,) in db.query(AgentLog.tool_calls).filter(AgentLog.agent_id == agent_id,
                                                       AgentLog.session_id.in_(session_ids[:SAMPLE_SESSIONS])):
        for c in json.loads(raw) if raw else []:
            if isinstance(c, dict) and (c.get("success") is False or c.get("blocked")):
                counts[action_category(c.get("name", ""))] += 1
    return counts


def refresh_shared_facts(db: Session, now: Optional[datetime] = None) -> int:
    """Hourly: rebuild each sharing account's anonymous facts; delete facts of accounts that turned it off."""
    from api.guard_api import _body, _current_rows

    now = now or datetime.now(timezone.utc)
    written = 0
    for org in db.query(Organization).all():
        h = org_hash(org.id)
        db.query(GlobalFact).filter(GlobalFact.org_hash == h).delete()
        if not getattr(org, "share_patterns", True):
            continue
        facts: Dict[str, GlobalFact] = {}
        for ao in db.query(AgentOrg).filter(AgentOrg.org_id == org.id):
            if not (ao.industry and ao.agent_type):
                continue  # no profile, nothing to compare with
            seg = (ao.industry, ao.agent_type, ao.system or "custom")
            for p in db.query(LossPattern).filter(LossPattern.agent_id == ao.agent_id,
                                                  LossPattern.pattern_type == "failure_type"):
                if p.pattern_value not in FAILURE_TYPES:
                    continue  # custom dimension names can identify a company
                sessions = [s for (s,) in db.query(EvalResult.session_id).filter(
                    EvalResult.agent_id == ao.agent_id, EvalResult.passed.is_(False),
                    EvalResult.failure_type == p.pattern_value).distinct().limit(SAMPLE_SESSIONS)]
                top = _failed_categories(db, ao.agent_id, sessions).most_common(1)
                cat = top[0][0] if top else ""
                fid = _fact_id(h, seg, "problem", p.pattern_value, cat, "")
                facts[fid] = GlobalFact(id=fid, org_hash=h, industry=seg[0], agent_type=seg[1], system=seg[2],
                                        kind="problem", failure_type=p.pattern_value, action_category=cat,
                                        rule_shape="", last_seen=now)
            for row in _current_rows(db, org.id, ao.agent_id):
                rule = _body(row)
                cat, shape = action_category((rule.get("match") or {}).get("tool", "")), rule_shape(rule)
                fid = _fact_id(h, seg, "rule", "", cat, shape)
                facts[fid] = GlobalFact(id=fid, org_hash=h, industry=seg[0], agent_type=seg[1], system=seg[2],
                                        kind="rule", failure_type="", action_category=cat, rule_shape=shape,
                                        last_seen=now)
        db.add_all(facts.values())
        written += len(facts)
    db.commit()
    return written


def known_problems(db: Session, industry: str, agent_type: str, exclude_org: str,
                   min_companies: int = MIN_COMPANIES) -> Dict[str, List[Dict[str, Any]]]:
    """What agents like this one get wrong, and the rule shapes that stopped it — only patterns ≥ min_companies."""
    out: Dict[str, List[Dict[str, Any]]] = {"problems": [], "rules": []}
    q = (db.query(GlobalFact.kind, GlobalFact.failure_type, GlobalFact.action_category, GlobalFact.rule_shape,
                  func.count(func.distinct(GlobalFact.org_hash)))
         .filter(GlobalFact.industry == industry, GlobalFact.agent_type == agent_type,
                 GlobalFact.org_hash != org_hash(exclude_org))
         .group_by(GlobalFact.kind, GlobalFact.failure_type, GlobalFact.action_category, GlobalFact.rule_shape))
    for kind, ft, cat, shape, n in q.all():
        if n < min_companies:
            continue
        item = {"failure_type": ft, "action_category": cat, "rule_shape": shape, "companies": int(n)}
        out["problems" if kind == "problem" else "rules"].append(item)
    for items in out.values():
        items.sort(key=lambda i: -i["companies"])
    return out


def rules_from_account(db: Session, org_id: str, agent_id: str) -> List[Dict[str, Any]]:
    """Rules on your other agents for an action this agent also takes, with coverage on this agent's sessions."""
    from api.guard_api import _body, _current_rows, _rule_key, _session_tool_calls
    from kalytera.drafts import coverage

    mine = {_rule_key(_body(r)) for r in _current_rows(db, org_id, agent_id)}
    tools_here: set = set()
    for (raw,) in db.query(AgentLog.tool_calls).filter(AgentLog.agent_id == agent_id,
                                                       AgentLog.tool_calls.isnot(None)).limit(2000):
        tools_here.update(c.get("name") for c in (json.loads(raw) if raw else []) if isinstance(c, dict))
    if not tools_here:
        return []
    verdicts = db.query(EvalResult.session_id, EvalResult.passed).filter(EvalResult.agent_id == agent_id).all()
    failing = list({s for s, ok in verdicts if not ok})[:SAMPLE_SESSIONS]
    passing = list({s for s, ok in verdicts if ok} - set(failing))[:SAMPLE_SESSIONS]
    calls_f, calls_p = _session_tool_calls(db, agent_id, failing), _session_tool_calls(db, agent_id, passing)
    out, seen = [], set()
    others = [a for (a,) in db.query(AgentOrg.agent_id).filter(AgentOrg.org_id == org_id, AgentOrg.agent_id != agent_id)]
    for other in others:
        for row in _current_rows(db, org_id, other):
            rule = _body(row)
            key = _rule_key(rule)
            if (rule.get("match") or {}).get("tool") not in tools_here or key in mine or key in seen:
                continue
            seen.add(key)
            cov = coverage({**rule, "agent_id": agent_id}, calls_f, calls_p)
            out.append({"from_agent": other, "mode": row.mode, "rule": {**rule, "agent_id": agent_id},
                        "coverage": cov})
    out.sort(key=lambda r: (-r["coverage"]["failing_matched"], r["coverage"]["passing_matched"]))
    return out


class ProfileIn(BaseModel):
    industry: Optional[str] = None
    agent_type: Optional[str] = None
    system: Optional[str] = None


class SharingIn(BaseModel):
    share_patterns: bool


def build_router(resolve_org: Callable[..., Any],
                 agent_ids_for_org: Callable[[str, Session], List[str]]) -> APIRouter:
    router = APIRouter(tags=["memory"])

    def _org(org: Any) -> str:
        if org is None or not getattr(org, "id", None):
            raise HTTPException(status_code=403, detail="sign in with your account's API key")
        return org.id

    def _agent(agent_id: str, org_id: str, db: Session) -> AgentOrg:
        row = db.query(AgentOrg).filter(AgentOrg.agent_id == agent_id, AgentOrg.org_id == org_id).first()
        if row is None:
            raise HTTPException(status_code=404, detail="agent not found")
        return row

    @router.get("/agents/{agent_id}/profile")
    async def get_profile(agent_id: str, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        row = _agent(agent_id, _org(org), db)
        return {"industry": row.industry, "agent_type": row.agent_type, "system": row.system,
                "choices": {"industry": INDUSTRIES, "agent_type": AGENT_TYPES, "system": SYSTEMS}}

    @router.put("/agents/{agent_id}/profile")
    async def set_profile(agent_id: str, body: ProfileIn, org=Depends(resolve_org),
                          db: Session = Depends(get_db)) -> Dict[str, Any]:
        row = _agent(agent_id, _org(org), db)
        for field, allowed in (("industry", INDUSTRIES), ("agent_type", AGENT_TYPES), ("system", SYSTEMS)):
            value = getattr(body, field)
            if value is not None and value not in allowed:
                raise HTTPException(status_code=422, detail=f"{field} must be one of {list(allowed)}")
            if value is not None:
                setattr(row, field, value)
        db.commit()
        return {"industry": row.industry, "agent_type": row.agent_type, "system": row.system}

    @router.get("/account/sharing")
    async def get_sharing(org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        row = db.query(Organization).filter(Organization.id == _org(org)).first()
        return {"share_patterns": bool(getattr(row, "share_patterns", True)) if row else True}

    @router.put("/account/sharing")
    async def set_sharing(body: SharingIn, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        org_id = _org(org)
        row = db.query(Organization).filter(Organization.id == org_id).first()
        if row is None:
            raise HTTPException(status_code=404, detail="account not found")
        row.share_patterns = body.share_patterns
        if not body.share_patterns:  # off means off now, not at the next hourly refresh
            db.query(GlobalFact).filter(GlobalFact.org_hash == org_hash(org_id)).delete()
        db.commit()
        return {"share_patterns": body.share_patterns}

    @router.get("/agents/{agent_id}/known-problems")
    async def known(agent_id: str, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        org_id = _org(org)
        row = _agent(agent_id, org_id, db)
        if not (row.industry and row.agent_type):
            return {"profile": False, "problems": [], "rules": [], "min_companies": MIN_COMPANIES}
        return {"profile": True, **known_problems(db, row.industry, row.agent_type, org_id),
                "min_companies": MIN_COMPANIES}

    @router.get("/agents/{agent_id}/rules/from-account")
    async def from_account(agent_id: str, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        org_id = _org(org)
        _agent(agent_id, org_id, db)
        return {"rules": rules_from_account(db, org_id, agent_id)}

    return router
