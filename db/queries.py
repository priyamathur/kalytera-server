"""
Database query functions for analytics engine.
All functions use SQLAlchemy ORM (no raw SQL) and return pandas DataFrames.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List
import pandas as pd  # type: ignore[import-untyped]
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_, Integer

from .models import AgentLog, SessionSummary, EvalResult


def get_session_volume(db: Session, agent_id: str, days: int) -> pd.DataFrame:
    """
    Get session volume analytics over time.
    
    Args:
        db: Database session
        agent_id: Agent identifier
        days: Number of days to look back
        
    Returns:
        DataFrame with columns: date, session_count, interaction_count
    """
    start_date = datetime.utcnow() - timedelta(days=days)
    
    # Query session summaries for the agent in the date range
    query = db.query(
        func.date(SessionSummary.started_at).label('date'),
        func.count(SessionSummary.id).label('session_count'),
        func.sum(SessionSummary.total_interactions).label('interaction_count')
    ).filter(
        and_(
            SessionSummary.started_at >= start_date,
            # Note: agent_id filtering would need to be added to SessionSummary model
            # For now, using all sessions as the model doesn't have agent_id
        )
    ).group_by(
        func.date(SessionSummary.started_at)
    ).order_by(
        func.date(SessionSummary.started_at)
    )
    
    results = query.all()
    
    return pd.DataFrame([
        {
            'date': result.date,
            'session_count': result.session_count or 0,
            'interaction_count': result.interaction_count or 0
        }
        for result in results
    ])


def get_top_intents(db: Session, agent_id: str, days: int) -> pd.DataFrame:
    """
    Get top intents by frequency and success rate.
    
    Args:
        db: Database session
        agent_id: Agent identifier
        days: Number of days to look back
        
    Returns:
        DataFrame with columns: intent, count, success_rate, avg_quality_score
    """
    start_date = datetime.utcnow() - timedelta(days=days)
    
    # Join AgentLog with EvalResult to get quality scores
    query = db.query(
        AgentLog.intent,
        func.count(AgentLog.id).label('count'),
        func.avg(EvalResult.overall_score).label('avg_quality_score')
    ).outerjoin(
        EvalResult, AgentLog.id == EvalResult.agent_log_id
    ).filter(
        and_(
            AgentLog.timestamp >= start_date,
            AgentLog.intent.is_not(None)
            # Note: agent_id filtering would need to be added to AgentLog model
        )
    ).group_by(
        AgentLog.intent
    ).order_by(
        desc('count')
    )
    
    results = query.all()
    
    # Calculate success rate from SessionSummary
    intent_success_rates = {}
    for intent in [r.intent for r in results]:
        success_query = db.query(
            func.avg(SessionSummary.success_score).label('success_rate')
        ).filter(
            and_(
                SessionSummary.primary_intent == intent,
                SessionSummary.started_at >= start_date
            )
        )
        success_result = success_query.first()
        intent_success_rates[intent] = success_result.success_rate if success_result and success_result.success_rate else 0.0
    
    return pd.DataFrame([
        {
            'intent': result.intent,
            'count': result.count,
            'success_rate': intent_success_rates.get(result.intent, 0.0),
            'avg_quality_score': float(result.avg_quality_score) if result.avg_quality_score else 0.0
        }
        for result in results
    ])


def get_top_workflow_paths(db: Session, agent_id: str, days: int) -> pd.DataFrame:
    """
    Get most common workflow paths and completion rates.
    
    Args:
        db: Database session
        agent_id: Agent identifier
        days: Number of days to look back
        
    Returns:
        DataFrame with columns: workflow_path, session_count, completion_rate, avg_duration
    """
    start_date = datetime.utcnow() - timedelta(days=days)
    
    # Get workflow paths by analyzing session summaries and their steps
    query = db.query(
        SessionSummary.primary_intent,
        func.count(SessionSummary.id).label('session_count'),
        func.avg(func.cast(SessionSummary.workflow_completed, Integer)).label('completion_rate'),
        func.avg(SessionSummary.duration_seconds).label('avg_duration')
    ).filter(
        and_(
            SessionSummary.started_at >= start_date,
            SessionSummary.primary_intent.is_not(None)
        )
    ).group_by(
        SessionSummary.primary_intent
    ).order_by(
        desc('session_count')
    )
    
    results = query.all()
    
    return pd.DataFrame([
        {
            'workflow_path': result.primary_intent,
            'session_count': result.session_count,
            'completion_rate': float(result.completion_rate) if result.completion_rate else 0.0,
            'avg_duration': float(result.avg_duration) if result.avg_duration else 0.0
        }
        for result in results
    ])


def get_dropoff_by_step(db: Session, agent_id: str, days: int) -> pd.DataFrame:
    """
    Get dropoff analysis by workflow step.
    
    Args:
        db: Database session
        agent_id: Agent identifier
        days: Number of days to look back
        
    Returns:
        DataFrame with columns: workflow_step, sessions_reached, dropoff_count, dropoff_rate
    """
    start_date = datetime.utcnow() - timedelta(days=days)
    
    # Get step-level analytics from AgentLog
    step_reaches = db.query(
        AgentLog.workflow_step,
        func.count(func.distinct(AgentLog.session_id)).label('sessions_reached')
    ).filter(
        AgentLog.timestamp >= start_date
    ).group_by(
        AgentLog.workflow_step
    ).all()
    
    # Get dropoff counts from SessionSummary
    dropoff_counts = db.query(
        SessionSummary.drop_off_step,
        func.count(SessionSummary.id).label('dropoff_count')
    ).filter(
        and_(
            SessionSummary.started_at >= start_date,
            SessionSummary.drop_off_step.is_not(None)
        )
    ).group_by(
        SessionSummary.drop_off_step
    ).all()
    
    # Combine data
    step_data = {}
    for reach in step_reaches:
        step_data[reach.workflow_step] = {'sessions_reached': reach.sessions_reached, 'dropoff_count': 0}
    
    for dropoff in dropoff_counts:
        if dropoff.drop_off_step in step_data:
            step_data[dropoff.drop_off_step]['dropoff_count'] = dropoff.dropoff_count
        else:
            step_data[dropoff.drop_off_step] = {'sessions_reached': 0, 'dropoff_count': dropoff.dropoff_count}
    
    return pd.DataFrame([
        {
            'workflow_step': step,
            'sessions_reached': data['sessions_reached'],
            'dropoff_count': data['dropoff_count'],
            'dropoff_rate': data['dropoff_count'] / data['sessions_reached'] if data['sessions_reached'] > 0 else 0.0
        }
        for step, data in sorted(step_data.items())
    ])


def get_tool_usage(db: Session, agent_id: str, days: int) -> pd.DataFrame:
    """
    Get tool usage analytics and success rates.
    
    Args:
        db: Database session
        agent_id: Agent identifier
        days: Number of days to look back
        
    Returns:
        DataFrame with columns: tool_name, usage_count, success_rate, avg_quality_score
    """
    start_date = datetime.utcnow() - timedelta(days=days)
    
    # Get tool usage from AgentLog where tool_calls is not None
    logs_with_tools = db.query(AgentLog).filter(
        and_(
            AgentLog.timestamp >= start_date,
            AgentLog.tool_calls.is_not(None),
            AgentLog.tool_calls != ''
        )
    ).all()
    
    # Parse tool_calls (assuming JSON string format) and aggregate
    tool_stats: Dict[str, Dict[str, Any]] = {}
    
    for log in logs_with_tools:
        if log.tool_calls:
            # Simple parsing - assumes tool names are in the tool_calls string
            # In production, this would parse JSON properly
            tools_used = [t.strip() for t in log.tool_calls.split(',') if t.strip()]
            
            for tool in tools_used:
                if tool not in tool_stats:
                    tool_stats[tool] = {'usage_count': 0, 'error_count': 0, 'log_ids': []}
                
                tool_stats[tool]['usage_count'] = tool_stats[tool]['usage_count'] + 1
                tool_stats[tool]['log_ids'].append(log.id)
                
                if log.error_occurred:
                    tool_stats[tool]['error_count'] = tool_stats[tool]['error_count'] + 1
    
    # Get quality scores for tool usage
    result_data = []
    for tool_name, stats in tool_stats.items():
        # Get average quality score for this tool's usage
        quality_query = db.query(
            func.avg(EvalResult.overall_score).label('avg_quality_score')
        ).filter(
            EvalResult.agent_log_id.in_(stats['log_ids'])
        )
        
        quality_result = quality_query.first()
        avg_quality = float(quality_result.avg_quality_score) if quality_result and quality_result.avg_quality_score else 0.0
        
        usage_count = int(stats['usage_count'])
        error_count = int(stats['error_count'])
        success_rate = 1.0 - (error_count / usage_count) if usage_count > 0 else 0.0
        
        result_data.append({
            'tool_name': tool_name,
            'usage_count': usage_count,
            'success_rate': success_rate,
            'avg_quality_score': avg_quality
        })
    
    return pd.DataFrame(result_data).sort_values('usage_count', ascending=False)


def get_quality_by_intent(db: Session, agent_id: str, days: int) -> pd.DataFrame:
    """
    Get quality metrics broken down by intent type.
    
    Args:
        db: Database session
        agent_id: Agent identifier
        days: Number of days to look back
        
    Returns:
        DataFrame with columns: intent, avg_accuracy, avg_relevance, avg_helpfulness, 
                               avg_goal_alignment, overall_quality, evaluation_count
    """
    start_date = datetime.utcnow() - timedelta(days=days)
    
    # Join AgentLog with EvalResult to get detailed quality metrics by intent
    query = db.query(
        AgentLog.intent,
        func.avg(EvalResult.accuracy_score).label('avg_accuracy'),
        func.avg(EvalResult.relevance_score).label('avg_relevance'),
        func.avg(EvalResult.helpfulness_score).label('avg_helpfulness'),
        func.avg(EvalResult.goal_alignment_score).label('avg_goal_alignment'),
        func.avg(EvalResult.overall_score).label('overall_quality'),
        func.count(EvalResult.id).label('evaluation_count')
    ).join(
        EvalResult, AgentLog.id == EvalResult.agent_log_id
    ).filter(
        and_(
            AgentLog.timestamp >= start_date,
            AgentLog.intent.is_not(None)
        )
    ).group_by(
        AgentLog.intent
    ).order_by(
        desc('overall_quality')
    )
    
    results = query.all()
    
    return pd.DataFrame([
        {
            'intent': result.intent,
            'avg_accuracy': float(result.avg_accuracy) if result.avg_accuracy else 0.0,
            'avg_relevance': float(result.avg_relevance) if result.avg_relevance else 0.0,
            'avg_helpfulness': float(result.avg_helpfulness) if result.avg_helpfulness else 0.0,
            'avg_goal_alignment': float(result.avg_goal_alignment) if result.avg_goal_alignment else 0.0,
            'overall_quality': float(result.overall_quality) if result.overall_quality else 0.0,
            'evaluation_count': result.evaluation_count
        }
        for result in results
    ])