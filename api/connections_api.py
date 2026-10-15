"""
Connect once: Kalytera reads an agent's production conversations from where they
already live (Langfuse, LangSmith) and keeps reading new ones; and tells the
account in Slack when a problem appears or gets worse.

  POST   /connections                  connect Langfuse or LangSmith: first pull, then judged live
                                       (poll GET /agents/{agent_id}/refresh)
  GET    /connections                  this account's connections (never the keys)
  POST   /connections/{id}/sync        pull new conversations now
  DELETE /connections/{id}             remove it; its stored keys are deleted
  PUT    /alerts/slack                 set the Slack incoming webhook (sends a test message)
  GET    /alerts                       whether Slack alerts are on
  DELETE /alerts/slack                 turn them off

Background (api/main.py): sync_all() every 15 minutes, send_alerts() after each analysis.
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.database import get_db
from api.refresh_api import job_status, start_job
from db.models import AgentLog, AgentOrg, Connection, LossPattern, ProblemAlert
from kalytera import importers, vault

logger = logging.getLogger("kalytera.connections")

SOURCES = ("langfuse", "langsmith")
SYNC_OVERLAP = timedelta(minutes=30)   # re-read a little before the last pull; duplicates are skipped
WORSE_ALERT_EVERY = timedelta(days=1)  # "getting worse" at most once a day per problem
SLACK_PREFIX = "https://hooks.slack.com/"
DASHBOARD = "https://app.kalytera.dev"


class ConnectIn(BaseModel):
    kind: str                      # langfuse | langsmith
    agent_name: str                # how the agent shows up in Kalytera
    settings: Dict[str, str] = {}  # langfuse: base_url; langsmith: api_url, project
    secrets: Dict[str, str]        # langfuse: public_key, secret_key; langsmith: api_key


class SlackIn(BaseModel):
    webhook_url: str


def agent_id_for(org_id: str, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "agent"
    return f"{slug}-{org_id.replace('-', '')[:6]}"


def _fetch(kind: str, settings: Dict[str, str], secrets: Dict[str, str],
           since: Optional[datetime]) -> List[importers.Conversation]:
    if kind == "langfuse":
        return importers.fetch_langfuse(secrets.get("public_key", ""), secrets.get("secret_key", ""),
                                        settings.get("base_url") or importers.LANGFUSE_REGIONS[
                                            next(iter(importers.LANGFUSE_REGIONS))], since=since)
    return importers.fetch_langsmith(secrets.get("api_key", ""), settings.get("project", ""),
                                     settings.get("api_url") or importers.LANGSMITH_REGIONS[
                                         next(iter(importers.LANGSMITH_REGIONS))], since=since)


def write_new(conversations: List[importers.Conversation], agent_id: str, kind: str, org_id: str,
              db: Session) -> int:
    """Store conversations not seen before, as ended sessions (so they get judged). Returns how many."""
    from db.queries import increment_session_count, insert_agent_logs

    steps = {conv["id"]: importers.to_steps(conv, agent_id, kind) for conv in conversations}
    ids = [s[0]["session_id"] for s in steps.values() if s]
    seen = {sid for (sid,) in db.query(AgentLog.session_id).filter(
        AgentLog.agent_id == agent_id, AgentLog.session_id.in_(ids)).distinct()} if ids else set()
    fresh = [s for s in steps.values() if s and s[0]["session_id"] not in seen]
    if fresh:
        insert_agent_logs([step for s in fresh for step in s], db)
        period = datetime.now(timezone.utc).strftime("%Y-%m")
        for _ in fresh:
            increment_session_count(org_id, period, db)
    return len(fresh)


def sync_connection(conn: Connection, db: Session, first: bool = False) -> int:
    """Pull conversations since the last sync (the last 30 days on the first). Records errors on the row."""
    since = None if first or conn.last_synced_at is None else _utc(conn.last_synced_at) - SYNC_OVERLAP
    started = datetime.now(timezone.utc)
    try:
        convs = _fetch(conn.kind, json.loads(conn.settings or "{}"), vault.decrypt(conn.secret), since)
        n = write_new(convs, conn.agent_id, conn.kind, conn.org_id, db)
        conn.status, conn.last_error, conn.last_synced_at = "ok", None, started
        db.commit()
        return n
    except Exception as exc:
        db.rollback()
        conn.status, conn.last_error = "error", str(exc)[:500]
        db.commit()
        raise


def sync_all(db: Session) -> Dict[str, int]:
    """Background: pull new conversations for every connection. One failing doesn't stop the rest."""
    pulled: Dict[str, int] = {}
    for conn in db.query(Connection).filter(Connection.kind.in_(SOURCES)).all():
        try:
            pulled[conn.id] = sync_connection(conn, db)
        except Exception as exc:
            logger.warning("[sync] connection=%s agent=%s failed: %s", conn.id, conn.agent_id, exc)
    return pulled


def _release_if_empty(agent_id: str, org_id: str, db: Session) -> None:
    if db.query(AgentLog.id).filter(AgentLog.agent_id == agent_id).first() is None:
        db.query(AgentOrg).filter(AgentOrg.agent_id == agent_id, AgentOrg.org_id == org_id).delete()
        db.commit()


def _utc(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


# ── Alerts ───────────────────────────────────────────────────────────────────
def _problem_link(p: LossPattern) -> str:
    from urllib.parse import urlencode

    return f"{DASHBOARD}/?{urlencode({'agent': p.agent_id, 'problem': p.id})}"


def _describe(p: LossPattern) -> str:
    what = (p.root_cause or str(p.pattern_value).replace("_", " ")).rstrip(".")
    sessions = f"{p.failure_count} conversation{'s' if p.failure_count != 1 else ''}"
    pct = f" ({round(p.failure_rate * 100)}% of them)" if p.total_count else ""
    return f"*{what}* — {sessions}{pct}"


def slack_message(new: List[LossPattern], worse: List[LossPattern]) -> Dict[str, Any]:
    """One message per agent per analysis: new problems first, then ones getting worse."""
    blocks: List[Dict[str, Any]] = []
    agent = (new or worse)[0].agent_id
    title = (f"{len(new)} new problem{'s' if len(new) != 1 else ''}" if new else "A problem is getting worse")
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}* in `{agent}`"}})
    for p, label in [(p, "New") for p in new[:5]] + [(p, "Getting worse") for p in worse[:5]]:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"{label}: {_describe(p)}"},
                       "accessory": {"type": "button", "text": {"type": "plain_text", "text": "Open"},
                                     "url": _problem_link(p)}})
    text = f"{title} in {agent}: " + "; ".join(_describe(p).replace("*", "") for p in (new + worse)[:3])
    return {"text": text, "blocks": blocks}


def _post_slack(url: str, payload: Dict[str, Any]) -> None:
    r = requests.post(url, json=payload, timeout=10)
    if r.status_code >= 300:
        raise ValueError(f"Slack said {r.status_code}: {r.text[:200]}")


def send_alerts(db: Session, now: Optional[datetime] = None, org_id: Optional[str] = None) -> int:
    """After an analysis: tell each account with Slack about new or worsening problems. Returns messages sent."""
    now = now or datetime.now(timezone.utc)
    sent = 0
    slacks = db.query(Connection).filter(Connection.kind == "slack")
    if org_id is not None:
        slacks = slacks.filter(Connection.org_id == org_id)
    for slack in slacks.all():
        try:
            url = vault.decrypt(slack.secret)["webhook_url"]
        except Exception as exc:
            logger.warning("[alerts] org=%s can't read the Slack webhook: %s", slack.org_id, exc)
            continue
        agents = [a for (a,) in db.query(AgentOrg.agent_id).filter(AgentOrg.org_id == slack.org_id)]
        past = db.query(ProblemAlert).filter(ProblemAlert.org_id == slack.org_id).all()
        alerted_new = {a.pattern_id for a in past if a.reason == "new"}
        last_told: Dict[str, datetime] = {}
        for a in past:  # the latest message of any kind about each problem
            last_told[a.pattern_id] = max(last_told.get(a.pattern_id, _utc(a.sent_at)), _utc(a.sent_at))
        for agent in agents:
            patterns = db.query(LossPattern).filter(LossPattern.agent_id == agent).all()
            new = [p for p in patterns if p.id not in alerted_new]
            # "Getting worse" only a day after the last word on it: a new problem is usually still rising.
            worse = [p for p in patterns if p.id in alerted_new and p.is_worsening
                     and now - last_told[p.id] >= WORSE_ALERT_EVERY]
            if not new and not worse:
                continue
            try:
                _post_slack(url, slack_message(new, worse))
            except Exception as exc:
                slack.status, slack.last_error = "error", str(exc)[:500]
                db.commit()
                logger.warning("[alerts] org=%s Slack failed: %s", slack.org_id, exc)
                break
            db.add_all([ProblemAlert(org_id=slack.org_id, pattern_id=p.id, reason="new", sent_at=now) for p in new]
                       + [ProblemAlert(org_id=slack.org_id, pattern_id=p.id, reason="worse", sent_at=now)
                          for p in worse])
            slack.status, slack.last_error = "ok", None
            db.commit()
            sent += 1
    return sent


def _public(conn: Connection) -> Dict[str, Any]:
    return {"id": conn.id, "kind": conn.kind, "agent_id": conn.agent_id,
            "settings": json.loads(conn.settings or "{}"), "status": conn.status, "last_error": conn.last_error,
            "last_synced_at": conn.last_synced_at.isoformat() if conn.last_synced_at else None}


# ── Routes ───────────────────────────────────────────────────────────────────
def build_router(resolve_org: Callable[..., Any]) -> APIRouter:
    router = APIRouter(tags=["connections"])

    def _org(org: Any) -> str:
        if org is None or not getattr(org, "id", None):
            raise HTTPException(status_code=403, detail="sign in with your account's API key")
        return org.id

    def _can_store() -> None:
        try:
            vault.encrypt({})
        except vault.SecretsUnavailable as exc:
            logger.error("[connections] %s", exc)
            raise HTTPException(status_code=503, detail="Connections are unavailable right now: the server "
                                                        "can't store keys safely. Please try again later.")

    def _mine(conn_id: str, org_id: str, db: Session) -> Connection:
        conn = db.query(Connection).filter(Connection.id == conn_id, Connection.org_id == org_id).first()
        if conn is None:
            raise HTTPException(status_code=404, detail="connection not found")
        return conn

    @router.post("/connections", status_code=202)
    async def connect(body: ConnectIn, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        """Check the keys by pulling the last 30 days of conversations, save the connection, then judge them.
        Returns at once; poll GET /agents/{agent_id}/refresh. A bad key ends the job in 'error' and saves nothing."""
        from db.queries import upsert_agent_org

        org_id = _org(org)
        if body.kind not in SOURCES:
            raise HTTPException(status_code=422, detail=f"kind must be one of {list(SOURCES)}")
        _can_store()
        agent_id = agent_id_for(org_id, body.agent_name)
        if not upsert_agent_org(agent_id, org_id, db):
            raise HTTPException(status_code=409, detail="That agent name is taken; pick another.")
        settings, secrets = dict(body.settings), {k: v.strip() for k, v in body.secrets.items()}

        def prepare(d: Session) -> None:
            try:
                convs = _fetch(body.kind, settings, secrets, since=None)  # raises with a clear message on bad keys
            except Exception:
                _release_if_empty(agent_id, org_id, d)  # a failed connect leaves no empty agent behind
                raise
            conn = Connection(org_id=org_id, kind=body.kind, agent_id=agent_id, settings=json.dumps(settings),
                              secret=vault.encrypt(secrets), last_synced_at=datetime.now(timezone.utc))
            d.add(conn)
            profile = d.query(AgentOrg).filter(AgentOrg.agent_id == agent_id).first()
            if profile is not None and not profile.system:
                profile.system = body.kind  # where its conversations come from
            d.commit()
            write_new(convs, agent_id, body.kind, org_id, d)

        job = start_job(f"{org_id}:{agent_id}", agent_id, prepare=prepare, limit=importers.MAX_CONVERSATIONS)
        return {**job_status(f"{org_id}:{agent_id}", agent_id, db), "state": job["state"]}

    @router.get("/connections")
    async def list_connections(org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        rows = db.query(Connection).filter(Connection.org_id == _org(org), Connection.kind.in_(SOURCES))
        return {"connections": [_public(c) for c in rows.order_by(Connection.created_at)]}

    @router.post("/connections/{conn_id}/sync", status_code=202)
    async def sync_now(conn_id: str, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        org_id = _org(org)
        conn = _mine(conn_id, org_id, db)
        cid = conn.id

        def prepare(d: Session) -> None:
            sync_connection(d.query(Connection).filter(Connection.id == cid).one(), d)

        job = start_job(f"{org_id}:{conn.agent_id}", conn.agent_id, prepare=prepare, limit=importers.MAX_CONVERSATIONS)
        return {**job_status(f"{org_id}:{conn.agent_id}", conn.agent_id, db), "state": job["state"]}

    @router.delete("/connections/{conn_id}")
    async def remove(conn_id: str, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        conn = _mine(conn_id, _org(org), db)
        db.delete(conn)  # the encrypted keys go with the row; the agent's conversations stay until deleted
        db.commit()
        return {"id": conn_id, "status": "removed"}

    @router.put("/alerts/slack")
    async def set_slack(body: SlackIn, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        org_id = _org(org)
        url = body.webhook_url.strip()
        if not url.startswith(SLACK_PREFIX):
            raise HTTPException(status_code=422, detail="Use a Slack incoming webhook URL (https://hooks.slack.com/…).")
        _can_store()
        secret = vault.encrypt({"webhook_url": url})
        try:
            _post_slack(url, {"text": "Kalytera is connected. New problems in your agents will show up here."})
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Couldn't post to that webhook: {exc}")
        row = db.query(Connection).filter(Connection.org_id == org_id, Connection.kind == "slack").first()
        if row is None:
            row = Connection(org_id=org_id, kind="slack", settings="{}", secret=secret)
            db.add(row)
            # Existing problems were already visible in the dashboard: only news from now on.
            agents = [a for (a,) in db.query(AgentOrg.agent_id).filter(AgentOrg.org_id == org_id)]
            for p in db.query(LossPattern).filter(LossPattern.agent_id.in_(agents)).all() if agents else []:
                db.add(ProblemAlert(org_id=org_id, pattern_id=p.id, reason="new"))
        else:
            row.secret, row.status, row.last_error = secret, "ok", None
        db.commit()
        return {"slack": True}

    @router.get("/alerts")
    async def get_alerts(org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        row = db.query(Connection).filter(Connection.org_id == _org(org), Connection.kind == "slack").first()
        return {"slack": row is not None, "status": row.status if row else None,
                "last_error": row.last_error if row else None}

    @router.delete("/alerts/slack")
    async def remove_slack(org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        db.query(Connection).filter(Connection.org_id == _org(org), Connection.kind == "slack").delete()
        db.commit()
        return {"slack": False}

    return router
