"""
Kalytera SDK Client - Fire-and-forget tracing that never blocks agents
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass
import aiohttp
import threading
from queue import Queue
import os

# Configure local logging for SDK debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kalytera.sdk")

@dataclass
class TraceEvent:
    """Single agent interaction to be traced"""
    session_id: str
    user_input: str
    agent_response: str
    response_time_ms: int
    timestamp: Optional[datetime] = None
    workflow_step: Optional[int] = None
    tool_calls: Optional[List[str]] = None
    tokens_used: Optional[int] = None
    error_occurred: Optional[bool] = None
    error_message: Optional[str] = None
    session_ended: Optional[bool] = None
    config_snapshot: Optional["KalyteraConfig"] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.workflow_step is None:
            self.workflow_step = 1

class KalyteraConfig:
    """SDK Configuration"""
    def __init__(
        self,
        api_endpoint: str = "http://localhost:8000",
        api_key: Optional[str] = None,
        timeout_seconds: float = 2.0,
        max_retries: int = 0,  # Never retry - fire and forget
        enable_local_logging: bool = True,
        local_log_path: str = "kalytera_traces.log"
    ):
        self.api_endpoint = api_endpoint.rstrip("/")
        self.api_key = api_key or os.getenv("KALYTERA_API_KEY")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.enable_local_logging = enable_local_logging
        self.local_log_path = local_log_path

class TraceClient:
    """Client for sending traces with configurable settings"""
    def __init__(
        self,
        api_endpoint: str = "http://localhost:8000",
        api_key: Optional[str] = None,
        timeout_seconds: float = 2.0,
        enable_local_logging: bool = True,
        log_dir: Optional[str] = None
    ):
        """Initialize TraceClient with custom configuration"""
        self.config = KalyteraConfig(
            api_endpoint=api_endpoint,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            enable_local_logging=enable_local_logging,
            local_log_path=os.path.join(log_dir or ".", "kalytera_traces.log")
        )
        
    def trace(
        self,
        session_id: Optional[str] = None,
        user_input: Optional[str] = None,
        agent_response: Optional[str] = None,
        response_time_ms: Optional[int] = None,
        workflow_step: Optional[int] = None,
        tool_calls: Optional[List[str]] = None,
        tokens_used: Optional[int] = None,
        error_occurred: Optional[bool] = None,
        error_message: Optional[str] = None,
        session_ended: Optional[bool] = None
    ) -> None:
        """Instance method that traces with this client's config (no global mutation)."""
        trace(
            session_id=session_id,
            user_input=user_input,
            agent_response=agent_response,
            response_time_ms=response_time_ms,
            workflow_step=workflow_step,
            tool_calls=tool_calls,
            tokens_used=tokens_used,
            error_occurred=error_occurred,
            error_message=error_message,
            session_ended=session_ended,
            _config_override=self.config,
        )

# Global SDK configuration
_config = KalyteraConfig()

# Background thread and queue for async processing
_trace_queue: Queue = Queue(maxsize=1000)  # Drop events if queue full
_background_thread: Optional[threading.Thread] = None
_shutdown_event = threading.Event()

def configure(
    api_endpoint: str = "http://localhost:8000",
    api_key: Optional[str] = None,
    timeout_seconds: float = 2.0,
    enable_local_logging: bool = True,
    local_log_path: str = "kalytera_traces.log"
) -> None:
    """
    Configure Kalytera SDK settings
    
    Args:
        api_endpoint: Kalytera API endpoint URL
        api_key: Optional API key for authentication
        timeout_seconds: HTTP request timeout (default: 2.0s)
        enable_local_logging: Whether to log traces locally
        local_log_path: Path for local trace logs
    """
    global _config
    _config = KalyteraConfig(
        api_endpoint=api_endpoint,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        enable_local_logging=enable_local_logging,
        local_log_path=local_log_path
    )
    logger.info(f"Kalytera SDK configured with endpoint: {api_endpoint}")

def _log_trace_locally(trace_event: TraceEvent) -> None:
    """Log trace event to local file for debugging/backup"""
    cfg = trace_event.config_snapshot or _config
    if not cfg.enable_local_logging:
        return

    try:
        log_data = {
            "timestamp": trace_event.timestamp.isoformat(),
            "session_id": trace_event.session_id,
            "user_input": trace_event.user_input[:100],  # Truncate for privacy
            "response_time_ms": trace_event.response_time_ms,
            "workflow_step": trace_event.workflow_step,
            "error_occurred": trace_event.error_occurred
        }

        with open(cfg.local_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_data) + "\n")
            
    except Exception as e:
        # Even local logging failures should not affect the agent
        logger.debug(f"Failed to log locally: {e}")

async def _send_trace_async(trace_event: TraceEvent) -> bool:
    """
    Send trace event to Kalytera API asynchronously
    Returns True if successful, False otherwise
    """
    try:
        # Convert to API payload format
        payload = {
            "session_id": trace_event.session_id,
            "timestamp": trace_event.timestamp.isoformat(),
            "user_input": trace_event.user_input,
            "agent_response": trace_event.agent_response,
            "workflow_step": trace_event.workflow_step,
            "tool_calls": json.dumps(trace_event.tool_calls) if trace_event.tool_calls else None,
            "response_time_ms": trace_event.response_time_ms,
            "tokens_used": trace_event.tokens_used,
            "error_occurred": trace_event.error_occurred or False,
            "error_message": trace_event.error_message,
            "session_ended": trace_event.session_ended or False
        }
        
        headers = {"Content-Type": "application/json"}
        if _config.api_key:
            headers["Authorization"] = f"Bearer {_config.api_key}"
        
        timeout = aiohttp.ClientTimeout(total=_config.timeout_seconds)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{_config.api_endpoint}/api/trace",
                json=payload,
                headers=headers
            ) as response:
                if response.status == 200:
                    logger.debug(f"Trace sent successfully for session {trace_event.session_id}")
                    return True
                else:
                    logger.debug(f"Trace failed with status {response.status}")
                    return False
                    
    except Exception as e:
        logger.debug(f"Failed to send trace: {e}")
        return False

def _write_trace_to_db(trace_event: TraceEvent) -> None:
    """Write trace event directly to AgentLog table. Never raises."""
    try:
        from api.database import SessionLocal
        from db.models import AgentLog
        db = SessionLocal()
        try:
            log = AgentLog(
                id=str(uuid.uuid4()),
                session_id=trace_event.session_id,
                timestamp=trace_event.timestamp,
                user_input=trace_event.user_input,
                agent_response=trace_event.agent_response,
                workflow_step=trace_event.workflow_step or 1,
                tool_calls=json.dumps(trace_event.tool_calls) if trace_event.tool_calls else None,
                response_time_ms=trace_event.response_time_ms,
                tokens_used=trace_event.tokens_used,
                error_occurred=trace_event.error_occurred or False,
                error_message=trace_event.error_message,
                session_ended=trace_event.session_ended or False,
            )
            db.add(log)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.debug(f"DB write failed for session {trace_event.session_id}: {e}")
        finally:
            db.close()
    except Exception as e:
        logger.debug(f"Could not import DB modules: {e}")


def _http_send_worker(trace_event: TraceEvent) -> None:
    """Daemon thread: fire-and-forget HTTP send. Never blocks the main worker."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_send_trace_async(trace_event))
        loop.close()
    except Exception as e:
        logger.debug(f"HTTP send failed for session {trace_event.session_id}: {e}")


def _background_worker():
    """Background thread worker that processes the trace queue"""
    logger.info("Kalytera background worker started")
    # Pre-warm DB import so first write is fast
    try:
        from api.database import SessionLocal as _  # noqa: F401
    except Exception:
        pass

    while not _shutdown_event.is_set():
        try:
            try:
                trace_event = _trace_queue.get(timeout=1.0)
            except Exception:
                continue  # Timeout - check shutdown event

            # Log locally (always succeeds, fast)
            _log_trace_locally(trace_event)

            # Write to DB synchronously (fast after pre-warm)
            _write_trace_to_db(trace_event)

            # HTTP send in its own daemon thread — doesn't block dequeue loop
            t = threading.Thread(target=_http_send_worker, args=(trace_event,), daemon=True)
            t.start()

            _trace_queue.task_done()

        except Exception as e:
            logger.error(f"Critical error in background worker: {e}")

    logger.info("Kalytera background worker stopped")

def _ensure_background_worker():
    """Ensure background worker thread is running"""
    global _background_thread
    
    if _background_thread is None or not _background_thread.is_alive():
        _background_thread = threading.Thread(target=_background_worker, daemon=True)
        _background_thread.start()
        logger.debug("Started Kalytera background worker thread")

def trace(
    session_id: Optional[str] = None,
    user_input: Optional[str] = None,
    agent_response: Optional[str] = None,
    response_time_ms: Optional[int] = None,
    workflow_step: Optional[int] = None,
    tool_calls: Optional[List[str]] = None,
    tokens_used: Optional[int] = None,
    error_occurred: Optional[bool] = None,
    error_message: Optional[str] = None,
    session_ended: Optional[bool] = None,
    _config_override: Optional["KalyteraConfig"] = None,
) -> None:
    """
    Trace a single agent interaction - fire and forget
    
    This function:
    - Never blocks (returns immediately)
    - Never raises exceptions 
    - Fails silently if Kalytera is down
    - Logs locally for debugging
    
    Args:
        session_id: Unique identifier for the conversation session
        user_input: The user's message/query
        agent_response: The agent's response
        response_time_ms: Time taken to generate response (milliseconds)
        workflow_step: Step number in the conversation workflow
        tool_calls: List of tools/functions called during response
        tokens_used: Number of tokens consumed
        error_occurred: Whether an error occurred during this interaction
        error_message: Error message if error_occurred is True
    
    Example:
        kalytera.trace(
            session_id="session_123",
            user_input="Help me cancel my subscription",
            agent_response="I can help you cancel your subscription...",
            response_time_ms=850,
            workflow_step=1,
            tool_calls=["subscription_api", "billing_api"],
            tokens_used=145
        )
    """
    try:
        # Generate unique ID for this interaction
        interaction_id = str(uuid.uuid4())
        
        # Validate and sanitize inputs - never fail on bad data
        safe_session_id = str(session_id) if session_id is not None else f"unknown_{interaction_id[:8]}"
        safe_user_input = str(user_input) if user_input is not None else ""
        safe_agent_response = str(agent_response) if agent_response is not None else ""
        safe_response_time_ms = int(response_time_ms) if isinstance(response_time_ms, (int, float)) and response_time_ms >= 0 else 0
        
        # Create trace event — snapshot config so background thread uses correct settings
        trace_event = TraceEvent(
            session_id=safe_session_id,
            user_input=safe_user_input,
            agent_response=safe_agent_response,
            response_time_ms=safe_response_time_ms,
            workflow_step=workflow_step,
            tool_calls=tool_calls,
            tokens_used=tokens_used,
            error_occurred=error_occurred,
            error_message=error_message,
            session_ended=session_ended,
            config_snapshot=_config_override or _config,
        )
        
        # Queue for background processing — never blocks caller
        _ensure_background_worker()
        try:
            _trace_queue.put_nowait(trace_event)
            logger.debug(f"Queued trace for session {session_id}")
        except Exception:
            logger.debug(f"Trace queue full - dropping event for session {session_id}")
        
    except Exception as e:
        # Never let SDK failures affect the agent
        logger.debug(f"Error in trace function: {e}")

def shutdown():
    """
    Graceful shutdown of the SDK
    Waits for pending traces to be sent (with timeout)
    """
    global _shutdown_event, _background_thread
    
    logger.info("Shutting down Kalytera SDK...")
    
    # Signal shutdown
    _shutdown_event.set()
    
    # Wait for background thread to finish
    if _background_thread and _background_thread.is_alive():
        _background_thread.join(timeout=5.0)
    
    # Wait for queue to empty
    try:
        _trace_queue.join()
    except:
        pass
    
    logger.info("Kalytera SDK shutdown complete")

# Cleanup on module exit
import atexit
atexit.register(shutdown)