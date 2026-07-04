"""
FastAPI ingest endpoints for Kalytera
POST /api/trace for real-time agent interaction tracing
Framework-agnostic webhook receiver that never blocks agents
"""

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
import logging
from ingestion.session_builder import SessionBuilder
from evaluation.intent_classifier import IntentClassifier
from api.database import get_db, SessionLocal

# Initialize services
intent_classifier = None
try:
    intent_classifier = IntentClassifier()
    print("✅ Intent classifier initialized")
except Exception as e:
    print(f"⚠️  Intent classifier unavailable: {e}")

session_builder = SessionBuilder(intent_classifier)

# FastAPI app
app = FastAPI(
    title="Kalytera API",
    description="Real-time agent log ingestion and usage analytics platform",
    version="1.0.0"
)

# Import and include routers
from api.analytics_endpoints import analytics_router
from api.evaluation_endpoints import evaluation_router
from api.pattern_endpoints import pattern_router
from api.monitoring import monitoring_router
from api.admin_endpoints import admin_router
app.include_router(analytics_router)
app.include_router(evaluation_router)
app.include_router(pattern_router)
app.include_router(monitoring_router)
app.include_router(admin_router)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database dependency imported from api.database


# Real-time trace models
class TraceRequest(BaseModel):
    """Real-time agent interaction trace request"""
    session_id: str = Field(..., description="Unique session identifier")
    timestamp: str = Field(..., description="ISO timestamp of the interaction")
    user_input: str = Field(..., description="User's message/query")
    agent_response: str = Field(..., description="Agent's response")
    response_time_ms: int = Field(..., description="Response time in milliseconds")
    workflow_step: Optional[int] = Field(1, description="Step in conversation workflow")
    tool_calls: Optional[str] = Field(None, description="JSON string of tools used")
    tokens_used: Optional[int] = Field(None, description="Number of tokens consumed")
    error_occurred: Optional[bool] = Field(False, description="Whether an error occurred")
    error_message: Optional[str] = Field(None, description="Error message if error occurred")

class TraceResponse(BaseModel):
    """Real-time trace response"""
    success: bool
    message: str
    processing_time_ms: int

# Batch processing models and functions removed - Kalytera is real-time only


# Real-time trace endpoint
@app.post("/trace", response_model=TraceResponse)
async def trace_interaction(
    trace: TraceRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Real-time agent interaction trace webhook
    
    Framework-agnostic endpoint that:
    - Never blocks (returns immediately)
    - Never raises exceptions to callers
    - Processes traces asynchronously
    - Builds sessions in real-time
    
    This is the primary entry point for production agents.
    """
    start_time = datetime.now()
    
    try:
        # Convert trace request to database models
        from datetime import datetime as dt
        from db.models import AgentLog
        import uuid
        
        # Parse timestamp
        try:
            timestamp = dt.fromisoformat(trace.timestamp.replace('Z', '+00:00'))
        except:
            timestamp = datetime.now()
        
        # Create AgentLog entry
        agent_log = AgentLog(
            id=str(uuid.uuid4()),
            session_id=trace.session_id,
            timestamp=timestamp,
            user_input=trace.user_input,
            agent_response=trace.agent_response,
            workflow_step=trace.workflow_step,
            tool_calls=trace.tool_calls,
            response_time_ms=trace.response_time_ms,
            tokens_used=trace.tokens_used,
            error_occurred=trace.error_occurred,
            error_message=trace.error_message
        )
        
        # Add to database immediately (fast insert)
        db.add(agent_log)
        db.commit()
        
        # Schedule background session building and intent classification
        background_tasks.add_task(
            process_trace_background,
            trace.session_id,
            agent_log.id
        )
        
        processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
        
        return TraceResponse(
            success=True,
            message="Trace received and queued for processing",
            processing_time_ms=processing_time
        )
        
    except Exception as e:
        # Never raise exceptions to the calling agent
        # Log locally and return success to avoid breaking agent
        logger = logging.getLogger("kalytera.trace")
        logger.error(f"Trace processing failed for session {trace.session_id}: {e}")
        
        processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
        
        # Still return success to avoid blocking the agent
        return TraceResponse(
            success=True,  # Always return success to agent
            message="Trace received",
            processing_time_ms=processing_time
        )

async def process_trace_background(session_id: str, agent_log_id: str):
    """
    Background processing for trace events:
    1. Classify intent (first 2 interactions)
    2. Update session summary in real-time
    """
    try:
        db = SessionLocal()
        
        # Check if this is one of the first 2 interactions for intent classification
        from sqlalchemy import text
        
        interaction_count_query = text("""
            SELECT COUNT(*) FROM agent_logs 
            WHERE session_id = :session_id
        """)
        
        result = db.execute(interaction_count_query, {"session_id": session_id})
        interaction_count = result.scalar()
        
        # Classify intent on first 2 interactions
        if interaction_count <= 2 and intent_classifier:
            try:
                # Get recent interactions for this session
                recent_interactions_query = text("""
                    SELECT user_input, agent_response 
                    FROM agent_logs 
                    WHERE session_id = :session_id 
                    ORDER BY timestamp ASC 
                    LIMIT 2
                """)
                
                interactions = db.execute(recent_interactions_query, {"session_id": session_id}).fetchall()
                
                # Build conversation context for intent classification
                conversation_text = []
                for user_input, agent_response in interactions:
                    conversation_text.append(f"User: {user_input}")
                    conversation_text.append(f"Agent: {agent_response}")
                
                conversation = "\n".join(conversation_text)
                
                # Classify intent
                intent_result = await intent_classifier.classify_intent(conversation)
                
                # Update all logs in this session with the classified intent
                if intent_result and intent_result.get('intent'):
                    update_intent_query = text("""
                        UPDATE agent_logs 
                        SET intent = :intent 
                        WHERE session_id = :session_id 
                        AND intent IS NULL
                    """)
                    
                    db.execute(update_intent_query, {
                        "intent": intent_result['intent'],
                        "session_id": session_id
                    })
                    
            except Exception as e:
                logger = logging.getLogger("kalytera.background")
                logger.error(f"Intent classification failed for session {session_id}: {e}")
        
        # Update session summary
        await session_builder.update_session_summary(session_id, db)
        
        db.commit()
        db.close()
        
    except Exception as e:
        logger = logging.getLogger("kalytera.background")
        logger.error(f"Background trace processing failed for session {session_id}: {e}")

# Endpoints
@app.get("/")
async def root():
    """Root endpoint - Kalytera API welcome"""
    return {
        "message": "Kalytera API",
        "description": "Real-time agent log ingestion and usage analytics platform",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "docs": "/docs",
            "ingestion": "/ingest/*",
            "analytics": "/analytics/*", 
            "evaluation": "/evaluation/*",
            "patterns": "/patterns/*"
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "intent_classifier": intent_classifier is not None,
            "database": True  # Could add actual DB connectivity check
        }
    }


# BATCH INGESTION ENDPOINTS REMOVED
# Kalytera runs alongside agents in real-time, not as a batch log processor
# Use the /api/trace endpoint for real-time agent interaction tracing

# @app.post("/ingest/json") - REMOVED: Use /api/trace instead
# @app.post("/ingest/csv") - REMOVED: Use /api/trace instead
# 
# Kalytera is designed for real-time agent monitoring, not log analysis.
# If you need to import historical data, use the SDK in replay mode:


# Batch task monitoring endpoints removed - not needed for real-time tracing


# Testing endpoints
@app.post("/ingest/recent-logs")
async def get_recent_logs(
    request: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db)
):
    """Get recent agent logs for dashboard display"""
    
    limit = 1000
    if request and "limit" in request:
        limit = min(request["limit"], 5000)  # Max 5000 for performance
    
    try:
        from sqlalchemy import text
        
        # Get recent logs directly from agent_logs
        query = text("""
            SELECT 
                session_id,
                timestamp,
                user_input,
                agent_response,
                intent,
                response_time_ms,
                tool_calls,
                workflow_step,
                error_occurred
            FROM agent_logs
            WHERE timestamp >= NOW() - INTERVAL '7 days'
            ORDER BY timestamp DESC
            LIMIT :limit
        """)
        
        result = db.execute(query, {"limit": limit}).fetchall()
        
        logs = []
        for row in result:
            log_dict = {
                "session_id": row[0],
                "timestamp": row[1].isoformat() if row[1] else None,
                "user_input": row[2],
                "agent_response": row[3],
                "intent": row[4],
                "response_time_ms": row[5],
                "tool_calls": row[6],
                "workflow_step": row[7],
                "error_occurred": row[8]
            }
            logs.append(log_dict)
        
        return {
            "success": True,
            "logs": logs,
            "count": len(logs),
            "limit_applied": limit
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch recent logs: {str(e)}"
        )


@app.post("/trace/test")
async def test_trace_endpoint(db: Session = Depends(get_db)):
    """Test the real-time trace endpoint with sample data"""
    
    from datetime import datetime
    import uuid
    
    test_session_id = str(uuid.uuid4())
    
    # Simulate a real-time trace call
    sample_trace = TraceRequest(
        session_id=test_session_id,
        timestamp=datetime.now().isoformat(),
        user_input="I need help with my billing",
        agent_response="I'd be happy to help you with your billing question. Let me look up your account details.",
        response_time_ms=1200,
        workflow_step=1,
        tool_calls='["billing_api", "account_lookup"]',
        tokens_used=45,
        error_occurred=False
    )
    
    # Call the trace endpoint
    from fastapi import BackgroundTasks
    background_tasks = BackgroundTasks()
    
    response = await trace_interaction(sample_trace, background_tasks, db)
    
    return {
        "message": "Real-time trace test completed",
        "test_session_id": test_session_id,
        "trace_response": response
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)