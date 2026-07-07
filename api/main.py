"""
Kalytera API — core endpoints + billing.
  POST /trace                        — receive AgentLog from tracer
  GET  /agents/{agent_id}/patterns   — return LossPattern rows
  /billing/*                         — usage, checkout, webhook
  /admin/tenants                     — tenant management
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.database import SessionLocal, get_db, initialize_database
from db.queries import (
    get_patterns_for_agent,
    get_unevaluated_logs,
    insert_agent_log,
    get_apikey_by_hash,
    get_org_by_id,
    get_current_usage,
    increment_session_count,
)
from api.billing import router as billing_router, TIERS, hash_key

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
# Auth + rate limiting
# ---------------------------------------------------------------------------

def _require_auth(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Optional[Any]:
    """
    Returns the Organization for customer keys (kly_live_*).
    Returns None for the master admin key or in dev mode (no rate limiting).
    Raises 429 when the org has exhausted its monthly session limit.
    """
    admin_key = os.getenv("KALYTERA_API_KEY", "")
    if not admin_key:
        return None  # dev mode — no key configured

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization: Bearer <key> header required",
        )
    token = authorization[len("Bearer "):]

    # Master admin key — bypass rate limiting
    if token == admin_key:
        return None

    # Customer key — resolve to org via ApiKey table
    api_key_row = get_apikey_by_hash(hash_key(token), db)
    if not api_key_row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    org = get_org_by_id(api_key_row.org_id, db)
    if not org:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Organization not found")

    # Check monthly rate limit (shared across all keys in this org)
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    usage = get_current_usage(org.id, period, db)
    sessions_used = usage.session_count if usage else 0
    tier_cfg = TIERS.get(org.tier, TIERS["free"])
    limit = tier_cfg["sessions"]

    if limit and sessions_used >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "monthly_limit_reached",
                "org": org.name,
                "tier": org.tier,
                "sessions_used": sessions_used,
                "sessions_limit": limit,
                "message": f"Your organization has used all {limit:,} sessions for {period} on the {org.tier} plan.",
                "upgrade_url": "/billing/checkout",
            },
        )
    return org


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def _eval_batch() -> None:
    """Sync: evaluate up to 20 unevaluated logs per agent, across all agents."""
    from kalytera.judge import evaluate_log
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
    from kalytera.analyzer import run_all

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


def _run_seed() -> None:
    """Run seed_data only if SEED_ON_STARTUP=true and DB is empty."""
    from db.models import AgentLog
    db = SessionLocal()
    try:
        count = db.query(AgentLog).count()
        if count > 0:
            logger.info("[seed] DB already has %d rows — skipping", count)
            return
        logger.info("[seed] DB is empty — running seed_data")
        import seed_data
        seed_data.main()
        logger.info("[seed] done")
    except Exception as exc:
        logger.error("[seed] failed: %s", exc)
    finally:
        db.close()


async def _startup_bg() -> None:
    """DB init + optional seed — runs as a background task after server is up."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, initialize_database)
    if os.getenv("SEED_ON_STARTUP", "").lower() == "true":
        await loop.run_in_executor(None, _run_seed)


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    # yield immediately so uvicorn binds the port and Render's health check passes.
    # All heavy work runs as background tasks after the server is accepting requests.
    tasks = [
        asyncio.create_task(_startup_bg()),
        asyncio.create_task(_eval_loop()),
        asyncio.create_task(_analysis_loop()),
    ]
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Kalytera", version="1.0.0", docs_url="/docs", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(billing_router)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/welcome", response_class=HTMLResponse)
async def welcome() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>You're all set — Kalytera</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Mono:wght@300;400&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0d10;color:#e8ecf0;font-family:'DM Mono',monospace;font-weight:300;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
.card{max-width:540px;width:100%;text-align:center}
.check{width:64px;height:64px;border-radius:50%;background:rgba(168,224,96,0.1);border:2px solid rgba(168,224,96,0.3);display:flex;align-items:center;justify-content:center;margin:0 auto 28px;font-size:26px}
h1{font-family:'Syne',sans-serif;font-weight:800;font-size:28px;letter-spacing:-.5px;margin-bottom:10px}
.sub{font-size:14px;color:rgba(232,236,240,0.45);line-height:1.7;margin-bottom:40px;max-width:400px;margin-left:auto;margin-right:auto}
.steps{text-align:left;border:1px solid rgba(255,255,255,0.08);border-radius:12px;overflow:hidden;margin-bottom:32px}
.step{display:grid;grid-template-columns:40px 1fr;gap:12px;padding:18px 20px;border-bottom:1px solid rgba(255,255,255,0.06);align-items:start}
.step:last-child{border-bottom:none}
.step-n{font-family:'Syne',sans-serif;font-weight:800;font-size:18px;color:rgba(0,200,232,0.25);line-height:1.2}
.step-title{font-family:'Syne',sans-serif;font-weight:700;font-size:13px;margin-bottom:5px}
.step-body{font-size:11.5px;color:rgba(232,236,240,0.45);line-height:1.65}
.step-body code{background:rgba(0,200,232,0.08);color:#00c8e8;padding:1px 6px;border-radius:3px;font-size:11px}
.btn{display:inline-block;font-family:'Syne',sans-serif;font-weight:700;font-size:12px;padding:13px 28px;background:#00c8e8;color:#0a0d10;border-radius:7px;text-decoration:none;margin-right:10px}
.btn-s{display:inline-block;font-family:'Syne',sans-serif;font-weight:700;font-size:12px;padding:12px 24px;border:1px solid rgba(255,255,255,0.08);color:rgba(232,236,240,0.5);border-radius:7px;text-decoration:none}
.logo{font-family:'Syne',sans-serif;font-weight:800;font-size:15px;margin-bottom:40px;display:flex;align-items:center;justify-content:center;gap:8px}
.dot{width:6px;height:6px;border-radius:50%;background:#00c8e8}
</style>
</head>
<body>
<div class="card">
  <div class="logo"><div class="dot"></div>Kalytera</div>
  <div class="check">✓</div>
  <h1>You're all set.</h1>
  <p class="sub">Your plan is active. Your API key was shown at signup — check your notes. Here's how to get your first trace into Kalytera.</p>
  <div class="steps">
    <div class="step">
      <div class="step-n">1</div>
      <div>
        <div class="step-title">Install the SDK</div>
        <div class="step-body"><code>pip install kalytera</code></div>
      </div>
    </div>
    <div class="step">
      <div class="step-n">2</div>
      <div>
        <div class="step-title">Configure once at startup</div>
        <div class="step-body"><code>kalytera.configure(api_key="kly_live_...", api_endpoint="https://agentiq-api-z9it.onrender.com")</code></div>
      </div>
    </div>
    <div class="step">
      <div class="step-n">3</div>
      <div>
        <div class="step-title">Add to your agent</div>
        <div class="step-body"><code>@kalytera.watch</code> on any function — or call <code>kalytera.trace()</code> manually at each step. That's it.</div>
      </div>
    </div>
    <div class="step">
      <div class="step-n">4</div>
      <div>
        <div class="step-title">Watch failures surface in real time</div>
        <div class="step-body">Loss patterns appear automatically after 5+ failures of the same type. Root cause in plain English. No config required.</div>
      </div>
    </div>
  </div>
  <a href="https://agentiq-api-z9it.onrender.com/docs" class="btn">API docs →</a>
  <a href="mailto:priya@kalytera.ai" class="btn-s">Contact support</a>
</div>
</body>
</html>"""


@app.post("/trace", response_model=TraceResponse, status_code=201)
async def post_trace(
    payload: TracePayload,
    org=Depends(_require_auth),
    db: Session = Depends(get_db),
) -> TraceResponse:
    """
    Receive one agent step from kalytera.trace().
    Writes an AgentLog row, increments monthly usage for customer keys.
    """
    insert_agent_log(payload.model_dump(), db)
    if org is not None:
        period = datetime.now(timezone.utc).strftime("%Y-%m")
        increment_session_count(org.id, period, db)
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
