"""
Replies stopped before the customer saw them (kalytera.check_reply()).

  POST /replies/held     the SDK's own check held a reply: store it, tell Slack now
  POST /replies/review   the AI reviewer reads a high-stakes reply before it's sent: {"hold", "reason"};
                         a held one is stored and sent to Slack like the above

The reviewer is told to hold only replies that could hurt the customer or the business, and to let
everything else through: a reply it isn't sure about goes out.
"""
import json
import logging
import os
import re
import threading
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.database import get_db
from db.models import AgentOrg, HeldReply

logger = logging.getLogger("kalytera.replies")

REVIEW_DAILY_LIMIT = int(os.getenv("KALYTERA_REVIEW_DAILY_LIMIT", "2000"))  # per account, to cap the AI's cost
TEXT_CHARS = 4000

_count_lock = threading.Lock()
_reviews_today: Dict[str, int] = {}

REVIEW_SYSTEM = (
    "You check an AI agent's reply to a customer BEFORE it is sent. You respond with JSON only: "
    '{"hold": true or false, "reason": "..."}. No prose, no markdown.'
)


class HeldIn(BaseModel):
    agent_id: str
    session_id: str = ""
    reply: str
    reason: str
    checked_by: str = "code"


class ReviewIn(BaseModel):
    agent_id: str
    session_id: str = ""
    message: str = ""
    reply: str
    actions: List[Dict[str, Any]] = Field(default_factory=list)
    policy: str = ""


def review_prompt(message: str, reply: str, actions: List[Dict[str, Any]], policy: str) -> List[Dict[str, str]]:
    from kalytera.prompts import _format_tool_calls

    user = (
        "Hold the reply ONLY if sending it could hurt the customer or the business:\n"
        "- it says an action happened (a refund, a cancellation, a change) that the actions below don't show "
        "succeeding;\n"
        "- it promises money, a refund, a discount, compensation or an exception that the business policy "
        "(if given) or the actions don't support;\n"
        "- it states a policy, price, fee, deadline, or legal or medical fact the customer may rely on, that "
        "nothing below supports and that looks invented;\n"
        "- it shows personal data that isn't this customer's;\n"
        "- it is abusive, harmful, or tells the customer to do something unsafe.\n"
        "Do NOT hold for tone, style, small slips that don't matter, or sensible general answers. If unsure, "
        "don't hold.\n\n"
        f"Customer's message:\n{message[:TEXT_CHARS] or '(not given)'}\n\n"
        f"Actions in this conversation:{_format_tool_calls(actions)}\n\n"
        f"Business policy:\n{policy[:TEXT_CHARS] or '(not given)'}\n\n"
        f"Reply to check:\n{reply[:TEXT_CHARS]}\n\n"
        'Respond with JSON only: {"hold": false, "reason": ""}. If you hold it, reason is one short sentence '
        "a manager would understand, saying what is wrong."
    )
    return [{"role": "user", "content": user}]


def parse_verdict(raw: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("hold"), bool):
        return None
    return {"hold": data["hold"], "reason": str(data.get("reason") or "")[:500] if data["hold"] else ""}


def _count_review(org_id: str) -> bool:
    """Count one review for today; False once the account's daily limit is reached."""
    key = f"{org_id}:{date.today().isoformat()}"
    with _count_lock:
        if len(_reviews_today) > 10000:
            _reviews_today.clear()
        if _reviews_today.get(key, 0) >= REVIEW_DAILY_LIMIT:
            return False
        _reviews_today[key] = _reviews_today.get(key, 0) + 1
        return True


def build_router(resolve_org: Callable[..., Any]) -> APIRouter:
    router = APIRouter(tags=["replies"])

    def _check_agent(agent_id: str, org: Any, db: Session) -> Optional[str]:
        """The account's id; 404 if another account owns this agent."""
        org_id = org.id if org is not None else None
        owner = db.query(AgentOrg.org_id).filter(AgentOrg.agent_id == agent_id).scalar()
        if owner is not None and org_id is not None and owner != org_id:
            raise HTTPException(status_code=404, detail="agent not found")
        return org_id

    def _hold(db: Session, org_id: Optional[str], agent_id: str, session_id: str, reply: str, reason: str,
              by: str) -> None:
        from api.connections_api import alert_held_reply

        db.add(HeldReply(org_id=org_id, agent_id=agent_id, session_id=session_id, reply=reply[:TEXT_CHARS],
                         reason=reason[:1000], checked_by=by))
        db.commit()
        alert_held_reply(db, org_id, agent_id, session_id, reason, by)

    @router.post("/replies/held", status_code=201)
    async def held(body: HeldIn, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        org_id = _check_agent(body.agent_id, org, db)
        by = body.checked_by if body.checked_by in ("code", "ai") else "code"
        _hold(db, org_id, body.agent_id, body.session_id, body.reply, body.reason, by)
        return {"held": True}

    @router.post("/replies/review")
    def review(body: ReviewIn, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        from kalytera.judge import _call_judge

        org_id = _check_agent(body.agent_id, org, db)
        if org_id and not _count_review(org_id):
            raise HTTPException(status_code=429, detail=f"AI review limit reached ({REVIEW_DAILY_LIMIT} a day)")
        verdict = parse_verdict(_call_judge(review_prompt(body.message, body.reply, body.actions, body.policy),
                                            system=REVIEW_SYSTEM))
        if verdict is None:
            raise HTTPException(status_code=503, detail="the reviewer didn't answer clearly; send the reply as is")
        if verdict["hold"]:
            reason = verdict["reason"] or "Kalytera's reviewer held this reply."
            _hold(db, org_id, body.agent_id, body.session_id, body.reply, reason, "ai")
        return verdict

    return router
