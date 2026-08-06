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
    get_agent_ids_for_org,
    get_patterns_for_agent,
    get_unevaluated_logs,
    get_unevaluated_sessions,
    insert_agent_log,
    get_apikey_by_hash,
    get_org_by_id,
    get_current_usage,
    increment_session_count,
    upsert_agent_org,
)
from api.billing import router as billing_router, TIERS, hash_key
from api.proxy_router import router as proxy_router

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
    Returns None for the master admin key or unauthenticated dev-mode requests.
    Raises 429 when the org has exhausted its monthly session limit.

    Behaviour when KALYTERA_API_KEY is not set (dev/misconfigured):
      - No auth header → return None (allow unauthenticated)
      - Valid customer key → still resolve to org so endpoints work correctly
      - Unrecognised key → return None (allow through)
    """
    admin_key = os.getenv("KALYTERA_API_KEY", "")

    if not authorization or not authorization.startswith("Bearer "):
        if not admin_key:
            return None  # dev mode — no master key configured, allow unauthenticated
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization: Bearer <key> header required",
        )

    token = authorization[len("Bearer "):]

    # Master admin key — bypass rate limiting
    if admin_key and token == admin_key:
        return None

    # Customer key — always resolve via ApiKey table regardless of admin_key
    api_key_row = get_apikey_by_hash(hash_key(token), db)
    if not api_key_row:
        if not admin_key:
            return None  # dev mode — unknown key, allow through
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
    """Sync: evaluate unevaluated logs/sessions per agent across all agents."""
    from db.models import AgentLog

    db = SessionLocal()
    try:
        agent_ids = [row[0] for row in db.query(AgentLog.agent_id).distinct().all()]
        if os.getenv("KALYTERA_EVAL_MODE", "session") == "session":
            _eval_sessions(agent_ids, db)
        else:
            _eval_steps(agent_ids, db)
    except Exception as exc:
        logger.error("[eval_batch] error: %s", exc)
        db.rollback()
    finally:
        db.close()


def _eval_sessions(agent_ids: List[str], db: Any) -> None:
    """Session-level eval: one Haiku call per complete session (free tier)."""
    from kalytera.judge import evaluate_session

    for agent_id in agent_ids:
        try:
            session_ids = get_unevaluated_sessions(agent_id, batch_size=20, db=db)
        except Exception as exc:
            logger.error("[eval_sessions] get_sessions agent=%s error: %s", agent_id, exc)
            db.rollback()
            continue
        for session_id in session_ids:
            try:
                evaluate_session(session_id, db)
            except Exception as exc:
                logger.error("[eval] session=%s error: %s", session_id, exc)
                db.rollback()


def _eval_steps(agent_ids: List[str], db: Any) -> None:
    """Step-level eval: one Haiku call per step (paid tier, granular scores)."""
    from kalytera.judge import evaluate_log

    for agent_id in agent_ids:
        try:
            logs = get_unevaluated_logs(agent_id, batch_size=20, db=db)
        except Exception as exc:
            logger.error("[eval_steps] get_logs agent=%s error: %s", agent_id, exc)
            db.rollback()
            continue
        for log in logs:
            try:
                evaluate_log(log.id, db)
            except Exception as exc:
                logger.error("[eval] log=%s error: %s", log.id, exc)
                db.rollback()


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
    await asyncio.sleep(90)  # let eval loop score a few batches first
    while True:
        try:
            await loop.run_in_executor(None, _analysis_batch)
            await asyncio.sleep(_ANALYSIS_INTERVAL_S)
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
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    allow_headers=["Authorization", "Content-Type", "X-Kalytera-Agent-Id", "X-Kalytera-Session-Id",
                   "anthropic-version", "x-api-key"],
)

app.include_router(billing_router)
app.include_router(proxy_router)


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
.card{max-width:480px;width:100%;text-align:center}
.logo{font-family:'Syne',sans-serif;font-weight:800;font-size:15px;margin-bottom:48px;display:flex;align-items:center;justify-content:center;gap:8px;color:#e8ecf0}
.dot{width:6px;height:6px;border-radius:50%;background:#00c8e8}
.check{font-size:72px;line-height:1;margin:0 auto 24px;color:#a8e060}
h1{font-family:'Syne',sans-serif;font-weight:800;font-size:26px;letter-spacing:-.5px;margin-bottom:10px}
.sub{font-size:13px;color:rgba(232,236,240,0.42);line-height:1.75;margin-bottom:36px}
.cb{background:#0d1117;border:1px solid rgba(255,255,255,0.08);border-radius:10px;text-align:left;overflow:hidden;margin-bottom:28px}
.cb-lbl{background:#161b22;padding:8px 16px;font-size:9px;letter-spacing:2px;text-transform:uppercase;color:#4e5a68;border-bottom:1px solid rgba(255,255,255,0.06)}
.cb pre{padding:16px 20px;font-size:12px;line-height:2;color:#e8ecf0;overflow-x:auto}
.kw{color:#00c8e8}.fn{color:#a8e060}.str{color:#e8c864}.cm{color:#4e5a68}
.btn{display:inline-block;font-family:'Syne',sans-serif;font-weight:700;font-size:12px;padding:13px 28px;background:#00c8e8;color:#0a0d10;border-radius:7px;text-decoration:none}
.help{margin-top:24px;font-size:11px;color:rgba(232,236,240,0.28)}
.help a{color:rgba(232,236,240,0.4);text-decoration:none;border-bottom:1px solid rgba(232,236,240,0.15)}
.help a:hover{color:#e8ecf0}
</style>
</head>
<body>
<div class="card">
  <div class="logo"><div class="dot"></div>Kalytera</div>
  <div class="check">✓</div>

  <h1>You're all set.</h1>
  <p class="sub">Your plan is active. Paste your API key from the previous screen and you're ready.</p>
  <div class="cb">
    <div class="cb-lbl">Get started in 30 seconds</div>
    <pre><span class="cm">pip install kalytera</span>

<span class="kw">import</span> kalytera
kalytera.<span class="fn">configure</span>(
  api_key=<span class="str">"kly_live_..."</span>,
  agent_id=<span class="str">"my-agent"</span>,
)

<span class="kw">@</span>kalytera.<span class="fn">watch</span>
<span class="kw">def</span> <span class="fn">your_agent</span>(user_input):
    ...  <span class="cm"># nothing else changes</span></pre>
  </div>
  <a href="https://kalytera.dev" class="btn">Back to kalytera.dev →</a>
  <div class="help">
    Questions? <a href="mailto:priya@kalytera.ai?subject=Kalytera%20support&body=Hi%20Priya%2C%0A%0AI%20just%20signed%20up%20for%20Kalytera%20and%20need%20help%20with%3A%0A%0A">Email priya@kalytera.ai</a>
  </div>
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
        upsert_agent_org(payload.agent_id, org.id, db)
    return TraceResponse(id=payload.id, status="accepted")


@app.get("/agents", response_model=List[str])
async def list_agents(
    org=Depends(_require_auth),
    db: Session = Depends(get_db),
) -> List[str]:
    """Return agent_ids owned by this org plus shared demo agents."""
    if org is None:
        from db.queries import DEMO_AGENT_IDS
        return DEMO_AGENT_IDS
    return get_agent_ids_for_org(org.id, db)


@app.get("/debug/auth-check")
async def debug_auth_check(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Temporary diagnostic endpoint — remove after debugging."""
    if not authorization or not authorization.startswith("Bearer "):
        return {"error": "no bearer token"}
    token = authorization[len("Bearer "):]
    key_hash = hash_key(token)
    try:
        from db.models import AgentOrg
        row = get_apikey_by_hash(key_hash, db)
        admin_key = os.getenv("KALYTERA_API_KEY", "")
        org_id = row.org_id if row else None
        agent_orgs: List[str] = []
        if org_id:
            agent_orgs = [
                r.agent_id
                for r in db.query(AgentOrg).filter(AgentOrg.org_id == org_id).all()
            ]
        return {
            "token_prefix": token[:20],
            "key_hash_prefix": key_hash[:16],
            "admin_key_set": bool(admin_key),
            "row_found": row is not None,
            "is_active": row.is_active if row else None,
            "org_id": org_id,
            "agent_orgs_in_db": agent_orgs,
        }
    except Exception as exc:
        return {"error": str(exc), "token_prefix": token[:20]}


@app.post("/debug/register-agent")
async def debug_register_agent(
    agent_id: str,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Temporary: directly call upsert_agent_org and report what happens."""
    if not authorization or not authorization.startswith("Bearer "):
        return {"error": "no bearer token"}
    token = authorization[len("Bearer "):]
    row = get_apikey_by_hash(hash_key(token), db)
    if not row:
        return {"error": "key not found in api_keys table"}
    org = get_org_by_id(row.org_id, db)
    if not org:
        return {"error": "org not found"}
    try:
        from db.models import AgentOrg
        upsert_agent_org(agent_id, org.id, db)
        count_after = db.query(AgentOrg).filter(AgentOrg.org_id == org.id).count()
        all_rows = [r.agent_id for r in db.query(AgentOrg).all()]
        db_url = os.getenv("DATABASE_URL", "NOT SET")[:40]
        return {
            "success": True,
            "agent_id": agent_id,
            "org_id": org.id,
            "count_after_upsert": count_after,
            "all_agent_orgs": all_rows,
            "db_url_prefix": db_url,
        }
    except Exception as exc:
        return {"error": str(exc), "agent_id": agent_id, "org_id": org.id}


@app.get(
    "/agents/{agent_id}/patterns",
    response_model=List[PatternOut],
)
async def get_patterns(
    agent_id: str,
    org=Depends(_require_auth),
    db: Session = Depends(get_db),
) -> List[PatternOut]:
    """
    Return LossPattern rows for one agent, sorted by pct_of_all_failures desc.
    Multi-tenant: agent_id must belong to the requesting org or be a demo agent.
    """
    if org is not None:
        allowed = get_agent_ids_for_org(org.id, db)
        if agent_id not in allowed:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Agent not found in your organization")
    return get_patterns_for_agent(agent_id, db)
