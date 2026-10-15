"""
Score an agent's new sessions and look for failure patterns now, instead of
waiting for the 30-second scoring loop and the hourly pattern analysis.

  POST /agents/{agent_id}/refresh   — start (or join) a refresh; returns its status
  GET  /agents/{agent_id}/refresh   — status: idle | preparing | scoring | analyzing | done | error
  POST /agents/sample               — create the sample refund agent for this account and
                                      start its refresh (the dashboard's "Run the sample agent")

Used by `kalytera quickstart` so a new developer sees patterns and a drafted
rule within a couple of minutes. Scoring a session here and in the background
loop never happens twice: both go through score_session_once().
"""
import threading
import uuid
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import SessionLocal, get_db

MAX_REFRESH_SESSIONS = 100   # sessions scored per refresh
SCORING_THREADS = 5          # judge calls in parallel

_lock = threading.Lock()
_in_flight: set = set()
_jobs: Dict[str, Dict[str, Any]] = {}


def score_session_once(session_id: str) -> bool:
    """Score one ended session unless it is already scored or being scored. True if scored now."""
    from db.models import EvalResult
    from kalytera.judge import evaluate_session

    with _lock:
        if session_id in _in_flight:
            return False
        _in_flight.add(session_id)
    db = SessionLocal()
    try:
        if db.query(EvalResult.id).filter(EvalResult.session_id == session_id).first():
            return False
        return evaluate_session(session_id, db) is not None
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        with _lock:
            _in_flight.discard(session_id)


def _run(job: Dict[str, Any], agent_id: str) -> None:
    from db.queries import get_unevaluated_sessions
    from kalytera.analyzer import run_analysis

    db = SessionLocal()
    try:
        prepare = job.pop("prepare", None)  # e.g. write the sample's or a connection's conversations first
        if prepare is not None:
            prepare(db)
        pending = list(dict.fromkeys(get_unevaluated_sessions(agent_id, job.get("limit", MAX_REFRESH_SESSIONS), db)))
        job.update(state="scoring", to_score=len(pending), scored=0, judge_errors=0)

        def one(sid: str) -> None:
            try:
                score_session_once(sid)
            except Exception:
                with _lock:
                    job["judge_errors"] += 1
            with _lock:
                job["scored"] += 1

        with ThreadPoolExecutor(SCORING_THREADS) as pool:
            list(pool.map(one, pending))
        job["state"] = "analyzing"
        job["patterns"] = run_analysis(agent_id, db)
        _alert_now(agent_id, db)
        job["state"] = "done"
    except Exception as exc:
        db.rollback()
        job.update(state="error", error=str(exc))
    finally:
        db.close()


def _alert_now(agent_id: str, db: Session) -> None:
    """Problems found by this run reach Slack now, not at the next hourly analysis."""
    from api.connections_api import send_alerts
    from db.models import AgentOrg

    try:
        owner = db.query(AgentOrg.org_id).filter(AgentOrg.agent_id == agent_id).scalar()
        if owner:
            send_alerts(db, org_id=owner)
    except Exception:  # an alert problem must never fail the run
        db.rollback()


def start_job(key: str, agent_id: str, prepare: Optional[Callable[[Session], None]] = None,
              limit: int = MAX_REFRESH_SESSIONS) -> Dict[str, Any]:
    """Start (or join) the background job that prepares, scores and analyses an agent's sessions."""
    with _lock:
        job = _jobs.get(key)
        new = job is None or job["state"] in ("done", "error")
        if new:
            job = _jobs[key] = {"state": "preparing" if prepare else "scoring", "to_score": 0, "scored": 0,
                                "judge_errors": 0, "limit": limit}
            if prepare is not None:
                job["prepare"] = prepare
    if new:
        _start(job, agent_id)
    return job


def job_status(key: str, agent_id: str, db: Session) -> Dict[str, Any]:
    return _status(_jobs.get(key), agent_id, db)


def sample_agent_id(org_id: str) -> str:
    return f"sample-refund-bot-{org_id.replace('-', '')[:6]}"


def _start(job: Dict[str, Any], agent_id: str) -> None:
    threading.Thread(target=_run, args=(job, agent_id), daemon=True).start()


def _write_sample(agent_id: str, db: Session) -> None:
    """The sample agent's conversations, written once (one commit)."""
    from db.models import AgentLog
    from db.queries import insert_agent_logs
    from kalytera.quickstart import sample_sessions

    if db.query(AgentLog.id).filter(AgentLog.agent_id == agent_id).first():
        return
    now = datetime.now(timezone.utc).isoformat()
    insert_agent_logs([{**step, "id": str(uuid.uuid4()), "agent_id": agent_id, "timestamp": now,
                        "metadata": {"source": "sample"}}
                       for steps in sample_sessions(uuid.uuid4().hex[:6]) for step in steps], db)


def _status(job: Optional[Dict[str, Any]], agent_id: str, db: Session) -> Dict[str, Any]:
    from db.queries import get_session_failure_counts

    counts = get_session_failure_counts(agent_id, db)
    out = {"agent_id": agent_id, "state": "idle", "to_score": 0, "scored": 0, "judge_errors": 0,
           "patterns": None, "error": None}
    out.update({k: v for k, v in (job or {}).items() if k in out})
    out["sessions_scored"] = counts["total"]
    out["sessions_failed"] = counts["failed"]
    return out


def build_router(resolve_org: Callable[..., Any],
                 agent_ids_for_org: Callable[[str, Session], List[str]]) -> APIRouter:
    router = APIRouter(tags=["agents"])

    def _check(agent_id: str, org: Any, db: Session) -> str:
        if org is not None and agent_id not in agent_ids_for_org(org.id, db):
            raise HTTPException(status_code=404, detail="agent not found")
        return f"{getattr(org, 'id', '')}:{agent_id}"

    @router.post("/agents/sample", status_code=202)
    async def sample(org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        """Same sample as `kalytera quickstart`, created server-side. Returns at once: the
        conversations are written, scored and analysed in the background (poll GET
        /agents/{agent_id}/refresh). Runs once per account; not counted against usage."""
        from db.queries import upsert_agent_org

        org_id = getattr(org, "id", None)
        if org_id is None:
            raise HTTPException(status_code=400, detail="sign in with your account's API key")
        agent_id = sample_agent_id(org_id)
        if not upsert_agent_org(agent_id, org_id, db):
            raise HTTPException(status_code=409, detail="sample agent name is taken")
        job = start_job(f"{org_id}:{agent_id}", agent_id, prepare=lambda d: _write_sample(agent_id, d))
        return _status(job, agent_id, db)

    @router.post("/agents/{agent_id}/refresh", status_code=202)
    async def start(agent_id: str, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        job = start_job(_check(agent_id, org, db), agent_id)
        return _status(job, agent_id, db)

    @router.get("/agents/{agent_id}/refresh")
    async def status(agent_id: str, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        key = _check(agent_id, org, db)
        return _status(_jobs.get(key), agent_id, db)

    return router
