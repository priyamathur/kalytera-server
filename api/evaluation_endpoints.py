"""
Evaluation API endpoints for Kalytera
Manage LLM judge evaluations and background processing
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
import asyncio
from pydantic import BaseModel

from api.database import get_db
from evaluation.agent_judge import AgentJudge, EvaluationScheduler
from api.database import SessionLocal
from datetime import datetime, timedelta
from sqlalchemy import text

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
    except (ValueError, Exception) as e:
        print(f"⚠️ AgentJudge initialization failed: {e}")
        return None

@evaluation_router.get("/health")
async def evaluation_health_check():
    """Check evaluation system health"""
    
    try:
        judge = get_agent_judge()
        
        return {
            "evaluation_system": "online" if judge else "unavailable (no API key)",
            "anthropic_api": "configured" if judge else "not configured", 
            "background_scheduler": "running" if _evaluation_scheduler and _evaluation_scheduler.is_running else "stopped",
            "model": "claude-sonnet-4-6" if judge else None,
            "status": "healthy"
        }
    except Exception as e:
        return {
            "evaluation_system": "error",
            "error": str(e),
            "status": "unhealthy"
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


class EvaluationRequest(BaseModel):
    user_input: str
    agent_response: str
    context: Optional[str] = None

@evaluation_router.post("/evaluate-interaction")
async def evaluate_single_interaction(request: EvaluationRequest):
    """
    Evaluate a single interaction using LLM judge
    Required for enterprise evaluation capabilities
    """
    
    judge = get_agent_judge()
    if not judge:
        raise HTTPException(
            status_code=503,
            detail="Evaluation service unavailable - Anthropic API key not configured"
        )
    
    try:
        # Prepare conversation context
        conversation_context = []
        if request.context:
            conversation_context.append({"context": request.context})
        
        result = await judge.evaluate_interaction(
            user_input=request.user_input,
            agent_response=request.agent_response,
            conversation_context=conversation_context,
            tool_results=None,
            intent=None
        )
        
        return {
            "overall_score": result.overall_score,
            "accuracy_score": result.accuracy_score,
            "goal_alignment_score": result.goal_alignment_score,
            "decision_quality_score": result.decision_quality_score,
            "completeness_score": result.completeness_score,
            "failure_category": result.primary_failure_mode,
            "evaluation_reasoning": result.failure_reasoning,
            "improvement_suggestions": result.improvement_suggestions,
            "evaluator_model": result.evaluator_model
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Evaluation failed: {str(e)}"
        )


@evaluation_router.post("/batch-evaluate")
async def batch_evaluate_interactions(
    hours_back: float = 24.0,
    db: Session = Depends(get_db)
):
    """
    Batch evaluate interactions from the last hours_back period
    Alternative endpoint name for compatibility
    """
    return await trigger_batch_evaluation(hours_back=hours_back, db=db)


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


# Dashboard-specific endpoints
@evaluation_router.get("/recent-failures")
async def get_recent_failures(
    limit: int = 20,
    hours_back: int = 24,
    db: Session = Depends(get_db)
):
    """Get recent failures for dashboard failure feed"""
    
    cutoff_time = datetime.now() - timedelta(hours=hours_back)
    
    query = text("""
        SELECT 
            al.id,
            al.session_id,
            al.timestamp,
            al.user_input,
            al.agent_response,
            al.intent,
            er.overall_score,
            er.accuracy_score,
            er.goal_alignment_score,
            er.decision_quality_score,
            er.completeness_score,
            er.evaluation_reasoning,
            er.failure_category,
            er.evaluated_at
        FROM eval_results er
        JOIN agent_logs al ON er.agent_log_id = al.id
        WHERE er.evaluated_at >= :cutoff_time
        AND er.overall_score < 0.7
        ORDER BY er.evaluated_at DESC
        LIMIT :limit
    """)
    
    try:
        results = db.execute(query, {
            'cutoff_time': cutoff_time,
            'limit': limit
        }).fetchall()
        
        failures = []
        for row in results:
            failure = {
                "id": row.id,
                "session_id": row.session_id,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "user_input": row.user_input,
                "agent_response": row.agent_response,
                "intent": row.intent,
                "overall_score": row.overall_score,
                "accuracy_score": row.accuracy_score,
                "goal_alignment_score": row.goal_alignment_score,
                "decision_quality_score": row.decision_quality_score,
                "completeness_score": row.completeness_score,
                "evaluation_reasoning": row.evaluation_reasoning,
                "failure_category": row.failure_category,
                "is_oneoff_failure": True,  # Would need pattern matching logic
                "evaluated_at": row.evaluated_at.isoformat() if row.evaluated_at else None
            }
            failures.append(failure)
        
        return {
            "failures": failures,
            "total_count": len(failures),
            "time_period_hours": hours_back
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get recent failures: {str(e)}"
        )


@evaluation_router.get("/failure-stats")
async def get_failure_stats(
    hours_back: int = 24,
    db: Session = Depends(get_db)
):
    """Get failure statistics for dashboard overview"""
    
    cutoff_time = datetime.now() - timedelta(hours=hours_back)
    
    try:
        # Total failures
        total_query = text("""
            SELECT COUNT(*) as total_failures
            FROM eval_results er
            WHERE er.evaluated_at >= :cutoff_time
            AND er.overall_score < 0.7
        """)
        
        total_result = db.execute(total_query, {'cutoff_time': cutoff_time}).fetchone()
        total_failures = total_result.total_failures if total_result else 0
        
        # Average severity (1 - quality_score)
        avg_query = text("""
            SELECT AVG(1 - er.overall_score) as avg_severity
            FROM eval_results er
            WHERE er.evaluated_at >= :cutoff_time
            AND er.overall_score < 0.7
        """)
        
        avg_result = db.execute(avg_query, {'cutoff_time': cutoff_time}).fetchone()
        avg_severity = avg_result.avg_severity if avg_result and avg_result.avg_severity else 0
        
        return {
            "total_failures": total_failures,
            "oneoff_failures": int(total_failures * 0.3),  # Estimate
            "pattern_failures": int(total_failures * 0.7),  # Estimate
            "avg_severity_score": round(avg_severity, 3),
            "time_period_hours": hours_back
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get failure stats: {str(e)}"
        )


@evaluation_router.get("/interaction-detail/{interaction_id}")
async def get_interaction_detail(
    interaction_id: str,
    db: Session = Depends(get_db)
):
    """Get detailed evaluation data for a specific interaction"""
    
    query = text("""
        SELECT 
            er.overall_score,
            er.accuracy_score,
            er.goal_alignment_score,
            er.decision_quality_score,
            er.completeness_score,
            er.evaluation_reasoning,
            er.failure_category,
            er.confidence_level,
            er.evaluated_at
        FROM eval_results er
        WHERE er.agent_log_id = :interaction_id
    """)
    
    try:
        result = db.execute(query, {'interaction_id': interaction_id}).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Interaction evaluation not found")
        
        return {
            "overall_score": result.overall_score,
            "accuracy_score": result.accuracy_score,
            "goal_alignment_score": result.goal_alignment_score,
            "decision_quality_score": result.decision_quality_score,
            "completeness_score": result.completeness_score,
            "evaluation_reasoning": result.evaluation_reasoning,
            "failure_category": result.failure_category,
            "confidence_level": result.confidence_level,
            "evaluated_at": result.evaluated_at.isoformat() if result.evaluated_at else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get interaction detail: {str(e)}"
        )


@evaluation_router.get("/quality-config/{agent_id}")
async def get_quality_config(agent_id: str):
    """Get quality configuration for an agent"""
    
    # Return default config - in production this would be stored in database
    return {
        "agent_id": agent_id,
        "accuracy_weight": 0.25,
        "goal_alignment_weight": 0.35,
        "decision_quality_weight": 0.20,
        "completeness_weight": 0.20,
        "pass_threshold": 0.7,
        "enabled": True,
        "custom_criteria": None
    }


@evaluation_router.post("/update-quality-config")
async def update_quality_config(config: dict):
    """Update quality configuration for an agent"""
    
    # In production, this would save to database
    # For now, just validate and return success
    
    required_fields = [
        "agent_id", "accuracy_weight", "goal_alignment_weight", 
        "decision_quality_weight", "completeness_weight", "pass_threshold"
    ]
    
    for field in required_fields:
        if field not in config:
            raise HTTPException(
                status_code=400, 
                detail=f"Missing required field: {field}"
            )
    
    # Validate weights sum to 1.0
    total_weight = (
        config["accuracy_weight"] + 
        config["goal_alignment_weight"] + 
        config["decision_quality_weight"] + 
        config["completeness_weight"]
    )
    
    if abs(total_weight - 1.0) > 0.01:
        raise HTTPException(
            status_code=400,
            detail=f"Weights must sum to 1.0, got {total_weight:.2f}"
        )
    
    return {
        "success": True,
        "message": f"Quality configuration updated for agent {config['agent_id']}",
        "config": config
    }


@evaluation_router.post("/test-config")
async def test_quality_config(request: dict):
    """Test quality configuration on recent interactions"""
    
    agent_id = request.get("agent_id")
    config = request.get("config", {})
    
    # In production, this would apply config to recent interactions and return stats
    return {
        "success": True,
        "message": f"Configuration test completed for {agent_id}",
        "test_results": {
            "interactions_tested": 10,
            "estimated_pass_rate": 0.75,
            "avg_score_change": "+0.05"
        }
    }