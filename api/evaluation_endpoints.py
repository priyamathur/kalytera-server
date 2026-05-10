"""
Evaluation API endpoints for AgentIQ
Manage LLM judge evaluations and background processing
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Dict, Any, List
import asyncio
import os

from api.database import get_db
from evaluation.agent_judge import AgentJudge, EvaluationScheduler
from api.database import SessionLocal

# Create evaluation router
evaluation_router = APIRouter(prefix="/evaluation", tags=["evaluation"])

# Global evaluation scheduler
_evaluation_scheduler = None
_background_task = None

# Initialize judge (will fail gracefully if no API key)
def get_agent_judge():
    """Get AgentJudge instance, handling missing API key gracefully"""
    try:
        return AgentJudge()
    except ValueError:
        return None

@evaluation_router.get("/health")
async def evaluation_health_check():
    """Check evaluation system health"""
    
    judge = get_agent_judge()
    
    return {
        "evaluation_system": "online" if judge else "unavailable (no API key)",
        "anthropic_api": "configured" if judge else "not configured",
        "background_scheduler": "running" if _evaluation_scheduler and _evaluation_scheduler.is_running else "stopped",
        "model": judge.model if judge else None
    }


@evaluation_router.post("/evaluate-batch")
async def trigger_batch_evaluation(
    hours_back: float = 0.5,
    db: Session = Depends(get_db)
):
    """
    Manually trigger batch evaluation of recent logs
    
    Args:
        hours_back: How far back to look for unevaluated logs
    """
    
    judge = get_agent_judge()
    if not judge:
        raise HTTPException(
            status_code=503, 
            detail="Evaluation service unavailable - Anthropic API key not configured"
        )
    
    try:
        # Run evaluation
        results = await judge.evaluate_new_logs(db, hours_back=hours_back)
        
        if not results:
            return {
                "success": True,
                "message": f"No new logs found to evaluate in last {hours_back} hours",
                "evaluations_completed": 0
            }
        
        # Get summary of completed evaluations
        summary = judge.get_evaluation_summary(db, hours_back=1)
        
        return {
            "success": True,
            "message": f"Completed evaluation of {len(results)} interactions",
            "evaluations_completed": len(results),
            "quality_summary": summary,
            "hours_analyzed": hours_back
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Evaluation failed: {str(e)}"
        )


@evaluation_router.get("/summary")
async def get_evaluation_summary(
    hours_back: int = 24,
    db: Session = Depends(get_db)
):
    """
    Get summary of evaluation results for recent time period
    
    Args:
        hours_back: Time period to analyze (hours)
    """
    
    judge = get_agent_judge()
    if not judge:
        return {
            "message": "Evaluation service unavailable",
            "total_evaluations": 0
        }
    
    try:
        summary = judge.get_evaluation_summary(db, hours_back=hours_back)
        return summary
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get evaluation summary: {str(e)}"
        )


@evaluation_router.post("/start-background")
async def start_background_evaluation(
    interval_minutes: int = 30,
    background_tasks: BackgroundTasks = None
):
    """
    Start background evaluation job that runs every interval_minutes
    
    Args:
        interval_minutes: How often to run evaluations (default: 30 minutes)
    """
    
    global _evaluation_scheduler, _background_task
    
    judge = get_agent_judge()
    if not judge:
        raise HTTPException(
            status_code=503,
            detail="Cannot start background evaluation - Anthropic API key not configured"
        )
    
    # Stop existing scheduler if running
    if _evaluation_scheduler and _evaluation_scheduler.is_running:
        _evaluation_scheduler.stop_background_evaluation()
    
    # Create new scheduler
    _evaluation_scheduler = EvaluationScheduler(judge, SessionLocal)
    
    # Start background task
    if background_tasks:
        background_tasks.add_task(
            _evaluation_scheduler.start_background_evaluation,
            interval_minutes
        )
    else:
        # Start in asyncio task
        _background_task = asyncio.create_task(
            _evaluation_scheduler.start_background_evaluation(interval_minutes)
        )
    
    return {
        "success": True,
        "message": f"Background evaluation started (every {interval_minutes} minutes)",
        "interval_minutes": interval_minutes,
        "status": "running"
    }


@evaluation_router.post("/stop-background")
async def stop_background_evaluation():
    """Stop background evaluation job"""
    
    global _evaluation_scheduler, _background_task
    
    if _evaluation_scheduler and _evaluation_scheduler.is_running:
        _evaluation_scheduler.stop_background_evaluation()
        
        # Cancel asyncio task if exists
        if _background_task and not _background_task.done():
            _background_task.cancel()
        
        return {
            "success": True,
            "message": "Background evaluation stopped",
            "status": "stopped"
        }
    else:
        return {
            "success": True,
            "message": "Background evaluation was not running",
            "status": "already_stopped"
        }


@evaluation_router.get("/background-status")
async def get_background_status():
    """Get status of background evaluation job"""
    
    global _evaluation_scheduler
    
    if _evaluation_scheduler:
        is_running = _evaluation_scheduler.is_running
    else:
        is_running = False
    
    return {
        "background_evaluation": "running" if is_running else "stopped",
        "scheduler_exists": _evaluation_scheduler is not None,
        "evaluation_service": "available" if get_agent_judge() else "unavailable"
    }


@evaluation_router.get("/failure-patterns")
async def get_failure_patterns(
    hours_back: int = 24,
    db: Session = Depends(get_db)
):
    """
    Get failure patterns from recent evaluations
    Shows which failure modes are most common
    """
    
    from sqlalchemy import text
    from datetime import datetime, timedelta
    
    cutoff_time = datetime.now() - timedelta(hours=hours_back)
    
    # Query failure patterns from evaluations
    query = text("""
        SELECT 
            al.intent,
            er.evaluation_reasoning,
            er.overall_score,
            al.workflow_step,
            COUNT(*) as frequency
        FROM eval_results er
        JOIN agent_logs al ON er.agent_log_id = al.id  
        WHERE er.evaluated_at >= :cutoff_time
        AND er.overall_score < 0.7
        GROUP BY al.intent, er.evaluation_reasoning, er.overall_score, al.workflow_step
        ORDER BY frequency DESC, er.overall_score ASC
        LIMIT 20
    """)
    
    try:
        results = db.execute(query, {'cutoff_time': cutoff_time}).fetchall()
        
        failure_patterns = []
        for row in results:
            pattern = {
                "intent": row.intent or "unknown",
                "failure_description": row.evaluation_reasoning,
                "avg_quality_score": round(row.overall_score, 3),
                "workflow_step": row.workflow_step,
                "frequency": row.frequency,
                "severity": "high" if row.overall_score < 0.4 else "medium"
            }
            failure_patterns.append(pattern)
        
        return {
            "failure_patterns": failure_patterns,
            "total_patterns": len(failure_patterns),
            "analysis_period_hours": hours_back,
            "last_updated": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to analyze failure patterns: {str(e)}"
        )


@evaluation_router.post("/test-evaluation")
async def test_single_evaluation():
    """
    Test the evaluation system with a sample interaction
    Useful for validating the judge is working correctly
    """
    
    judge = get_agent_judge()
    if not judge:
        raise HTTPException(
            status_code=503,
            detail="Evaluation service unavailable - Anthropic API key not configured"
        )
    
    # Test interaction
    test_user_input = "I have a billing dispute and need a refund immediately"
    test_agent_response = "I understand your concern. Let me look into your billing issue. Unfortunately, I cannot access the billing system right now due to a technical issue. Please try again later."
    test_context = [
        {
            "user_input": "Hello, I need help with my account",
            "agent_response": "Hi! I'm happy to help you with your account. What specific issue are you having?"
        }
    ]
    
    try:
        result = await judge.evaluate_interaction(
            user_input=test_user_input,
            agent_response=test_agent_response,
            conversation_context=test_context,
            tool_results=None,
            intent="billing"
        )
        
        return {
            "success": True,
            "test_evaluation": {
                "user_input": test_user_input,
                "agent_response": test_agent_response,
                "scores": {
                    "accuracy": result.accuracy_score,
                    "goal_alignment": result.goal_alignment_score,
                    "decision_quality": result.decision_quality_score,
                    "completeness": result.completeness_score,
                    "overall": result.overall_score
                },
                "failure_analysis": {
                    "primary_failure_mode": result.primary_failure_mode,
                    "failure_reasoning": result.failure_reasoning,
                    "specific_issues": result.specific_issues,
                    "improvement_suggestions": result.improvement_suggestions
                },
                "confidence": result.confidence_level,
                "evaluator_model": result.evaluator_model
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Test evaluation failed: {str(e)}"
        )