"""
FastAPI ingest endpoints for AgentIQ
POST /ingest/json and /ingest/csv for real-time agent log ingestion
"""

from fastapi import FastAPI, HTTPException, File, UploadFile, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import List, Dict, Any, Optional, Union
import json
import io
from datetime import datetime
import asyncio
from sqlalchemy.orm import Session
from ingestion.parsers import LogParser, ParsedInteraction
from ingestion.session_builder import SessionBuilder, BatchSessionBuilder
from evaluation.intent_classifier import IntentClassifier
from db.models import Base, SessionSummary, AgentLog
from api.database import get_db, SessionLocal

# Initialize services
intent_classifier = None
try:
    intent_classifier = IntentClassifier()
    print("✅ Intent classifier initialized")
except Exception as e:
    print(f"⚠️  Intent classifier unavailable: {e}")

session_builder = SessionBuilder(intent_classifier)
batch_builder = BatchSessionBuilder(session_builder)

# FastAPI app
app = FastAPI(
    title="AgentIQ API",
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


# Request models
class JSONIngestRequest(BaseModel):
    """Request model for JSON log ingestion"""
    data: Union[List[Dict[str, Any]], Dict[str, Any]] = Field(
        ..., description="JSON log data - single object or array of objects"
    )
    source: Optional[str] = Field(
        "api", description="Source system identifier"
    )
    format_hint: Optional[str] = Field(
        None, description="Format hint: 'langsmith', 'generic', or auto-detect"
    )
    
    @validator('data')
    def validate_data(cls, v):
        if not v:
            raise ValueError("Data cannot be empty")
        return v


class IngestResponse(BaseModel):
    """Response model for ingestion endpoints"""
    success: bool
    message: str
    sessions_processed: int
    interactions_processed: int
    errors: List[str]
    processing_time_ms: int
    session_ids: List[str]


class IngestStatus(BaseModel):
    """Status model for background processing"""
    task_id: str
    status: str  # "processing", "completed", "failed"
    progress: float  # 0.0 - 1.0
    message: str
    sessions_processed: int = 0
    interactions_processed: int = 0


# In-memory task tracking (use Redis in production)
background_tasks_status = {}


# Helper functions
async def process_parsed_interactions(
    interactions: List[ParsedInteraction],
    db: Session,
    source: str
) -> IngestResponse:
    """Process parsed interactions into database"""
    
    start_time = datetime.now()
    errors = []
    
    try:
        # Build sessions from interactions
        session_summaries, agent_logs = await batch_builder.build_sessions_from_parsed_data(interactions)
        
        # Insert session summaries
        for summary in session_summaries:
            db.add(summary)
        
        # Insert agent logs
        for log in agent_logs:
            db.add(log)
        
        # Commit transaction
        db.commit()
        
        # Calculate processing time
        processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
        
        return IngestResponse(
            success=True,
            message=f"Successfully ingested {len(session_summaries)} sessions from {source}",
            sessions_processed=len(session_summaries),
            interactions_processed=len(agent_logs),
            errors=errors,
            processing_time_ms=processing_time,
            session_ids=[s.id for s in session_summaries]
        )
        
    except Exception as e:
        db.rollback()
        error_msg = f"Database insertion failed: {str(e)}"
        errors.append(error_msg)
        
        processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
        
        return IngestResponse(
            success=False,
            message=error_msg,
            sessions_processed=0,
            interactions_processed=0,
            errors=errors,
            processing_time_ms=processing_time,
            session_ids=[]
        )


async def background_ingest_task(
    task_id: str,
    interactions: List[ParsedInteraction],
    source: str
):
    """Background task for processing large ingestion jobs"""
    
    background_tasks_status[task_id] = IngestStatus(
        task_id=task_id,
        status="processing",
        progress=0.0,
        message="Starting ingestion..."
    )
    
    try:
        # Process in chunks for progress tracking
        chunk_size = 50
        total_sessions = len(set(i.session_id for i in interactions))
        processed_sessions = 0
        
        db = SessionLocal()
        
        for i in range(0, len(interactions), chunk_size):
            chunk = interactions[i:i + chunk_size]
            
            # Process chunk
            session_summaries, agent_logs = await batch_builder.build_sessions_from_parsed_data(chunk)
            
            # Insert to database
            for summary in session_summaries:
                db.add(summary)
            for log in agent_logs:
                db.add(log)
            
            db.commit()
            
            processed_sessions += len(session_summaries)
            progress = min(1.0, processed_sessions / total_sessions)
            
            # Update status
            background_tasks_status[task_id] = IngestStatus(
                task_id=task_id,
                status="processing",
                progress=progress,
                message=f"Processed {processed_sessions}/{total_sessions} sessions",
                sessions_processed=processed_sessions,
                interactions_processed=len(agent_logs)
            )
        
        # Mark completed
        background_tasks_status[task_id] = IngestStatus(
            task_id=task_id,
            status="completed",
            progress=1.0,
            message=f"Successfully processed {processed_sessions} sessions",
            sessions_processed=processed_sessions,
            interactions_processed=len(interactions)
        )
        
        db.close()
        
    except Exception as e:
        background_tasks_status[task_id] = IngestStatus(
            task_id=task_id,
            status="failed",
            progress=0.0,
            message=f"Processing failed: {str(e)}"
        )


# Endpoints
@app.get("/")
async def root():
    """Root endpoint - AgentIQ API welcome"""
    return {
        "message": "AgentIQ API",
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


@app.post("/ingest/json", response_model=IngestResponse)
async def ingest_json_logs(
    request: JSONIngestRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Ingest JSON format agent logs
    
    Supports:
    - Generic JSON logs with flexible field mapping
    - LangSmith trace exports
    - Custom agent framework exports
    """
    
    try:
        # Determine format
        format_type = request.format_hint or "auto"
        if format_type == "auto":
            # Auto-detect based on data structure
            if isinstance(request.data, dict) and "runs" in request.data:
                format_type = "langsmith"
            else:
                format_type = "json"
        
        # Parse interactions
        interactions = LogParser.parse(request.data, format_type)
        
        if not interactions:
            raise HTTPException(
                status_code=400,
                detail="No valid interactions found in provided data"
            )
        
        # For large datasets, process in background
        if len(interactions) > 100:
            task_id = f"ingest_{datetime.now().timestamp()}"
            background_tasks.add_task(
                background_ingest_task,
                task_id,
                interactions,
                request.source
            )
            
            return IngestResponse(
                success=True,
                message=f"Large dataset queued for background processing. Task ID: {task_id}",
                sessions_processed=0,
                interactions_processed=len(interactions),
                errors=[],
                processing_time_ms=0,
                session_ids=[]
            )
        
        # Process immediately for smaller datasets
        return await process_parsed_interactions(interactions, db, request.source)
        
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"JSON ingestion failed: {str(e)}"
        )


@app.post("/ingest/csv", response_model=IngestResponse)
async def ingest_csv_logs(
    file: UploadFile = File(...),
    source: str = "csv_upload",
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    """
    Ingest CSV format agent logs
    
    Automatically detects column mappings for:
    - session_id, timestamp, user_input, agent_response
    - tool_calls, response_time_ms, tokens_used
    - error information and metadata
    """
    
    # Validate file type
    if not file.filename.endswith('.csv'):
        raise HTTPException(
            status_code=400,
            detail="File must be a CSV (.csv extension required)"
        )
    
    try:
        # Read file content
        content = await file.read()
        csv_string = content.decode('utf-8')
        
        # Parse CSV
        interactions = LogParser.parse(csv_string, "csv")
        
        if not interactions:
            raise HTTPException(
                status_code=400,
                detail="No valid interactions found in CSV file"
            )
        
        # For large CSV files, process in background
        if len(interactions) > 100:
            task_id = f"csv_ingest_{datetime.now().timestamp()}"
            background_tasks.add_task(
                background_ingest_task,
                task_id,
                interactions,
                source
            )
            
            return IngestResponse(
                success=True,
                message=f"Large CSV queued for background processing. Task ID: {task_id}",
                sessions_processed=0,
                interactions_processed=len(interactions),
                errors=[],
                processing_time_ms=0,
                session_ids=[]
            )
        
        # Process immediately for smaller files
        return await process_parsed_interactions(interactions, db, source)
        
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="CSV file encoding error. Please ensure file is UTF-8 encoded."
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"CSV ingestion failed: {str(e)}"
        )


@app.get("/ingest/status/{task_id}", response_model=IngestStatus)
async def get_ingest_status(task_id: str):
    """Get status of background ingestion task"""
    
    if task_id not in background_tasks_status:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found"
        )
    
    return background_tasks_status[task_id]


@app.get("/ingest/tasks")
async def list_ingest_tasks():
    """List all background ingestion tasks"""
    return {
        "tasks": list(background_tasks_status.keys()),
        "status_counts": {
            "processing": sum(1 for s in background_tasks_status.values() if s.status == "processing"),
            "completed": sum(1 for s in background_tasks_status.values() if s.status == "completed"),
            "failed": sum(1 for s in background_tasks_status.values() if s.status == "failed")
        }
    }


# Testing endpoints
@app.post("/ingest/test/langsmith")
async def test_langsmith_ingestion(db: Session = Depends(get_db)):
    """Test LangSmith format ingestion with sample data"""
    
    sample_langsmith_data = {
        "id": "test-session-123",
        "runs": [
            {
                "id": "run-1",
                "name": "ChatOpenAI",
                "run_type": "llm",
                "start_time": "2024-01-01T10:00:00Z",
                "end_time": "2024-01-01T10:00:02Z",
                "inputs": {
                    "messages": [
                        {"type": "human", "content": "I need help with my billing"}
                    ]
                },
                "outputs": {
                    "content": "I'd be happy to help you with your billing question. Can you tell me more about the specific issue?"
                },
                "extra": {
                    "usage": {"total_tokens": 45}
                }
            },
            {
                "id": "run-2", 
                "name": "ChatOpenAI",
                "run_type": "llm",
                "start_time": "2024-01-01T10:01:00Z",
                "end_time": "2024-01-01T10:01:01Z",
                "inputs": {
                    "messages": [
                        {"type": "human", "content": "There's a charge I don't recognize on my account"}
                    ]
                },
                "outputs": {
                    "content": "Let me look up that charge for you. I can see the transaction details and help explain what it covers."
                },
                "extra": {
                    "usage": {"total_tokens": 38}
                }
            }
        ]
    }
    
    request = JSONIngestRequest(
        data=sample_langsmith_data,
        source="test_langsmith",
        format_hint="langsmith"
    )
    
    return await ingest_json_logs(request, None, db)


@app.post("/ingest/test/generic")
async def test_generic_json_ingestion(db: Session = Depends(get_db)):
    """Test generic JSON format ingestion with sample data"""
    
    sample_data = [
        {
            "session_id": "test-session-456",
            "timestamp": "2024-01-01T11:00:00Z",
            "user_input": "I want to cancel my subscription",
            "agent_response": "I can help you with cancelling your subscription. Let me pull up your account details.",
            "response_time_ms": 1200,
            "tokens_used": 32
        },
        {
            "session_id": "test-session-456", 
            "timestamp": "2024-01-01T11:00:30Z",
            "user_input": "Yes, please cancel it immediately",
            "agent_response": "I've successfully cancelled your subscription. You'll retain access until your current billing period ends on January 15th.",
            "response_time_ms": 800,
            "tokens_used": 28
        }
    ]
    
    request = JSONIngestRequest(
        data=sample_data,
        source="test_generic",
        format_hint="json"
    )
    
    return await ingest_json_logs(request, None, db)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)