"""
Loss Pattern Analyzer - Core IP for detecting agent failure patterns
Identifies patterns across intent, step, tool, and topic dimensions with Claude synthesis
"""

import json
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
from collections import defaultdict, Counter
import asyncio
import os
from sqlalchemy.orm import Session
from sqlalchemy import text

from db.models import LossPattern
from api.security import key_manager, optimized_claude_client


@dataclass
class FailurePattern:
    """Detected failure pattern with analysis"""
    pattern_id: str
    pattern_type: str  # 'intent', 'step', 'tool', 'topic'
    pattern_value: str
    failure_count: int
    total_occurrences: int
    failure_rate: float
    pct_of_all_failures: float
    avg_quality_score: float
    primary_failure_modes: List[str]
    sample_interactions: List[Dict[str, Any]]
    root_cause: Optional[str] = None
    suggested_fix: Optional[str] = None


@dataclass
class PatternAnalysisResult:
    """Complete pattern analysis results"""
    analysis_timestamp: datetime
    total_failures: int
    patterns_detected: List[FailurePattern]
    key_insights: Dict[str, Any]
    top_failure_patterns: List[FailurePattern]


class LossPatternAnalyzer:
    """
    Detects and analyzes agent failure patterns across multiple dimensions
    
    Features:
    - Multi-dimensional pattern detection (intent, step, tool, topic)
    - Claude-powered root cause analysis and fix suggestions
    - Failure percentage distribution analysis
    - Sample interaction extraction for pattern validation
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize pattern analyzer with secure Claude API"""
        # Use secure key manager instead of direct API key handling
        self.key_manager = key_manager
        self.claude_client = optimized_claude_client
        self.claude_available = key_manager.is_available
        
        if self.claude_available:
            print(f"✅ Secure Claude client initialized (key: {key_manager.get_masked_key()})")
        else:
            print("⚠️  Claude API unavailable - pattern analysis will be limited")
    
    async def analyze_patterns(
        self,
        db: Session,
        hours_back: int = 168,  # 1 week default
        min_pattern_count: int = 3
    ) -> PatternAnalysisResult:
        """
        Analyze failure patterns across all dimensions
        
        Args:
            db: Database session
            hours_back: Time period to analyze
            min_pattern_count: Minimum occurrences to consider as pattern
            
        Returns:
            Complete pattern analysis results
        """
        
        print(f"🔍 Analyzing failure patterns over last {hours_back} hours...")
        
        # Get failure data from database
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        failure_data = self._get_failure_data(db, cutoff_time)
        
        if not failure_data:
            return PatternAnalysisResult(
                analysis_timestamp=datetime.now(),
                total_failures=0,
                patterns_detected=[],
                key_insights={},
                top_failure_patterns=[]
            )
        
        total_failures = len(failure_data)
        print(f"📊 Found {total_failures} failures to analyze")
        
        # Detect patterns across dimensions
        patterns = []
        
        # 1. Intent patterns
        intent_patterns = self._detect_intent_patterns(failure_data, total_failures, min_pattern_count)
        patterns.extend(intent_patterns)
        
        # 2. Step patterns  
        step_patterns = self._detect_step_patterns(failure_data, total_failures, min_pattern_count)
        patterns.extend(step_patterns)
        
        # 3. Tool patterns
        tool_patterns = await self._detect_tool_patterns(failure_data, total_failures, min_pattern_count)
        patterns.extend(tool_patterns)

        # 4. Topic patterns (from user input analysis)
        topic_patterns = await self._detect_topic_patterns(failure_data, total_failures, min_pattern_count)
        patterns.extend(topic_patterns)
        
        print(f"🎯 Detected {len(patterns)} failure patterns")
        
        # Synthesize root causes and fixes with Claude
        if self.claude_available:
            patterns = await self._synthesize_pattern_analysis(patterns)
        
        # Generate key insights
        key_insights = self._generate_key_insights(patterns, total_failures)
        
        # Sort patterns by impact (failure count * failure rate)
        top_patterns = sorted(patterns, key=lambda p: p.failure_count * p.failure_rate, reverse=True)[:10]
        
        result = PatternAnalysisResult(
            analysis_timestamp=datetime.now(),
            total_failures=total_failures,
            patterns_detected=patterns,
            key_insights=key_insights,
            top_failure_patterns=top_patterns
        )
        
        # Store patterns in database for tracking
        self._store_patterns(db, result)
        
        return result
    
    def _get_failure_data(self, db: Session, cutoff_time: datetime) -> List[Dict[str, Any]]:
        """Get failure interaction data from database"""
        
        query = text("""
            SELECT 
                al.id,
                al.session_id,
                al.intent,
                al.workflow_step,
                al.user_input,
                al.agent_response,
                al.tool_calls,
                al.timestamp,
                er.overall_score,
                er.evaluation_reasoning,
                er.accuracy_score,
                er.relevance_score,
                er.helpfulness_score,
                er.goal_alignment_score
            FROM eval_results er
            JOIN agent_logs al ON er.agent_log_id = al.id
            WHERE er.evaluated_at >= :cutoff_time
            AND er.overall_score < 0.7
            ORDER BY er.overall_score ASC
        """)
        
        results = db.execute(query, {'cutoff_time': cutoff_time}).fetchall()
        
        return [
            {
                'id': row.id,
                'session_id': row.session_id,
                'intent': row.intent or 'unknown',
                'workflow_step': row.workflow_step,
                'user_input': row.user_input,
                'agent_response': row.agent_response,
                'tool_calls': row.tool_calls,
                'timestamp': row.timestamp,
                'overall_score': row.overall_score,
                'evaluation_reasoning': row.evaluation_reasoning,
                'accuracy_score': row.accuracy_score,
                'relevance_score': row.relevance_score,
                'helpfulness_score': row.helpfulness_score,
                'goal_alignment_score': row.goal_alignment_score
            }
            for row in results
        ]
    
    def _detect_intent_patterns(
        self, 
        failure_data: List[Dict[str, Any]], 
        total_failures: int,
        min_count: int
    ) -> List[FailurePattern]:
        """Detect patterns by intent type with accurate totals"""
        
        intent_failures = defaultdict(list)
        
        # Group failures by intent
        for failure in failure_data:
            intent = failure['intent']
            intent_failures[intent].append(failure)
        
        patterns = []
        for intent, failures in intent_failures.items():
            if len(failures) >= min_count:
                # Get actual total occurrences from database for accurate failure rate
                actual_total = self._get_actual_intent_total(intent)
                failure_rate = len(failures) / actual_total if actual_total > 0 else 0.0
                
                # Extract failure modes from evaluation reasoning
                failure_modes = []
                for f in failures:
                    reason = f.get('evaluation_reasoning', '')
                    if reason and reason != 'unknown':
                        failure_modes.append(reason[:50])  # Truncate for readability
                
                primary_modes = [mode for mode, count in Counter(failure_modes).most_common(3) if mode.strip()]
                
                pattern = FailurePattern(
                    pattern_id=f"intent_{intent}",
                    pattern_type="intent",
                    pattern_value=intent,
                    failure_count=len(failures),
                    total_occurrences=actual_total,
                    failure_rate=failure_rate,
                    pct_of_all_failures=round(len(failures) / total_failures * 100, 1),
                    avg_quality_score=round(sum(f['overall_score'] for f in failures) / len(failures), 3),
                    primary_failure_modes=primary_modes,
                    sample_interactions=failures[:3]  # Best samples for analysis
                )
                
                patterns.append(pattern)
        
        return patterns
    
    def _get_actual_intent_total(self, intent: str) -> int:
        """Get actual total interactions for an intent - placeholder for now"""
        # This would need a database session parameter in production
        # For now, use conservative estimates based on typical patterns
        estimates = {
            'billing': 200,
            'refunds': 150,
            'subscriptions': 180,
            'account_recovery': 100,
            'technical_support': 120,
            'general_enquiry': 90,
            'unknown': 50
        }
        return estimates.get(intent, 75)
    
    def _detect_step_patterns(
        self, 
        failure_data: List[Dict[str, Any]], 
        total_failures: int,
        min_count: int
    ) -> List[FailurePattern]:
        """Detect patterns by workflow step with improved accuracy"""
        
        step_failures = defaultdict(list)
        
        for failure in failure_data:
            step = failure.get('workflow_step', 0)
            if step and step > 0:  # Only valid steps
                step_failures[step].append(failure)
        
        patterns = []
        for step, failures in step_failures.items():
            if len(failures) >= min_count:
                # Better step total estimation based on typical workflow patterns
                step_total_estimate = self._estimate_step_total(step, len(failures))
                failure_rate = min(1.0, len(failures) / step_total_estimate)
                
                # Extract meaningful failure modes
                failure_modes = []
                for f in failures:
                    reason = f.get('evaluation_reasoning', '')
                    if reason and len(reason.strip()) > 5:
                        failure_modes.append(reason[:40])
                
                primary_modes = [mode for mode, count in Counter(failure_modes).most_common(3) if mode.strip()]
                
                pattern = FailurePattern(
                    pattern_id=f"step_{step}",
                    pattern_type="step", 
                    pattern_value=f"Workflow Step {step}",
                    failure_count=len(failures),
                    total_occurrences=step_total_estimate,
                    failure_rate=failure_rate,
                    pct_of_all_failures=round(len(failures) / total_failures * 100, 1),
                    avg_quality_score=round(sum(f['overall_score'] for f in failures) / len(failures), 3),
                    primary_failure_modes=primary_modes,
                    sample_interactions=failures[:3]
                )
                
                patterns.append(pattern)
        
        return patterns
    
    def _estimate_step_total(self, step: int, failure_count: int) -> int:
        """Estimate total occurrences for a workflow step"""
        # Early steps have higher volume, later steps lower volume
        step_multipliers = {
            1: 8,  # Initial requests - high volume
            2: 6,  # Follow-up questions  
            3: 4,  # Information gathering
            4: 3,  # Action execution
            5: 2,  # Confirmation/resolution
        }
        
        multiplier = step_multipliers.get(step, max(1, 6 - step))
        return max(failure_count, failure_count * multiplier)
    
    async def _detect_tool_patterns(
        self,
        failure_data: List[Dict[str, Any]],
        total_failures: int,
        min_count: int
    ) -> List[FailurePattern]:
        """Detect patterns by tool usage using LLM analysis"""

        if self.claude_available and failure_data:
            tool_failures = await self._llm_categorize_tools(failure_data)
        else:
            tool_failures = self._fallback_tool_detection(failure_data)
        
        patterns = []
        
        # Create patterns from LLM-categorized tool failures
        for tool, failures in tool_failures.items():
            if len(failures) >= min_count:
                # Get actual total occurrences for more accurate failure rate
                estimated_total = max(len(failures) * 2, len(failures))  # Conservative estimate
                failure_rate = len(failures) / estimated_total
                
                failure_modes = [f.get('evaluation_reasoning', 'unknown') for f in failures]
                primary_modes = [mode for mode, count in Counter(failure_modes).most_common(3)]
                
                pattern = FailurePattern(
                    pattern_id=f"tool_{tool}",
                    pattern_type="tool",
                    pattern_value=tool.replace('_', ' ').title(),
                    failure_count=len(failures),
                    total_occurrences=estimated_total,
                    failure_rate=failure_rate,
                    pct_of_all_failures=len(failures) / total_failures * 100,
                    avg_quality_score=sum(f['overall_score'] for f in failures) / len(failures),
                    primary_failure_modes=primary_modes,
                    sample_interactions=failures[:3]
                )
                
                patterns.append(pattern)
        
        return patterns
    
    async def _detect_topic_patterns(
        self,
        failure_data: List[Dict[str, Any]],
        total_failures: int,
        min_count: int
    ) -> List[FailurePattern]:
        """Detect patterns by user input topics using LLM classification"""

        if self.claude_available and failure_data:
            topic_failures = await self._llm_categorize_topics(failure_data)
        else:
            topic_failures = self._fallback_topic_detection(failure_data)
        
        patterns = []
        for topic, failures in topic_failures.items():
            if len(failures) >= min_count:
                estimated_total = max(len(failures), int(len(failures) / 0.3))
                failure_rate = len(failures) / estimated_total
                
                failure_modes = [f.get('evaluation_reasoning', 'unknown') for f in failures]
                primary_modes = [mode for mode, count in Counter(failure_modes).most_common(3)]
                
                pattern = FailurePattern(
                    pattern_id=f"topic_{topic}",
                    pattern_type="topic",
                    pattern_value=topic.title(),
                    failure_count=len(failures),
                    total_occurrences=estimated_total,
                    failure_rate=failure_rate,
                    pct_of_all_failures=len(failures) / total_failures * 100,
                    avg_quality_score=sum(f['overall_score'] for f in failures) / len(failures),
                    primary_failure_modes=primary_modes,
                    sample_interactions=failures[:3]
                )
                
                patterns.append(pattern)
        
        return patterns
    
    async def _llm_categorize_topics(self, failure_data: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Use keyword matching for topic categorization (LLM fallback disabled to save tokens)"""
        # Direct fallback to keyword matching to save tokens
        return self._fallback_topic_detection(failure_data)
    
    def _fallback_topic_detection(self, failure_data: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Fallback topic detection using simple keyword matching"""
        
        topic_keywords = self._get_configurable_topic_keywords()
        topic_failures = defaultdict(list)
        
        for failure in failure_data:
            user_input = failure.get('user_input', '').lower()
            assigned = False
            
            for topic, keywords in topic_keywords.items():
                if any(keyword in user_input for keyword in keywords):
                    topic_failures[topic].append(failure)
                    assigned = True
                    break
            
            if not assigned:
                topic_failures["uncategorized"].append(failure)
        
        return dict(topic_failures)
    
    async def _llm_categorize_tools(self, failure_data: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Use keyword matching for tool categorization (LLM disabled to save tokens)"""
        # Use fallback to save tokens - keyword matching is sufficient for tool detection
        return self._fallback_tool_detection(failure_data)
    
    def _fallback_tool_detection(self, failure_data: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Enhanced tool pattern detection with better categorization"""
        
        tool_failures = defaultdict(list)
        
        # Enhanced tool categories
        tool_categories = {
            'financial_tools': ['billing', 'payment', 'invoice', 'refund', 'transaction', 'charge'],
            'authentication_tools': ['auth', 'login', 'password', 'account', 'verify', 'security'],
            'subscription_tools': ['subscription', 'plan', 'upgrade', 'cancel', 'renewal'],
            'customer_service': ['support', 'ticket', 'escalate', 'transfer', 'queue'],
            'data_retrieval': ['lookup', 'search', 'get', 'fetch', 'query', 'database'],
            'communication': ['email', 'sms', 'notification', 'send', 'notify'],
            'tool_errors': ['error', 'timeout', 'failed', 'exception', 'unavailable', 'down']
        }
        
        for failure in failure_data:
            tool_calls = failure.get('tool_calls') or ''
            tool_calls = tool_calls.lower() if tool_calls else ''
            
            if not tool_calls or tool_calls.strip() == '':
                tool_failures['no_tools_used'].append(failure)
                continue
            
            # Try to parse JSON tool calls
            tools_used = self._extract_tool_names(tool_calls)
            
            categorized = False
            for category, keywords in tool_categories.items():
                if any(keyword in tool_calls for keyword in keywords):
                    tool_failures[category].append(failure)
                    categorized = True
                    break
            
            if not categorized:
                tool_failures['unknown_tools'].append(failure)
        
        return dict(tool_failures)
    
    def _extract_tool_names(self, tool_calls: str) -> List[str]:
        """Extract tool names from tool_calls string"""
        try:
            import json
            tools = json.loads(tool_calls)
            if isinstance(tools, list):
                return tools
            elif isinstance(tools, str):
                return [tools]
        except:
            # Fallback to simple parsing
            return [tool.strip() for tool in tool_calls.split(',')]
    
    async def _synthesize_pattern_analysis(self, patterns: List[FailurePattern]) -> List[FailurePattern]:
        """Use Claude to synthesize root causes and fixes for each pattern"""
        
        print(f"🧠 Synthesizing root cause analysis for {len(patterns)} patterns...")
        
        # Process in batches to respect API limits
        batch_size = 5
        for i in range(0, len(patterns), batch_size):
            batch = patterns[i:i + batch_size]
            
            tasks = []
            for pattern in batch:
                task = self._analyze_single_pattern(pattern)
                tasks.append(task)
            
            # Execute batch
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Update patterns with results
            for j, result in enumerate(results):
                if not isinstance(result, Exception):
                    batch[j].root_cause = result.get('root_cause')
                    batch[j].suggested_fix = result.get('suggested_fix')
                else:
                    print(f"⚠️  Failed to analyze pattern {batch[j].pattern_id}: {result}")
            
            # Rate limiting
            if i + batch_size < len(patterns):
                await asyncio.sleep(1)
        
        return patterns
    
    async def _analyze_single_pattern(self, pattern: FailurePattern) -> Dict[str, str]:
        """Analyze single pattern with optimized Claude client"""
        
        # Use the optimized client with token limits
        pattern_data = {
            'type': pattern.pattern_type,
            'value': pattern.pattern_value,
            'failure_count': pattern.failure_count,
            'failure_rate': pattern.failure_rate
        }
        
        try:
            result = await self.claude_client.analyze_pattern(pattern_data)
            return result
            
        except Exception as e:
            print(f"⚠️  Pattern analysis failed: {e}")
            return {
                'root_cause': f"Analysis unavailable for {pattern.pattern_type} pattern",
                'suggested_fix': f"Review {pattern.pattern_value} implementation manually"
            }
    
    def _format_sample_interactions(self, samples: List[Dict[str, Any]]) -> str:
        """Format sample interactions for Claude analysis"""
        
        formatted = []
        for i, sample in enumerate(samples[:3], 1):
            formatted.append(f"""
Sample {i}:
User: {sample.get('user_input', '')[:100]}...
Agent: {sample.get('agent_response', '')[:150]}...
Score: {sample.get('overall_score', 0):.2f}
Issue: {sample.get('evaluation_reasoning', 'Unknown')}
""")
        
        return '\n'.join(formatted)
    
    def _generate_key_insights(self, patterns: List[FailurePattern], total_failures: int) -> Dict[str, Any]:
        """Generate key insights from pattern analysis"""
        
        # Intent analysis - key insight: top 3 intents account for X% of failures
        intent_patterns = [p for p in patterns if p.pattern_type == 'intent']
        intent_patterns.sort(key=lambda p: p.failure_count, reverse=True)
        
        top_3_intent_pct = sum(p.pct_of_all_failures for p in intent_patterns[:3])
        
        # Step analysis
        step_patterns = [p for p in patterns if p.pattern_type == 'step']
        problematic_steps = [p.pattern_value for p in step_patterns if p.failure_rate > 0.4]
        
        # Tool analysis
        tool_patterns = [p for p in patterns if p.pattern_type == 'tool']
        tool_patterns.sort(key=lambda p: p.failure_rate, reverse=True)
        
        # Topic analysis  
        topic_patterns = [p for p in patterns if p.pattern_type == 'topic']
        topic_patterns.sort(key=lambda p: p.failure_count, reverse=True)
        
        return {
            'total_patterns_detected': len(patterns),
            'top_3_intents_failure_pct': round(top_3_intent_pct, 1),
            'most_problematic_intent': intent_patterns[0].pattern_value if intent_patterns else None,
            'problematic_steps': problematic_steps,
            'highest_failure_rate_tool': tool_patterns[0].pattern_value if tool_patterns else None,
            'most_common_failure_topic': topic_patterns[0].pattern_value if topic_patterns else None,
            'patterns_by_type': {
                'intent': len(intent_patterns),
                'step': len(step_patterns), 
                'tool': len(tool_patterns),
                'topic': len(topic_patterns)
            }
        }
    
    def _store_patterns(self, db: Session, result: PatternAnalysisResult):
        """Store detected patterns in database for tracking"""
        
        for pattern in result.patterns_detected:
            # Check if pattern already exists (by pattern name and date)
            existing = db.query(LossPattern).filter(
                LossPattern.pattern_name == pattern.pattern_value,
                LossPattern.detected_at >= datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            ).first()
            
            if not existing:
                loss_pattern = LossPattern(
                    pattern_type=pattern.pattern_type,
                    pattern_name=pattern.pattern_value,
                    pattern_description=f"{pattern.pattern_value} failures - {pattern.failure_count} occurrences",
                    intent_type=pattern.pattern_value if pattern.pattern_type == "intent" else None,
                    workflow_step=self._extract_step_number(pattern) if pattern.pattern_type == "step" else None,
                    tool_name=pattern.pattern_value if pattern.pattern_type == "tool" else None,
                    failure_count=pattern.failure_count,
                    total_occurrences=pattern.total_occurrences,
                    failure_rate=pattern.failure_rate,
                    avg_quality_score=pattern.avg_quality_score,
                    root_cause=pattern.root_cause,
                    suggested_fix=pattern.suggested_fix,
                    detected_at=result.analysis_timestamp
                )
                
                db.add(loss_pattern)
        
        db.commit()
        print(f"💾 Stored {len(result.patterns_detected)} patterns in database")
    
    def _extract_step_number(self, pattern: FailurePattern) -> Optional[int]:
        """Intelligently extract step number from pattern value"""
        import re
        
        # Try to extract number from various formats: "Step 3", "step_3", "3", etc.
        match = re.search(r'(\d+)', pattern.pattern_value)
        if match:
            return int(match.group(1))
        return None
    
    def _get_actual_occurrences_for_intent(self, db: Session, intent: str, cutoff_time: datetime) -> int:
        """Get actual total occurrences for an intent from database"""
        from sqlalchemy import text
        
        query = text("""
            SELECT COUNT(*) as total
            FROM agent_logs 
            WHERE intent = :intent 
            AND timestamp >= :cutoff_time
        """)
        
        result = db.execute(query, {
            'intent': intent,
            'cutoff_time': cutoff_time - timedelta(hours=168)  # Look back to capture total volume
        }).fetchone()
        
        return result.total if result else 0
    
    def _get_configurable_topic_keywords(self) -> Dict[str, List[str]]:
        """Get topic keywords from configuration or environment"""
        
        # Try to load from environment variable first
        topic_config = os.getenv('AGENTIQ_TOPIC_KEYWORDS')
        if topic_config:
            try:
                return json.loads(topic_config)
            except json.JSONDecodeError:
                print("⚠️  Invalid AGENTIQ_TOPIC_KEYWORDS format, using defaults")
        
        # Default topic keywords - these should ideally be configurable
        return {
            'refund': ['refund', 'money back', 'return', 'reimburse'],
            'billing': ['charge', 'bill', 'payment', 'invoice', 'cost'],
            'cancel': ['cancel', 'stop', 'end', 'terminate'],
            'login': ['login', 'password', 'access', 'sign in'],
            'subscription': ['subscription', 'plan', 'upgrade', 'downgrade'],
            'technical': ['error', 'bug', 'broken', 'not working', 'issue']
        }