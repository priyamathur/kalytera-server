"""
API monitoring and usage tracking endpoints for Kalytera
Provides real-time monitoring of token usage and security status
"""

from fastapi import APIRouter
from typing import Dict, Any
from datetime import datetime

from api.security import get_usage_stats, check_api_health

monitoring_router = APIRouter(prefix="/api/security", tags=["monitoring"])


@monitoring_router.get("/usage")
async def get_token_usage():
    """
    Get current token usage statistics and rate limits
    Endpoint for monitoring token consumption and cost control
    """
    stats = get_usage_stats()
    
    return {
        "timestamp": datetime.now().isoformat(),
        "usage_stats": stats,
        "alerts": _generate_usage_alerts(stats),
        "recommendations": _generate_recommendations(stats)
    }


@monitoring_router.get("/health")
async def get_security_health():
    """
    Get comprehensive security and API health status
    """
    health = check_api_health()
    
    return {
        "timestamp": datetime.now().isoformat(),
        "security_status": "healthy" if health["api_key_available"] and health["rate_limit_ok"] else "degraded",
        "details": health,
        "system_info": {
            "secure_key_manager": "active",
            "token_optimization": "enabled", 
            "cost_controls": "enforced",
            "fallback_systems": "available"
        }
    }


@monitoring_router.get("/cost-estimate")
async def get_cost_estimate():
    """
    Estimate current and projected API costs based on usage
    """
    stats = get_usage_stats()
    
    # Claude Haiku pricing: ~$0.25 per 1M input tokens, ~$1.25 per 1M output tokens
    # Conservative estimate assuming 50/50 split
    avg_cost_per_1k_tokens = 0.75 / 1000  # $0.75 per 1M tokens average
    
    daily_usage = stats.get("daily_usage", {}).get("total_tokens", 0)
    daily_cost_estimate = daily_usage * avg_cost_per_1k_tokens / 1000
    
    monthly_projection = daily_cost_estimate * 30
    
    return {
        "timestamp": datetime.now().isoformat(),
        "cost_estimates": {
            "today_usd": round(daily_cost_estimate, 4),
            "monthly_projection_usd": round(monthly_projection, 2),
            "tokens_used_today": daily_usage,
            "tokens_remaining_today": stats.get("daily_limits", {}).get("total_tokens", 100000) - daily_usage
        },
        "optimization_status": {
            "model_used": "claude-3-haiku-20240307",
            "cost_tier": "optimized_low_cost",
            "token_limits": "enforced",
            "fallback_enabled": True
        }
    }


def _generate_usage_alerts(stats: Dict[str, Any]) -> list:
    """Generate alerts based on usage statistics"""
    alerts = []
    
    utilization = stats.get("utilization_pct", 0)
    
    if utilization > 90:
        alerts.append({
            "level": "critical",
            "message": f"Daily token limit nearly exhausted ({utilization}%)",
            "action": "API calls will be throttled soon"
        })
    elif utilization > 75:
        alerts.append({
            "level": "warning", 
            "message": f"High token usage detected ({utilization}%)",
            "action": "Consider reducing evaluation frequency"
        })
    
    hourly_requests = stats.get("requests_last_hour", 0)
    hourly_limit = stats.get("daily_limits", {}).get("requests_per_hour", 100)
    
    if hourly_requests > hourly_limit * 0.9:
        alerts.append({
            "level": "warning",
            "message": f"Approaching hourly rate limit ({hourly_requests}/{hourly_limit})",
            "action": "Requests may be throttled"
        })
    
    return alerts


def _generate_recommendations(stats: Dict[str, Any]) -> list:
    """Generate optimization recommendations based on usage patterns"""
    recommendations = []
    
    utilization = stats.get("utilization_pct", 0)
    
    if utilization < 25:
        recommendations.append({
            "type": "efficiency",
            "message": "Low token usage detected - you could increase evaluation frequency",
            "benefit": "More comprehensive agent monitoring"
        })
    elif utilization > 80:
        recommendations.append({
            "type": "cost_optimization", 
            "message": "High usage - consider reducing batch sizes or evaluation frequency",
            "benefit": "Lower API costs while maintaining coverage"
        })
    
    pattern_tokens = stats.get("daily_usage", {}).get("pattern_analysis_tokens", 0)
    eval_tokens = stats.get("daily_usage", {}).get("evaluation_tokens", 0)
    
    if pattern_tokens > eval_tokens * 0.5:
        recommendations.append({
            "type": "optimization",
            "message": "Pattern analysis using significant tokens - consider keyword-only mode",
            "benefit": "Reduce costs while maintaining pattern detection"
        })
    
    return recommendations