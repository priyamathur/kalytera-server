"""
Analytics API endpoints for AgentIQ
6 core endpoints providing actionable insights from agent interaction data
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime

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