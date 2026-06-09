"""
Analytics API endpoints for AgentIQ
6 core endpoints providing actionable insights from agent interaction data
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import text

from analytics.usage_analytics import (
    UsageAnalyticsEngine,
    WorkflowPath,
    DropoffInsight,
    ToolUsageAnalytics,
    QualityByIntent
)
from api.database import get_db

# Create analytics router
analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])


@analytics_router.get("/session-volume", response_model=List[Dict[str, Any]])
async def get_session_volume_analytics(
    hours_back: int = Query(168, description="Hours back to analyze (default: 1 week)"),
    granularity: str = Query("hour", description="Time granularity: hour, day, week"),
    db: Session = Depends(get_db)
):
    """
    **Session Volume Over Time**
    
    Shows session trends, peak usage times, and capacity planning insights.
    Critical for understanding when your agents are most/least busy.
    
    **Insights provided:**
    - Session count trends
    - Interaction volume patterns  
    - Completion rate trends
    - Average session duration over time
    """
    
    try:
        analytics_engine = UsageAnalyticsEngine(db)
        volume_data = analytics_engine.get_session_volume_over_time(hours_back, granularity)
        
        # Convert to API response format
        return [
            {
                "timestamp": point.timestamp.isoformat(),
                "session_count": point.session_count,
                "interaction_count": point.interaction_count,
                "avg_duration_seconds": round(point.avg_duration_seconds, 1),
                "completion_rate": round(point.completion_rate, 3)
            }
            for point in volume_data
        ]
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get session volume data: {str(e)}")


@analytics_router.get("/intent-performance", response_model=List[Dict[str, Any]])
async def get_intent_performance_analytics(
    limit: int = Query(10, description="Number of top intents to return"),
    db: Session = Depends(get_db)
):
    """
    **Top Intents with Performance Metrics**
    
    Shows which user intents your agent handles well vs poorly.
    Essential for prioritizing improvement efforts.
    
    **Insights provided:**
    - Completion rates by intent
    - Average conversation length
    - Success scores and error rates
    - Volume distribution across intents
    """
    
    try:
        analytics_engine = UsageAnalyticsEngine(db)
        intent_data = analytics_engine.get_top_intents_analytics(limit)
        
        return [
            {
                "intent": intent.intent,
                "session_count": intent.session_count,
                "completion_rate": round(intent.completion_rate, 3),
                "avg_steps": round(intent.avg_steps, 1),
                "avg_success_score": round(intent.avg_success_score, 3),
                "total_interactions": intent.total_interactions,
                "avg_duration_seconds": round(intent.avg_duration_seconds, 1),
                "error_rate": round(intent.error_rate, 3),
                "performance_grade": _get_performance_grade(intent.completion_rate, intent.avg_success_score)
            }
            for intent in intent_data
        ]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get intent analytics: {str(e)}")


@analytics_router.get("/workflow-paths", response_model=List[Dict[str, Any]])
async def get_workflow_path_analytics(
    intent_filter: Optional[str] = Query(None, description="Filter by specific intent"),
    min_frequency: int = Query(5, description="Minimum frequency to include path"),
    db: Session = Depends(get_db)
):
    """
    **Most Common Workflow Paths**
    
    Shows how users actually navigate through conversations.
    Reveals gaps between intended workflows and reality.
    
    **Insights provided:**
    - Most common conversation flows
    - Completion rates by path type
    - Intent distribution across paths
    - Path efficiency metrics
    """
    
    try:
        analytics_engine = UsageAnalyticsEngine(db)
        workflow_data = analytics_engine.get_workflow_paths(intent_filter, min_frequency)
        
        return [
            {
                "path_description": " → ".join(path.path),
                "path_steps": path.path,
                "frequency": path.frequency,
                "completion_rate": round(path.completion_rate, 3),
                "avg_duration_seconds": round(path.avg_duration, 1),
                "intent_distribution": path.intent_distribution,
                "efficiency_score": _calculate_path_efficiency(path)
            }
            for path in workflow_data
        ]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get workflow path analytics: {str(e)}")


@analytics_router.get("/dropoff-analysis", response_model=List[Dict[str, Any]])
async def get_dropoff_analysis(
    db: Session = Depends(get_db)
):
    """
    **Drop-off Analysis - MOST IMPACTFUL INSIGHT**
    
    Shows exactly where users abandon conversations and why.
    This is the single most actionable insight for improving agent performance.
    
    **Insights provided:**
    - Drop-off rates by conversation step
    - Intent breakdown for each drop-off point
    - Common failure reasons
    - Impact scores for prioritization
    """
    
    try:
        analytics_engine = UsageAnalyticsEngine(db)
        dropoff_data = analytics_engine.get_dropoff_analysis()
        
        return [
            {
                "step": insight.step,
                "dropoff_count": insight.dropoff_count,
                "dropoff_rate": round(insight.dropoff_rate, 3),
                "intent_breakdown": insight.intent_breakdown,
                "common_failure_reasons": insight.common_reasons,
                "impact_score": round(insight.impact_score, 2),
                "priority_level": _get_priority_level(insight.impact_score),
                "recommended_actions": _get_dropoff_recommendations(insight)
            }
            for insight in dropoff_data
        ]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get drop-off analysis: {str(e)}")


@analytics_router.get("/tool-performance", response_model=List[Dict[str, Any]])
async def get_tool_performance_analytics(
    db: Session = Depends(get_db)
):
    """
    **Tool Usage and Failure Rates**
    
    Shows which integrations/tools work well vs which ones cause problems.
    Critical for identifying infrastructure issues.
    
    **Insights provided:**
    - Tool success/failure rates
    - Performance metrics by tool
    - Common failure modes
    - Intent-specific tool usage
    """
    
    try:
        analytics_engine = UsageAnalyticsEngine(db)
        tool_data = analytics_engine.get_tool_usage_analytics()
        
        return [
            {
                "tool_name": tool.tool_name,
                "usage_count": tool.usage_count,
                "success_rate": round(tool.success_rate, 3),
                "avg_response_time_ms": round(tool.avg_response_time_ms, 1),
                "failure_modes": tool.failure_modes,
                "intent_usage_distribution": tool.intent_usage,
                "health_status": _get_tool_health_status(tool.success_rate, tool.avg_response_time_ms),
                "recommendations": _get_tool_recommendations(tool)
            }
            for tool in tool_data
        ]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get tool performance analytics: {str(e)}")


@analytics_router.get("/quality-by-intent", response_model=List[Dict[str, Any]])
async def get_quality_by_intent_analytics(
    db: Session = Depends(get_db)
):
    """
    **Quality Pass Rates by Intent**
    
    Bridge between usage patterns and loss patterns.
    Shows which intents consistently produce high/low quality responses.
    
    **Insights provided:**
    - Pass rates vs benchmarks by intent
    - Quality score distributions
    - Top failure patterns per intent
    - Sample sizes for confidence
    """
    
    try:
        analytics_engine = UsageAnalyticsEngine(db)
        quality_data = analytics_engine.get_quality_by_intent()
        
        return [
            {
                "intent": quality.intent,
                "pass_rate": round(quality.pass_rate, 3),
                "avg_quality_score": round(quality.avg_quality_score, 3),
                "sample_size": quality.sample_size,
                "benchmark_comparison": quality.benchmark_comparison,
                "confidence_level": _get_confidence_level(quality.sample_size),
                "top_failure_patterns": quality.top_failure_patterns,
                "improvement_potential": _calculate_improvement_potential(quality),
                "next_actions": _get_quality_improvement_actions(quality)
            }
            for quality in quality_data
        ]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get quality analytics: {str(e)}")


@analytics_router.get("/dashboard-summary", response_model=Dict[str, Any])
async def get_analytics_dashboard_summary(
    db: Session = Depends(get_db)
):
    """
    **High-Level Analytics Summary**
    
    Key metrics for executive dashboard and quick health check.
    Perfect for monitoring overall agent performance.
    
    **Insights provided:**
    - Overall completion and quality rates
    - Volume and usage trends
    - Drop-off and failure indicators
    - System health overview
    """
    
    try:
        analytics_engine = UsageAnalyticsEngine(db)
        summary = analytics_engine.get_analytics_summary()
        
        # Add derived insights
        summary["health_score"] = _calculate_overall_health_score(summary)
        summary["trend_indicator"] = _get_trend_indicator(summary)
        summary["top_priority_actions"] = _get_top_priority_actions(summary)
        summary["data_freshness"] = datetime.now().isoformat()
        
        return summary
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get dashboard summary: {str(e)}")


# Helper functions for enriching analytics data
def _get_performance_grade(completion_rate: float, success_score: float) -> str:
    """Calculate performance grade for intent"""
    combined_score = (completion_rate + success_score) / 2
    if combined_score >= 0.8:
        return "A"
    elif combined_score >= 0.7:
        return "B"
    elif combined_score >= 0.6:
        return "C"
    elif combined_score >= 0.5:
        return "D"
    else:
        return "F"


def _calculate_path_efficiency(path: WorkflowPath) -> float:
    """Calculate efficiency score for workflow path"""
    # Efficient paths: high completion rate, reasonable duration, not too many steps
    step_penalty = len(path.path) * 0.05  # Penalty for long paths
    duration_penalty = max(0, (path.avg_duration - 300) / 1000 * 0.1)  # Penalty for >5min sessions
    
    efficiency = path.completion_rate - step_penalty - duration_penalty
    return max(0.0, min(1.0, efficiency))


def _get_priority_level(impact_score: float) -> str:
    """Determine priority level based on impact score"""
    if impact_score >= 5.0:
        return "Critical"
    elif impact_score >= 2.0:
        return "High"
    elif impact_score >= 0.5:
        return "Medium"
    else:
        return "Low"


def _get_dropoff_recommendations(insight: DropoffInsight) -> List[str]:
    """Generate actionable recommendations for drop-off points"""
    recommendations = []
    
    if insight.step <= 2:
        recommendations.append("Improve initial user understanding and expectation setting")
    
    if insight.common_reasons:
        recommendations.append("Address common error patterns: " + ", ".join(insight.common_reasons[:2]))
    
    if insight.dropoff_rate > 0.2:
        recommendations.append("Implement proactive user assistance at this step")
    
    # Intent-specific recommendations
    top_intent = max(insight.intent_breakdown.items(), key=lambda x: x[1])[0] if insight.intent_breakdown else None
    if top_intent == "refunds":
        recommendations.append("Streamline refund validation process")
    elif top_intent == "account_recovery":
        recommendations.append("Simplify identity verification flow")
    
    return recommendations[:3]  # Top 3 recommendations


def _get_tool_health_status(success_rate: float, avg_response_time: float) -> str:
    """Determine tool health status"""
    if success_rate >= 0.95 and avg_response_time <= 2000:
        return "Excellent"
    elif success_rate >= 0.85 and avg_response_time <= 5000:
        return "Good"
    elif success_rate >= 0.7 and avg_response_time <= 10000:
        return "Fair"
    else:
        return "Poor"


def _get_tool_recommendations(tool: ToolUsageAnalytics) -> List[str]:
    """Generate recommendations for tool improvements"""
    recommendations = []
    
    if tool.success_rate < 0.8:
        recommendations.append("Investigate and fix reliability issues")
    
    if tool.avg_response_time_ms > 5000:
        recommendations.append("Optimize for faster response times")
    
    if len(tool.failure_modes) > 0:
        top_failure = max(tool.failure_modes, key=lambda x: x['count'])
        recommendations.append(f"Address primary failure mode: {top_failure['error_type']}")
    
    return recommendations


def _get_confidence_level(sample_size: int) -> str:
    """Get confidence level based on sample size"""
    if sample_size >= 100:
        return "High"
    elif sample_size >= 30:
        return "Medium"
    elif sample_size >= 10:
        return "Low"
    else:
        return "Very Low"


def _calculate_improvement_potential(quality: QualityByIntent) -> float:
    """Calculate potential improvement score"""
    # Higher potential if currently below benchmark with reasonable sample size
    if quality.benchmark_comparison == "below" and quality.sample_size >= 10:
        return (1.0 - quality.pass_rate) * (quality.sample_size / 100)
    return 0.0


def _get_quality_improvement_actions(quality: QualityByIntent) -> List[str]:
    """Get specific improvement actions for quality issues"""
    actions = []
    
    if quality.pass_rate < 0.6:
        actions.append("Urgent: Review agent training for this intent")
    
    if quality.benchmark_comparison == "below":
        actions.append("Analyze successful sessions for best practices")
    
    if quality.top_failure_patterns:
        actions.append(f"Fix pattern: {quality.top_failure_patterns[0]}")
    
    return actions


def _calculate_overall_health_score(summary: Dict[str, Any]) -> float:
    """Calculate overall system health score"""
    completion_weight = 0.3
    quality_weight = 0.3
    dropoff_weight = 0.4  # Weighted higher as it's most actionable
    
    completion_score = summary.get('overall_completion_rate', 0)
    quality_score = summary.get('avg_quality_score', 0)
    dropoff_score = 1.0 - summary.get('dropoff_rate', 1.0)  # Invert dropoff rate
    
    health_score = (
        completion_score * completion_weight +
        quality_score * quality_weight +
        dropoff_score * dropoff_weight
    )
    
    return round(health_score, 3)


def _get_trend_indicator(summary: Dict[str, Any]) -> str:
    """Simple trend indicator - would need time series data for real trends"""
    health_score = _calculate_overall_health_score(summary)
    
    if health_score >= 0.8:
        return "Positive"
    elif health_score >= 0.6:
        return "Stable"
    else:
        return "Concerning"


def _get_top_priority_actions(summary: Dict[str, Any]) -> List[str]:
    """Generate top priority actions based on summary metrics"""
    actions = []
    
    if summary.get('dropoff_rate', 0) > 0.3:
        actions.append("Investigate high drop-off rates")
    
    if summary.get('overall_completion_rate', 0) < 0.6:
        actions.append("Improve conversation completion flows")
    
    if summary.get('avg_quality_score', 0) < 0.6:
        actions.append("Review agent response quality")
    
    return actions[:3]


# Alias endpoints for integration test compatibility
@analytics_router.get("/top-intents")
async def get_top_intents_alias(
    hours_back: int = Query(168, description="Hours back to analyze"),
    limit: int = Query(10, description="Number of top intents to return"),
    db: Session = Depends(get_db)
):
    """Alias for intent-performance endpoint"""
    return await get_intent_performance_analytics(limit, db)


@analytics_router.get("/workflow-dropoff")  
async def get_workflow_dropoff_alias(
    hours_back: int = Query(168, description="Hours back to analyze"),
    db: Session = Depends(get_db)
):
    """Alias for dropoff-analysis endpoint"""
    return await get_dropoff_analysis(db)


@analytics_router.get("/tool-usage")
async def get_tool_usage_alias(
    hours_back: int = Query(168, description="Hours back to analyze"), 
    db: Session = Depends(get_db)
):
    """Alias for tool-performance endpoint"""
    return await get_tool_performance_analytics(db)


@analytics_router.get("/drop-off-analysis")
async def get_drop_off_analysis_alias(
    hours_back: int = Query(168, description="Hours back to analyze"),
    db: Session = Depends(get_db)
):
    """
    Drop-off Analysis (with hyphens for test compatibility)
    Shows where users abandon conversations - the most impactful insight
    """
    try:
        analytics_engine = UsageAnalyticsEngine(db)
        dropoff_data = analytics_engine.get_dropoff_analysis()
        
        # Format for test compatibility
        drop_off_by_step = {}
        for insight in dropoff_data:
            step_key = f"step_{insight.step}"
            drop_off_by_step[step_key] = {
                "sessions": insight.dropoff_count,
                "drop_rate": round(insight.dropoff_rate, 3),
                "intent_breakdown": insight.intent_breakdown,
                "common_reasons": insight.common_reasons
            }
        
        return {
            "drop_off_by_step": drop_off_by_step,
            "analysis_period_hours": hours_back,
            "total_dropoff_points": len(dropoff_data),
            "last_updated": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get drop-off analysis: {str(e)}")


@analytics_router.get("/recent-logs")
async def get_recent_logs(
    limit: int = Query(1000, description="Number of recent logs to return (max 5000)"),
    hours_back: int = Query(24, description="Hours back to look for logs"),
    intent_filter: Optional[str] = Query(None, description="Filter by specific intent"),
    db: Session = Depends(get_db)
):
    """
    **Recent Agent Logs**
    
    Get recent raw agent logs for dashboard display and analysis.
    Returns direct agent_logs data for real-time insights.
    """
    
    limit = min(limit, 5000)  # Max 5000 for performance
    
    try:
        from sqlalchemy import text
        
        # Build filter conditions
        where_conditions = ["timestamp >= NOW() - INTERVAL ':hours_back hours'"]
        params = {"limit": limit, "hours_back": hours_back}
        
        if intent_filter:
            where_conditions.append("intent = :intent_filter")
            params["intent_filter"] = intent_filter
        
        where_clause = " AND ".join(where_conditions)
        
        # Get recent logs directly from agent_logs
        query = text(f"""
            SELECT 
                session_id,
                timestamp,
                user_input,
                agent_response,
                intent,
                response_time_ms,
                tool_calls,
                workflow_step,
                error_occurred,
                tokens_used
            FROM agent_logs
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT :limit
        """)
        
        result = db.execute(query, params).fetchall()
        
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
                "error_occurred": bool(row[8]) if row[8] is not None else False,
                "tokens_used": row[9]
            }
            logs.append(log_dict)
        
        return {
            "success": True,
            "logs": logs,
            "count": len(logs),
            "limit_applied": limit,
            "hours_analyzed": hours_back,
            "intent_filter": intent_filter,
            "last_updated": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch recent logs: {str(e)}"
        )


# Additional dashboard endpoints
@analytics_router.get("/quality-trend")
async def get_quality_trend(
    hours_back: int = Query(24, description="Hours back to analyze"),
    db: Session = Depends(get_db)
):
    """Get quality score trend over time for dashboard"""
    
    try:
        # Create hourly buckets
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        
        query = text("""
            SELECT 
                DATE_TRUNC('hour', er.evaluated_at) as hour,
                AVG(er.overall_score) as avg_quality_score,
                COUNT(*) as evaluation_count
            FROM eval_results er
            WHERE er.evaluated_at >= :cutoff_time
            GROUP BY DATE_TRUNC('hour', er.evaluated_at)
            ORDER BY hour ASC
        """)
        
        results = db.execute(query, {'cutoff_time': cutoff_time}).fetchall()
        
        trend_data = []
        for row in results:
            trend_data.append({
                "hour": row.hour.isoformat() if row.hour else None,
                "avg_quality_score": round(row.avg_quality_score, 3) if row.avg_quality_score else 0,
                "evaluation_count": row.evaluation_count
            })
        
        return trend_data
        
    except Exception as e:
        # Return empty trend data for graceful failure
        return []


@analytics_router.get("/session-detail/{session_id}")
async def get_session_detail(
    session_id: str,
    db: Session = Depends(get_db)
):
    """Get detailed information about a specific session"""
    
    try:
        # Get session summary
        summary_query = text("""
            SELECT * FROM session_summaries WHERE id = :session_id
        """)
        
        summary_result = db.execute(summary_query, {'session_id': session_id}).fetchone()
        
        if not summary_result:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session_detail = {
            "id": summary_result.id,
            "started_at": summary_result.started_at.isoformat() if summary_result.started_at else None,
            "ended_at": summary_result.ended_at.isoformat() if summary_result.ended_at else None,
            "duration_seconds": summary_result.duration_seconds,
            "total_interactions": summary_result.total_interactions,
            "primary_intent": summary_result.primary_intent,
            "intent_confidence": summary_result.intent_confidence,
            "workflow_completed": summary_result.workflow_completed,
            "drop_off_step": summary_result.drop_off_step,
            "total_tokens": summary_result.total_tokens,
            "avg_response_time_ms": summary_result.avg_response_time_ms,
            "errors_count": summary_result.errors_count,
            "success_score": summary_result.success_score
        }
        
        return session_detail
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get session detail: {str(e)}"
        )


@analytics_router.get("/session-interactions/{session_id}")
async def get_session_interactions(
    session_id: str,
    db: Session = Depends(get_db)
):
    """Get all interactions for a specific session"""
    
    try:
        query = text("""
            SELECT 
                id,
                session_id,
                timestamp,
                user_input,
                agent_response,
                intent,
                workflow_step,
                tool_calls,
                response_time_ms,
                tokens_used,
                error_occurred,
                error_message
            FROM agent_logs
            WHERE session_id = :session_id
            ORDER BY workflow_step ASC, timestamp ASC
        """)
        
        results = db.execute(query, {'session_id': session_id}).fetchall()
        
        interactions = []
        for row in results:
            interaction = {
                "id": row.id,
                "session_id": row.session_id,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "user_input": row.user_input,
                "agent_response": row.agent_response,
                "intent": row.intent,
                "workflow_step": row.workflow_step,
                "tool_calls": row.tool_calls,
                "response_time_ms": row.response_time_ms,
                "tokens_used": row.tokens_used,
                "error_occurred": row.error_occurred,
                "error_message": row.error_message
            }
            interactions.append(interaction)
        
        return {
            "interactions": interactions,
            "total_count": len(interactions),
            "session_id": session_id
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get session interactions: {str(e)}"
        )


@analytics_router.get("/recent-sessions")
async def get_recent_sessions(
    limit: int = Query(20, description="Number of sessions to return"),
    failed_only: bool = Query(False, description="Only return failed sessions"),
    db: Session = Depends(get_db)
):
    """Get recent sessions for dashboard display"""
    
    try:
        where_clause = ""
        if failed_only:
            where_clause = "WHERE success_score < 0.7"
        
        query = text(f"""
            SELECT 
                id,
                started_at,
                ended_at,
                duration_seconds,
                total_interactions,
                primary_intent,
                intent_confidence,
                workflow_completed,
                drop_off_step,
                total_tokens,
                avg_response_time_ms,
                errors_count,
                success_score
            FROM session_summaries
            {where_clause}
            ORDER BY started_at DESC
            LIMIT :limit
        """)
        
        results = db.execute(query, {'limit': limit}).fetchall()
        
        sessions = []
        for row in results:
            session = {
                "id": row.id,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "ended_at": row.ended_at.isoformat() if row.ended_at else None,
                "duration_seconds": row.duration_seconds,
                "total_interactions": row.total_interactions,
                "primary_intent": row.primary_intent,
                "intent_confidence": row.intent_confidence,
                "workflow_completed": row.workflow_completed,
                "drop_off_step": row.drop_off_step,
                "total_tokens": row.total_tokens,
                "avg_response_time_ms": row.avg_response_time_ms,
                "errors_count": row.errors_count,
                "success_score": row.success_score
            }
            sessions.append(session)
        
        return {
            "sessions": sessions,
            "total_count": len(sessions),
            "failed_only": failed_only
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get recent sessions: {str(e)}"
        )


@analytics_router.get("/quality-stats")
async def get_quality_stats(
    hours_back: int = Query(24, description="Hours back to analyze"),
    db: Session = Depends(get_db)
):
    """Get overall quality statistics"""
    
    try:
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        
        query = text("""
            SELECT 
                AVG(overall_score) as avg_score,
                COUNT(CASE WHEN overall_score >= 0.7 THEN 1 END)::FLOAT / COUNT(*)::FLOAT as pass_rate,
                COUNT(*) as total_evaluations
            FROM eval_results
            WHERE evaluated_at >= :cutoff_time
        """)
        
        result = db.execute(query, {'cutoff_time': cutoff_time}).fetchone()
        
        if result:
            return {
                "avg_score": round(result.avg_score, 3) if result.avg_score else 0,
                "pass_rate": round(result.pass_rate, 3) if result.pass_rate else 0,
                "total_evaluations": result.total_evaluations
            }
        else:
            return {
                "avg_score": 0,
                "pass_rate": 0,
                "total_evaluations": 0
            }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get quality stats: {str(e)}"
        )


@analytics_router.get("/agent-workflow-analysis/{intent}")
async def get_agent_workflow_analysis(
    intent: str,
    hours_back: int = Query(168, description="Hours back to analyze"),
    db: Session = Depends(get_db)
):
    """
    **Dynamic Agent Workflow Analysis**
    
    Analyzes the actual workflow steps for a specific agent intent,
    generating dynamic flowcharts based on real session data.
    """
    
    try:
        # Get workflow steps for the specific intent
        query = text("""
            SELECT 
                al.workflow_step,
                COUNT(*) as total_sessions,
                COUNT(CASE WHEN NOT al.error_occurred THEN 1 END) as success_count,
                AVG(al.response_time_ms) as avg_response_time,
                0.75 as avg_quality_score,
                COUNT(CASE WHEN NOT al.error_occurred THEN 1 END) as passed_count,
                GROUP_CONCAT(DISTINCT al.tool_calls) as tools_used,
                COUNT(CASE WHEN ss.drop_off_step = al.workflow_step THEN 1 END) as dropoff_count
            FROM agent_logs al
            LEFT JOIN session_summaries ss ON al.session_id = ss.id
            WHERE al.intent = :intent 
            AND al.timestamp >= datetime('now', '-' || :hours_back || ' hours')
            AND al.workflow_step IS NOT NULL
            GROUP BY al.workflow_step
            ORDER BY al.workflow_step
        """)
        
        result = db.execute(query, {'intent': intent, 'hours_back': hours_back}).fetchall()
        
        if not result:
            return {
                "intent": intent,
                "workflow_steps": [],
                "flowchart_nodes": [],
                "success_path": [],
                "failure_points": [],
                "message": "No workflow data found for this intent"
            }
        
        # Process workflow steps
        workflow_steps = []
        flowchart_nodes = []
        failure_points = []
        
        for row in result:
            step_data = {
                "step": row.workflow_step,
                "total_sessions": row.total_sessions,
                "success_count": row.success_count,
                "success_rate": round(row.success_count / row.total_sessions, 3) if row.total_sessions > 0 else 0,
                "avg_response_time": round(row.avg_response_time, 1) if row.avg_response_time else 0,
                "avg_quality_score": round(row.avg_quality_score, 3) if row.avg_quality_score else 0,
                "passed_count": row.passed_count or 0,
                "tools_used": row.tools_used.split(',') if row.tools_used else [],
                "dropoff_count": row.dropoff_count
            }
            workflow_steps.append(step_data)
            
            # Create flowchart node
            success_rate = step_data["success_rate"]
            node_color = "green" if success_rate >= 0.8 else "orange" if success_rate >= 0.6 else "red"
            
            # Determine step name based on common patterns
            step_name = _get_step_name(row.workflow_step, step_data["tools_used"])
            
            flowchart_nodes.append({
                "id": f"step_{row.workflow_step}",
                "name": step_name,
                "step_number": row.workflow_step,
                "success_rate": success_rate,
                "color": node_color,
                "sessions": row.total_sessions,
                "tools": step_data["tools_used"][:3]  # Top 3 tools
            })
            
            # Track failure points
            if success_rate < 0.7 and row.total_sessions >= 5:
                failure_points.append({
                    "step": row.workflow_step,
                    "step_name": step_name,
                    "success_rate": success_rate,
                    "dropoff_count": row.dropoff_count,
                    "impact": "high" if success_rate < 0.5 else "medium"
                })
        
        # Generate success path (steps with >80% success rate)
        success_path = [step["step"] for step in workflow_steps if step["success_rate"] >= 0.8]
        
        return {
            "intent": intent,
            "hours_analyzed": hours_back,
            "workflow_steps": workflow_steps,
            "flowchart_nodes": flowchart_nodes,
            "success_path": success_path,
            "failure_points": failure_points,
            "total_unique_steps": len(workflow_steps),
            "overall_success_rate": round(sum(step["success_rate"] for step in workflow_steps) / len(workflow_steps), 3) if workflow_steps else 0,
            "flowchart_mermaid": _generate_mermaid_flowchart(flowchart_nodes, failure_points)
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get agent workflow analysis: {str(e)}"
        )


@analytics_router.get("/all-agent-workflows") 
async def get_all_agent_workflows(
    hours_back: int = Query(168, description="Hours back to analyze"),
    db: Session = Depends(get_db)
):
    """
    **All Agent Workflows Overview**
    
    Returns workflow analysis for all agent intents, 
    showing the diversity of agent execution paths.
    """
    
    try:
        # Get all intents with their workflow patterns
        query = text("""
            SELECT DISTINCT intent FROM agent_logs 
            WHERE intent IS NOT NULL 
            AND timestamp >= datetime('now', '-' || :hours_back || ' hours')
            ORDER BY intent
        """)
        
        intents = db.execute(query, {'hours_back': hours_back}).fetchall()
        
        workflows = []
        for intent_row in intents:
            intent = intent_row.intent
            
            # Get step count and complexity for each intent
            step_query = text("""
                SELECT 
                    COUNT(DISTINCT workflow_step) as unique_steps,
                    MAX(workflow_step) as max_step,
                    COUNT(DISTINCT session_id) as total_sessions,
                    AVG(CASE WHEN NOT error_occurred THEN 1.0 ELSE 0.0 END) as avg_success_rate
                FROM agent_logs
                WHERE intent = :intent 
                AND timestamp >= datetime('now', '-' || :hours_back || ' hours')
                AND workflow_step IS NOT NULL
            """)
            
            result = db.execute(step_query, {'intent': intent, 'hours_back': hours_back}).fetchone()
            
            if result and result.total_sessions >= 5:  # Only include intents with sufficient data
                workflows.append({
                    "intent": intent,
                    "unique_steps": result.unique_steps,
                    "max_step": result.max_step,
                    "total_sessions": result.total_sessions,
                    "avg_success_rate": round(result.avg_success_rate, 3) if result.avg_success_rate else 0,
                    "complexity": "high" if result.unique_steps > 5 else "medium" if result.unique_steps > 3 else "low",
                    "workflow_health": "good" if result.avg_success_rate >= 0.8 else "fair" if result.avg_success_rate >= 0.6 else "poor"
                })
        
        return {
            "workflows": workflows,
            "total_agent_types": len(workflows),
            "hours_analyzed": hours_back,
            "summary": {
                "most_complex": max(workflows, key=lambda x: x["unique_steps"])["intent"] if workflows else None,
                "highest_performing": max(workflows, key=lambda x: x["avg_success_rate"])["intent"] if workflows else None,
                "needs_attention": [w["intent"] for w in workflows if w["avg_success_rate"] < 0.6]
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get all agent workflows: {str(e)}"
        )


def _get_step_name(step_number: int, tools_used: List[str]) -> str:
    """Generate descriptive step names based on step number and tools"""
    
    # Common step patterns
    step_names = {
        1: "Initial Contact",
        2: "Intent Recognition", 
        3: "Context Gathering",
        4: "Tool Execution",
        5: "Response Generation",
        6: "Quality Check",
        7: "Follow-up",
        8: "Resolution"
    }
    
    base_name = step_names.get(step_number, f"Step {step_number}")
    
    # Enhance with tool information
    if tools_used:
        primary_tool = tools_used[0].replace('["', '').replace('"]', '').replace('"', '')
        if 'billing' in primary_tool.lower():
            return f"{base_name} (Billing)"
        elif 'payment' in primary_tool.lower():
            return f"{base_name} (Payment)"
        elif 'auth' in primary_tool.lower():
            return f"{base_name} (Auth)"
        elif 'api' in primary_tool.lower():
            return f"{base_name} (API)"
    
    return base_name


def _generate_mermaid_flowchart(nodes: List[Dict], failure_points: List[Dict]) -> str:
    """Generate Mermaid flowchart syntax for the workflow"""
    
    if not nodes:
        return "flowchart TD\n    A[No workflow data available]"
    
    mermaid = "flowchart TD\n"
    
    # Add nodes
    for i, node in enumerate(nodes):
        node_id = node["id"]
        name = node["name"]
        success_rate = node["success_rate"]
        
        # Node shape based on success rate
        if success_rate >= 0.8:
            shape = f'    {node_id}["{name}\\n{success_rate:.1%} success"]'
        elif success_rate >= 0.6:
            shape = f'    {node_id}{{"{name}\\n{success_rate:.1%} success"}}'
        else:
            shape = f'    {node_id}["{name}\\n{success_rate:.1%} success"]'
        
        mermaid += shape + "\n"
        
        # Add connections
        if i < len(nodes) - 1:
            next_node = nodes[i + 1]["id"]
            if success_rate >= 0.8:
                mermaid += f"    {node_id} --> {next_node}\n"
            else:
                mermaid += f"    {node_id} -->|❌ {int((1-success_rate)*100)}% fail| {next_node}\n"
    
    # Add failure paths
    failure_node_ids = [f"step_{fp['step']}" for fp in failure_points]
    if failure_node_ids:
        mermaid += "    FAIL[❌ Session Failed]\n"
        for fail_id in failure_node_ids:
            mermaid += f"    {fail_id} -->|Failure| FAIL\n"
    
    # Add success end
    if nodes:
        last_node = nodes[-1]["id"]
        mermaid += "    SUCCESS[✅ Success]\n"
        mermaid += f"    {last_node} --> SUCCESS\n"
    
    # Add styling
    mermaid += "\n    classDef success fill:#90EE90\n"
    mermaid += "    classDef warning fill:#FFB347\n" 
    mermaid += "    classDef failure fill:#FFB6C1\n"
    mermaid += "    classDef endpoint fill:#87CEEB\n"
    
    # Apply classes
    for node in nodes:
        if node["success_rate"] >= 0.8:
            mermaid += f"    class {node['id']} success\n"
        elif node["success_rate"] >= 0.6:
            mermaid += f"    class {node['id']} warning\n"
        else:
            mermaid += f"    class {node['id']} failure\n"
    
    mermaid += "    class SUCCESS success\n"
    mermaid += "    class FAIL failure\n"
    
    return mermaid