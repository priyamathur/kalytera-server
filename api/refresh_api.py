"""
Score an agent's new sessions and look for failure patterns now, instead of
waiting for the 30-second scoring loop and the hourly pattern analysis.

  POST /agents/{agent_id}/refresh   — start (or join) a refresh; returns its status
  GET  /agents/{agent_id}/refresh   — status: idle | scoring | analyzing | done | error

Used by `kalytera quickstart` so a new developer sees patterns and a drafted
rule within a couple of minutes. Scoring a session here and in the background
loop never happens twice: both go through score_session_once().
"""
import threading
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
        pending = list(dict.fromkeys(get_unevaluated_sessions(agent_id, MAX_REFRESH_SESSIONS, db)))
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
        job["state"] = "done"
    except Exception as exc:
        db.rollback()
        job.update(state="error", error=str(exc))
    finally:
        db.close()


def _start(job: Dict[str, Any], agent_id: str) -> None:
    threading.Thread(target=_run, args=(job, agent_id), daemon=True).start()


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

    @router.post("/agents/{agent_id}/refresh", status_code=202)
    async def start(agent_id: str, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        key = _check(agent_id, org, db)
        with _lock:
            job = _jobs.get(key)
            new = job is None or job["state"] in ("done", "error")
            if new:
                job = _jobs[key] = {"state": "scoring", "to_score": 0, "scored": 0, "judge_errors": 0}
        if new:
            _start(job, agent_id)
        return _status(job, agent_id, db)

    @router.get("/agents/{agent_id}/refresh")
    async def status(agent_id: str, org=Depends(resolve_org), db: Session = Depends(get_db)) -> Dict[str, Any]:
        key = _check(agent_id, org, db)
        return _status(_jobs.get(key), agent_id, db)

    return router
