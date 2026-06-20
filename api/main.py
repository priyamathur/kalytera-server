"""
AgentIQ API — two endpoints only.
  POST /trace                        — receive AgentLog from tracer
  GET  /agents/{agent_id}/patterns   — return LossPattern rows
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.database import SessionLocal, get_db, initialize_database
from db.queries import get_patterns_for_agent, get_unevaluated_logs, insert_agent_log

logger = logging.getLogger(__name__)

_EVAL_INTERVAL_S = 30       # evaluate unevaluated logs every 30 seconds
_ANALYSIS_INTERVAL_S = 3600 # run pattern analysis every hour

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class TracePayload(BaseModel):
    id: str
    agent_id: str
    session_id: str
    step_number: int
    step_name: str
    input: str
    output: str
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    latency_ms: int = 0
    session_ended: bool = False
    timestamp: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TraceResponse(BaseModel):
    id: str
    status: str


class PatternOut(BaseModel):
    id: str
    agent_id: str
    pattern_type: str
    pattern_value: str
    failure_count: int
    total_count: int
    failure_rate: float
    pct_of_all_failures: float
    root_cause: Optional[str]
    is_worsening: bool
    first_seen: datetime
    last_seen: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _require_auth(authorization: Optional[str] = Header(default=None)) -> None:
    expected = os.getenv("AGENTIQ_API_KEY")
    if not expected:
        return  # dev mode: no key configured, allow all
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization: Bearer <key> header required",
        )
    token = authorization[len("Bearer "):]
    if token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def _eval_batch() -> None:
    """Sync: evaluate up to 20 unevaluated logs per agent, across all agents."""
    from agentiq.judge import evaluate_log
    from db.models import AgentLog

    db = SessionLocal()
    try:
        agent_ids = [row[0] for row in db.query(AgentLog.agent_id).distinct().all()]
        for agent_id in agent_ids:
            logs = get_unevaluated_logs(agent_id, batch_size=20, db=db)
            for log in logs:
                try:
                    evaluate_log(log.id, db)
                except Exception as exc:
                    logger.error("[eval] log=%s error: %s", log.id, exc)
    except Exception as exc:
        logger.error("[eval_batch] error: %s", exc)
    finally:
        db.close()


def _analysis_batch() -> None:
    """Sync: run pattern detection across all agents."""
    from agentiq.analyzer import run_all

    db = SessionLocal()
    try:
        run_all(db)
    except Exception as exc:
        logger.error("[analysis_batch] error: %s", exc)
    finally:
        db.close()


async def _eval_loop() -> None:
    loop = asyncio.get_event_loop()
    while True:
        try:
            await asyncio.sleep(_EVAL_INTERVAL_S)
            await loop.run_in_executor(None, _eval_batch)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("[eval_loop] error: %s", exc)


async def _analysis_loop() -> None:
    loop = asyncio.get_event_loop()
    while True:
        try:
            await asyncio.sleep(_ANALYSIS_INTERVAL_S)
            await loop.run_in_executor(None, _analysis_batch)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("[analysis_loop] error: %s", exc)


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    initialize_database()
    tasks = [
        asyncio.create_task(_eval_loop()),
        asyncio.create_task(_analysis_loop()),
    ]
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="AgentIQ", version="1.0.0", docs_url="/docs", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/trace", response_model=TraceResponse, status_code=201)
async def post_trace(
    payload: TracePayload,
    _: None = Depends(_require_auth),
    db: Session = Depends(get_db),
) -> TraceResponse:
    """
    Receive one agent step from agentiq.trace().
    Writes an AgentLog row. Returns immediately.
    """
    insert_agent_log(payload.model_dump(), db)
    return TraceResponse(id=payload.id, status="accepted")


@app.get(
    "/agents/{agent_id}/patterns",
    response_model=List[PatternOut],
)
async def get_patterns(
    agent_id: str,
    _: None = Depends(_require_auth),
    db: Session = Depends(get_db),
) -> List[PatternOut]:
    """
    Return LossPattern rows for one agent, sorted by pct_of_all_failures desc.
    Multi-tenant: results are scoped to the requested agent_id.
    """
    return get_patterns_for_agent(agent_id, db)
