"""
Admin endpoints for Kalytera database initialization and maintenance
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
import subprocess

from api.database import get_db, engine
from db.models import Base

admin_router = APIRouter(prefix="/admin", tags=["admin"])


@admin_router.post("/init-database")
async def initialize_database():
    """
    Initialize database by creating all tables
    This endpoint creates the database schema without using migrations
    """
    try:
        # Create all tables defined in models
        Base.metadata.create_all(bind=engine)
        
        return {
            "success": True,
            "message": "Database initialized successfully",
            "timestamp": datetime.now().isoformat(),
            "tables_created": [table.name for table in Base.metadata.sorted_tables]
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Database initialization failed: {str(e)}"
        )


@admin_router.post("/run-migrations")
async def run_database_migrations():
    """
    Run Alembic database migrations
    """
    try:
        # Run alembic upgrade
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            cwd="/app"  # Railway app directory
        )
        
        if result.returncode == 0:
            return {
                "success": True,
                "message": "Database migrations completed successfully",
                "timestamp": datetime.now().isoformat(),
                "output": result.stdout
            }
        else:
            return {
                "success": False,
                "message": "Migration failed",
                "error": result.stderr,
                "output": result.stdout
            }
            
    except Exception as e:
        # Fallback to direct table creation and column additions
        try:
            # Create all tables
            Base.metadata.create_all(bind=engine)
            
            # Add missing failure_category column if it doesn't exist
            from sqlalchemy import text
            with engine.connect() as conn:
                try:
                    conn.execute(text("ALTER TABLE eval_results ADD COLUMN failure_category VARCHAR"))
                    conn.commit()
                except Exception:
                    pass  # Column might already exist
                    
            return {
                "success": True,
                "message": "Database initialized via direct table creation (migration fallback)",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as fallback_error:
            raise HTTPException(
                status_code=500,
                detail=f"Both migration and fallback failed: {str(e)}, {str(fallback_error)}"
            )


@admin_router.get("/database-status")
async def get_database_status(db: Session = Depends(get_db)):
    """
    Check database status and table existence
    """
    try:
        # Check if core tables exist
        tables_to_check = [
            "agent_logs", 
            "session_summaries", 
            "eval_results", 
            "loss_patterns"
        ]
        
        existing_tables = []
        missing_tables = []
        
        for table_name in tables_to_check:
            try:
                result = db.execute(text(f"SELECT COUNT(*) FROM {table_name} LIMIT 1"))
                existing_tables.append(table_name)
            except Exception:
                missing_tables.append(table_name)
        
        return {
            "database_connected": True,
            "existing_tables": existing_tables,
            "missing_tables": missing_tables,
            "tables_ready": len(missing_tables) == 0,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {
            "database_connected": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


@admin_router.post("/seed-sample-data")
async def seed_sample_data(db: Session = Depends(get_db)):
    """
    Seed database with sample data for testing
    """
    try:
        from db.models import AgentLog, SessionSummary
        import uuid
        from datetime import datetime, timedelta
        
        # Create sample session
        sample_session = SessionSummary(
            id=str(uuid.uuid4()),
            started_at=datetime.now() - timedelta(hours=1),
            ended_at=datetime.now(),
            primary_intent="billing",
            workflow_completed=True,
            success_score=0.85,
            total_interactions=3,
            duration_seconds=180,
            drop_off_step=None
        )
        
        db.add(sample_session)
        
        # Create sample agent logs
        for i in range(3):
            sample_log = AgentLog(
                id=str(uuid.uuid4()),
                session_id=sample_session.id,
                timestamp=datetime.now() - timedelta(minutes=30-i*10),
                user_input=f"Sample user input {i+1}",
                agent_response=f"Sample agent response {i+1}",
                intent="billing",
                workflow_step=i+1,
                response_time_ms=800 + i*100
            )
            db.add(sample_log)
        
        db.commit()
        
        return {
            "success": True,
            "message": "Sample data seeded successfully",
            "session_id": sample_session.id,
            "logs_created": 3,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Sample data seeding failed: {str(e)}"
        )