"""
Usage Analytics Engine for AgentIQ
Transforms raw session data into actionable insights for agent performance optimization
"""

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, text, and_, or_
from dataclasses import dataclass
import json

from db.models import SessionSummary, AgentLog


@dataclass
class SessionVolumePoint:
    """Data point for session volume over time"""
    timestamp: datetime
    session_count: int
    interaction_count: int
    avg_duration_seconds: float
    completion_rate: float


@dataclass
class IntentAnalytics:
    """Analytics for a specific intent type"""
    intent: str
    session_count: int
    completion_rate: float
    avg_steps: float
    avg_success_score: float
    total_interactions: int
    avg_duration_seconds: float
    error_rate: float


@dataclass
class WorkflowPath:
    """Common workflow path with analytics"""
    path: List[str]
    frequency: int
    completion_rate: float
    avg_duration: float
    intent_distribution: Dict[str, int]


@dataclass
class DropoffInsight:
    """Drop-off analysis insight"""
    step: int
    dropoff_count: int
    dropoff_rate: float
    intent_breakdown: Dict[str, int]
    common_reasons: List[str]
    impact_score: float  # How impactful fixing this would be


@dataclass
class ToolUsageAnalytics:
    """Tool usage and failure analytics"""
    tool_name: str
    usage_count: int
    success_rate: float
    avg_response_time_ms: float
    failure_modes: List[Dict[str, Any]]
    intent_usage: Dict[str, int]


@dataclass
class QualityByIntent:
    """Quality metrics broken down by intent"""
    intent: str
    pass_rate: float
    avg_quality_score: float
    sample_size: int
    benchmark_comparison: str  # "above", "below", "at" benchmark
    top_failure_patterns: List[str]


class UsageAnalyticsEngine:
    """Core analytics engine for processing usage patterns"""
    
    def __init__(self, db_session: Session):
        self.db = db_session
    
    def get_session_volume_over_time(
        self, 
        hours_back: int = 168,  # Default 1 week
        granularity: str = "hour"  # "hour", "day", "week"
    ) -> List[SessionVolumePoint]:
        """
        Analyze session volume trends over time
        Critical for understanding usage patterns and peak times
        """
        
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours_back)
        
        # Define time grouping based on granularity (PostgreSQL compatible)
        if granularity == "hour":
            time_format = "%Y-%m-%d %H:00:00"
            time_group = "DATE_TRUNC('hour', started_at)"
        elif granularity == "day":
            time_format = "%Y-%m-%d 00:00:00"
            time_group = "DATE_TRUNC('day', started_at)"
        else:  # week
            time_format = "%Y-%m-%d"
            time_group = "DATE_TRUNC('week', started_at)"
        
        # Query session volume by time period
        query = text(f"""
            SELECT 
                {time_group} as time_bucket,
                COUNT(*) as session_count,
                SUM(total_interactions) as interaction_count,
                AVG(duration_seconds) as avg_duration,
                AVG(CASE WHEN workflow_completed = true THEN 1.0 ELSE 0.0 END) as completion_rate
            FROM session_summaries 
            WHERE started_at >= :start_time AND started_at <= :end_time
            GROUP BY {time_group}
            ORDER BY time_bucket
        """)
        
        result = self.db.execute(query, {
            'start_time': start_time,
            'end_time': end_time
        }).fetchall()
        
        volume_points = []
        for row in result:
            # PostgreSQL DATE_TRUNC returns timestamp objects directly
            timestamp = row[0] if isinstance(row[0], datetime) else datetime.strptime(str(row[0]), time_format)
            volume_points.append(SessionVolumePoint(
                timestamp=timestamp,
                session_count=row[1],
                interaction_count=row[2] or 0,
                avg_duration_seconds=row[3] or 0.0,
                completion_rate=row[4] or 0.0
            ))
        
        return volume_points
    
    def get_top_intents_analytics(self, limit: int = 10) -> List[IntentAnalytics]:
        """
        Analyze intent performance - completion rates, steps, success scores
        Essential for understanding which user needs the agent handles well/poorly
        """
        
        query = text("""
            SELECT 
                primary_intent,
                COUNT(*) as session_count,
                AVG(CASE WHEN workflow_completed = true THEN 1.0 ELSE 0.0 END) as completion_rate,
                AVG(total_interactions) as avg_steps,
                AVG(success_score) as avg_success_score,
                SUM(total_interactions) as total_interactions,
                AVG(duration_seconds) as avg_duration,
                AVG(CASE WHEN errors_count > 0 THEN 1.0 ELSE 0.0 END) as error_rate
            FROM session_summaries 
            WHERE primary_intent IS NOT NULL
            GROUP BY primary_intent
            ORDER BY session_count DESC
            LIMIT :limit
        """)
        
        result = self.db.execute(query, {'limit': limit}).fetchall()
        
        intent_analytics = []
        for row in result:
            intent_analytics.append(IntentAnalytics(
                intent=row[0],
                session_count=row[1],
                completion_rate=float(row[2]) if row[2] else 0.0,
                avg_steps=float(row[3]) if row[3] else 0.0,
                avg_success_score=float(row[4]) if row[4] else 0.0,
                total_interactions=int(row[5]) if row[5] else 0,
                avg_duration_seconds=float(row[6]) if row[6] else 0.0,
                error_rate=float(row[7]) if row[7] else 0.0
            ))
        
        return intent_analytics
    
    def get_workflow_paths(
        self, 
        intent_filter: Optional[str] = None,
        min_frequency: int = 5
    ) -> List[WorkflowPath]:
        """
        Identify most common workflow paths through conversations
        Shows how users actually navigate vs intended flows
        """
        
        # Build session query with optional intent filter
        session_filter = ""
        params = {'min_frequency': min_frequency}
        
        if intent_filter:
            session_filter = "AND ss.primary_intent = :intent_filter"
            params['intent_filter'] = intent_filter
        
        # Get workflow sequences for each session
        query = text(f"""
            SELECT 
                al.session_id,
                ss.primary_intent,
                ss.workflow_completed,
                ss.duration_seconds,
                STRING_AGG(
                    CASE 
                        WHEN al.tool_calls IS NOT NULL AND al.tool_calls != '[]' THEN 'tool_call'
                        WHEN al.error_occurred = true THEN 'error'
                        WHEN al.workflow_step = 1 THEN 'initial_request'
                        WHEN al.workflow_step <= 2 THEN 'clarification'
                        WHEN al.workflow_step <= 4 THEN 'processing'
                        ELSE 'resolution'
                    END, ' -> '
                    ORDER BY al.workflow_step
                ) as workflow_path
            FROM agent_logs al
            JOIN session_summaries ss ON al.session_id = ss.id
            WHERE 1=1 {session_filter}
            GROUP BY al.session_id, ss.primary_intent, ss.workflow_completed, ss.duration_seconds
        """)
        
        result = self.db.execute(query, params).fetchall()
        
        # Aggregate workflow paths
        path_analytics = {}
        
        for row in result:
            session_id, intent, completed, duration, path = row
            path_key = path or "unknown_path"
            
            if path_key not in path_analytics:
                path_analytics[path_key] = {
                    'frequency': 0,
                    'completions': 0,
                    'total_duration': 0,
                    'intent_distribution': {}
                }
            
            path_analytics[path_key]['frequency'] += 1
            path_analytics[path_key]['completions'] += (1 if completed else 0)
            path_analytics[path_key]['total_duration'] += (duration or 0)
            
            intent_key = intent or 'unknown'
            if intent_key not in path_analytics[path_key]['intent_distribution']:
                path_analytics[path_key]['intent_distribution'][intent_key] = 0
            path_analytics[path_key]['intent_distribution'][intent_key] += 1
        
        # Convert to WorkflowPath objects
        workflow_paths = []
        for path_str, analytics in path_analytics.items():
            if analytics['frequency'] >= min_frequency:
                workflow_paths.append(WorkflowPath(
                    path=path_str.split(' -> '),
                    frequency=analytics['frequency'],
                    completion_rate=analytics['completions'] / analytics['frequency'],
                    avg_duration=analytics['total_duration'] / analytics['frequency'],
                    intent_distribution=analytics['intent_distribution']
                ))
        
        # Sort by frequency
        workflow_paths.sort(key=lambda x: x.frequency, reverse=True)
        
        return workflow_paths
    
    def get_dropoff_analysis(self) -> List[DropoffInsight]:
        """
        Analyze where users drop off in conversations
        MOST IMPACTFUL SINGLE INSIGHT - shows exactly where to focus improvements
        """
        
        # Query drop-off patterns by step
        query = text("""
            SELECT 
                ss.drop_off_step,
                COUNT(*) as dropoff_count,
                ss.primary_intent,
                STRING_AGG(al.error_message, ',') as error_messages
            FROM session_summaries ss
            LEFT JOIN agent_logs al ON ss.id = al.session_id 
                AND al.workflow_step = ss.drop_off_step
            WHERE ss.drop_off_step IS NOT NULL
            GROUP BY ss.drop_off_step, ss.primary_intent
            ORDER BY dropoff_count DESC
        """)
        
        result = self.db.execute(query).fetchall()
        
        # Calculate total sessions for drop-off rates
        total_sessions = self.db.execute(text("SELECT COUNT(*) FROM session_summaries")).fetchone()[0]
        
        # Aggregate by step
        step_analytics = {}
        
        for row in result:
            step, count, intent, error_messages = row
            
            if step not in step_analytics:
                step_analytics[step] = {
                    'dropoff_count': 0,
                    'intent_breakdown': {},
                    'error_messages': []
                }
            
            step_analytics[step]['dropoff_count'] += count
            
            intent_key = intent or 'unknown'
            if intent_key not in step_analytics[step]['intent_breakdown']:
                step_analytics[step]['intent_breakdown'][intent_key] = 0
            step_analytics[step]['intent_breakdown'][intent_key] += count
            
            if error_messages:
                step_analytics[step]['error_messages'].extend(
                    [msg for msg in error_messages.split(',') if msg and msg.strip()]
                )
        
        # Convert to DropoffInsight objects with impact scoring
        dropoff_insights = []
        
        for step, analytics in step_analytics.items():
            dropoff_rate = analytics['dropoff_count'] / total_sessions
            
            # Impact score: combines volume and early-stage impact
            # Early steps have higher impact (more sessions affected downstream)
            step_weight = max(1.0, (10 - step) / 10) if step <= 10 else 0.1
            impact_score = dropoff_rate * step_weight * analytics['dropoff_count']
            
            # Extract common failure reasons
            common_reasons = []
            error_freq = {}
            for error_msg in analytics['error_messages']:
                if error_msg and error_msg.strip():
                    error_freq[error_msg] = error_freq.get(error_msg, 0) + 1
            
            # Top 3 most common error messages
            common_reasons = [
                error for error, freq in 
                sorted(error_freq.items(), key=lambda x: x[1], reverse=True)[:3]
            ]
            
            dropoff_insights.append(DropoffInsight(
                step=step,
                dropoff_count=analytics['dropoff_count'],
                dropoff_rate=dropoff_rate,
                intent_breakdown=analytics['intent_breakdown'],
                common_reasons=common_reasons,
                impact_score=impact_score
            ))
        
        # Sort by impact score (most impactful first)
        dropoff_insights.sort(key=lambda x: x.impact_score, reverse=True)
        
        return dropoff_insights
    
    def get_tool_usage_analytics(self) -> List[ToolUsageAnalytics]:
        """
        Analyze tool usage patterns and failure rates
        Critical for understanding which integrations work/fail
        """
        
        # Query tool usage patterns
        query = text("""
            SELECT 
                al.tool_calls,
                al.response_time_ms,
                al.error_occurred,
                al.error_message,
                ss.primary_intent
            FROM agent_logs al
            JOIN session_summaries ss ON al.session_id = ss.id
            WHERE al.tool_calls IS NOT NULL 
            AND al.tool_calls != '[]' 
            AND al.tool_calls != 'null'
        """)
        
        result = self.db.execute(query).fetchall()
        
        # Parse tool usage data
        tool_analytics = {}
        
        for row in result:
            tool_calls_str, response_time, error_occurred, error_message, intent = row
            
            try:
                # Parse tool calls (can be JSON array or comma-separated string)
                if tool_calls_str.startswith('['):
                    tools = json.loads(tool_calls_str)
                else:
                    tools = [tool.strip() for tool in tool_calls_str.split(',')]
                
                for tool in tools:
                    if tool and tool != 'null':
                        if tool not in tool_analytics:
                            tool_analytics[tool] = {
                                'usage_count': 0,
                                'success_count': 0,
                                'total_response_time': 0,
                                'failure_modes': [],
                                'intent_usage': {}
                            }
                        
                        tool_analytics[tool]['usage_count'] += 1
                        tool_analytics[tool]['total_response_time'] += (response_time or 1000)
                        
                        if not error_occurred:
                            tool_analytics[tool]['success_count'] += 1
                        else:
                            tool_analytics[tool]['failure_modes'].append({
                                'error_message': error_message,
                                'response_time_ms': response_time,
                                'intent': intent
                            })
                        
                        # Track intent usage
                        intent_key = intent or 'unknown'
                        if intent_key not in tool_analytics[tool]['intent_usage']:
                            tool_analytics[tool]['intent_usage'][intent_key] = 0
                        tool_analytics[tool]['intent_usage'][intent_key] += 1
                        
            except (json.JSONDecodeError, AttributeError):
                # Skip malformed tool calls data
                continue
        
        # Convert to ToolUsageAnalytics objects
        tool_usage_list = []
        
        for tool, analytics in tool_analytics.items():
            success_rate = analytics['success_count'] / analytics['usage_count']
            avg_response_time = analytics['total_response_time'] / analytics['usage_count']
            
            # Group similar failure modes
            failure_mode_groups = {}
            for failure in analytics['failure_modes']:
                error_key = failure['error_message'][:50] if failure['error_message'] else 'unknown_error'
                if error_key not in failure_mode_groups:
                    failure_mode_groups[error_key] = {
                        'count': 0,
                        'sample_error': failure['error_message'],
                        'avg_response_time': 0,
                        'total_response_time': 0
                    }
                
                failure_mode_groups[error_key]['count'] += 1
                failure_mode_groups[error_key]['total_response_time'] += (failure['response_time_ms'] or 0)
                failure_mode_groups[error_key]['avg_response_time'] = (
                    failure_mode_groups[error_key]['total_response_time'] / 
                    failure_mode_groups[error_key]['count']
                )
            
            grouped_failures = [
                {
                    'error_type': error_key,
                    'count': data['count'],
                    'sample_error': data['sample_error'],
                    'avg_response_time_ms': data['avg_response_time']
                }
                for error_key, data in failure_mode_groups.items()
            ]
            
            tool_usage_list.append(ToolUsageAnalytics(
                tool_name=tool,
                usage_count=analytics['usage_count'],
                success_rate=success_rate,
                avg_response_time_ms=avg_response_time,
                failure_modes=grouped_failures,
                intent_usage=analytics['intent_usage']
            ))
        
        # Sort by usage count
        tool_usage_list.sort(key=lambda x: x.usage_count, reverse=True)
        
        return tool_usage_list
    
    def get_quality_by_intent(self) -> List[QualityByIntent]:
        """
        Quality metrics broken down by intent - pass rates and score distributions
        Bridge between usage patterns and loss patterns
        """
        
        # Quality benchmarks (these could be configurable)
        QUALITY_BENCHMARKS = {
            'billing': 0.75,
            'refunds': 0.60,
            'subscriptions': 0.85,
            'account_recovery': 0.70,
            'technical_support': 0.65,
            'general_enquiry': 0.90
        }
        
        # Define "pass" threshold
        PASS_THRESHOLD = 0.7
        
        query = text("""
            SELECT 
                ss.primary_intent,
                COUNT(*) as total_sessions,
                AVG(ss.success_score) as avg_quality_score,
                SUM(CASE WHEN ss.success_score >= :pass_threshold THEN 1 ELSE 0 END) as passed_sessions,
                SUM(CASE WHEN ss.workflow_completed = 0 THEN 1 ELSE 0 END) as failed_completions,
                SUM(ss.errors_count) as total_errors
            FROM session_summaries ss
            WHERE ss.primary_intent IS NOT NULL
            AND ss.success_score IS NOT NULL
            GROUP BY ss.primary_intent
            ORDER BY total_sessions DESC
        """)
        
        result = self.db.execute(query, {'pass_threshold': PASS_THRESHOLD}).fetchall()
        
        quality_analytics = []
        
        for row in result:
            intent, total_sessions, avg_score, passed_sessions, failed_completions, total_errors = row
            
            pass_rate = passed_sessions / total_sessions if total_sessions > 0 else 0.0
            benchmark = QUALITY_BENCHMARKS.get(intent, 0.70)
            
            # Determine benchmark comparison
            if pass_rate >= benchmark * 1.05:  # 5% tolerance
                benchmark_comparison = "above"
            elif pass_rate <= benchmark * 0.95:
                benchmark_comparison = "below"
            else:
                benchmark_comparison = "at"
            
            # Identify top failure patterns for this intent
            failure_patterns = self._get_failure_patterns_for_intent(intent)
            
            quality_analytics.append(QualityByIntent(
                intent=intent,
                pass_rate=pass_rate,
                avg_quality_score=avg_score or 0.0,
                sample_size=total_sessions,
                benchmark_comparison=benchmark_comparison,
                top_failure_patterns=failure_patterns
            ))
        
        return quality_analytics
    
    def _get_failure_patterns_for_intent(self, intent: str, limit: int = 3) -> List[str]:
        """Get top failure patterns for a specific intent"""
        
        query = text("""
            SELECT 
                ss.drop_off_step,
                COUNT(*) as frequency,
                STRING_AGG(DISTINCT al.error_message, ',') as error_messages
            FROM session_summaries ss
            LEFT JOIN agent_logs al ON ss.id = al.session_id
            WHERE ss.primary_intent = :intent 
            AND ss.workflow_completed = 0
            GROUP BY ss.drop_off_step
            ORDER BY frequency DESC
            LIMIT :limit
        """)
        
        result = self.db.execute(query, {'intent': intent, 'limit': limit}).fetchall()
        
        failure_patterns = []
        for row in result:
            step, frequency, error_messages = row
            if step:
                pattern = f"Drop-off at step {step}"
                if error_messages and error_messages.strip():
                    # Take first error message as example
                    first_error = error_messages.split(',')[0].strip()
                    if first_error and first_error != 'None':
                        pattern += f": {first_error[:50]}..."
                failure_patterns.append(pattern)
        
        return failure_patterns
    
    def get_analytics_summary(self) -> Dict[str, Any]:
        """Get high-level analytics summary for dashboard"""
        
        # Key metrics query (last 7 days)
        seven_days_ago = datetime.now() - timedelta(days=7)
        summary_query = text("""
            SELECT 
                COUNT(*) as total_sessions,
                COUNT(DISTINCT primary_intent) as unique_intents,
                AVG(CASE WHEN workflow_completed = true THEN 1.0 ELSE 0.0 END) as overall_completion_rate,
                AVG(success_score) as avg_quality_score,
                SUM(total_interactions) as total_interactions,
                AVG(duration_seconds) as avg_session_duration,
                COUNT(CASE WHEN drop_off_step IS NOT NULL THEN 1 END) as sessions_with_dropoff
            FROM session_summaries
            WHERE started_at >= :seven_days_ago
        """)
        
        result = self.db.execute(summary_query, {'seven_days_ago': seven_days_ago}).fetchone()
        
        return {
            'total_sessions': result[0],
            'unique_intents': result[1],
            'overall_completion_rate': result[2] or 0.0,
            'avg_quality_score': result[3] or 0.0,
            'total_interactions': result[4] or 0,
            'avg_session_duration_seconds': result[5] or 0.0,
            'sessions_with_dropoff': result[6],
            'dropoff_rate': (result[6] / result[0]) if result[0] > 0 else 0.0
        }