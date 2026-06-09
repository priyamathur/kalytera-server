"""
AgentIQ Loss Pattern Analysis System
Automated detection and analysis of agent failure patterns with root cause identification

Core Features:
- Systematic failure pattern detection across agent workflows
- Root cause analysis: "billing disputes account for 47% of failures because payment API times out at step 3"
- Multi-dimensional pattern analysis: by intent, workflow step, tool call, time pattern
- Automated priority scoring for developer action
- Structured failure data for continuous improvement loops
"""

import requests
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging
from dataclasses import dataclass
from enum import Enum
from collections import defaultdict, Counter

class FailurePattern(Enum):
    """Types of failure patterns detected in agent workflows"""
    INTENT_SPECIFIC = "intent_specific"           # Failures specific to user intent
    WORKFLOW_STEP = "workflow_step"               # Failures at specific workflow steps
    TOOL_FAILURE = "tool_failure"                 # Tool/API call failures
    SEQUENCE_DEPENDENT = "sequence_dependent"     # Failures in multi-step sequences
    TIME_DEPENDENT = "time_dependent"             # Time-based failure patterns
    CONTEXT_DEPENDENT = "context_dependent"       # Context-specific failures
    COMPOUND_FAILURE = "compound_failure"         # Multiple failure causes

class PatternSeverity(Enum):
    """Severity levels for failure patterns"""
    CRITICAL = "critical"     # >30% failure rate, high volume
    HIGH = "high"             # >20% failure rate or high business impact  
    MEDIUM = "medium"         # >10% failure rate
    LOW = "low"              # <10% failure rate but systematic

@dataclass
class LossPatternDetection:
    """Detected loss pattern with comprehensive analysis"""
    pattern_id: str
    pattern_type: FailurePattern
    severity: PatternSeverity
    
    # Pattern Definition
    pattern_name: str
    description: str
    affected_intent: Optional[str]
    workflow_step: Optional[int]
    tool_involved: Optional[str]
    
    # Impact Analysis
    failure_rate: float           # 0.0 to 1.0
    total_occurrences: int
    affected_sessions: int
    business_impact_score: float  # 0.0 to 1.0
    
    # Root Cause Analysis
    root_causes: List[str]
    contributing_factors: List[str]
    failure_context: Dict[str, Any]
    
    # Pattern Evidence
    example_failures: List[Dict[str, Any]]
    failure_timeline: List[datetime]
    correlation_data: Dict[str, float]
    
    # Actionable Intelligence
    recommended_actions: List[str]
    priority_score: float
    estimated_fix_effort: str    # "low", "medium", "high"
    expected_improvement: str
    
    # Metadata
    detection_confidence: float
    first_detected: datetime
    last_updated: datetime
    pattern_stability: float     # How consistent this pattern is

class LossPatternAnalyzer:
    """Advanced loss pattern analysis for enterprise agent optimization"""
    
    def __init__(self, api_base: str = "https://agentiq-api-z9it.onrender.com"):
        self.api_base = api_base
        self.logger = logging.getLogger("AgentIQ-LossPatternAnalyzer")
        
        # Pattern detection thresholds
        self.min_occurrences = 5      # Minimum failures to constitute a pattern
        self.min_failure_rate = 0.05  # 5% failure rate minimum
        self.min_confidence = 0.7     # Minimum pattern confidence
        
        # Business impact weights
        self.impact_weights = {
            "volume": 0.4,           # Number of affected sessions
            "severity": 0.3,         # Failure rate
            "user_impact": 0.2,      # User experience impact
            "business_cost": 0.1     # Estimated business cost
        }
    
    async def analyze_loss_patterns(self, time_window_hours: int = 168) -> List[LossPatternDetection]:
        """
        Comprehensive loss pattern analysis across all agent interactions
        
        Args:
            time_window_hours: Analysis window (default 1 week)
            
        Returns:
            List of detected loss patterns sorted by priority
        """
        try:
            # Get evaluation and interaction data
            evaluation_data = await self._get_evaluation_data(time_window_hours)
            interaction_data = await self._get_interaction_data(time_window_hours)
            
            if not evaluation_data or not interaction_data:
                self.logger.warning("Insufficient data for loss pattern analysis")
                return []
            
            # Multi-dimensional pattern analysis
            patterns = []
            
            # 1. Intent-specific failure patterns
            intent_patterns = await self._analyze_intent_patterns(evaluation_data, interaction_data)
            patterns.extend(intent_patterns)
            
            # 2. Workflow step failure patterns
            workflow_patterns = await self._analyze_workflow_patterns(interaction_data)
            patterns.extend(workflow_patterns)
            
            # 3. Tool failure patterns
            tool_patterns = await self._analyze_tool_patterns(evaluation_data, interaction_data)
            patterns.extend(tool_patterns)
            
            # 4. Sequence-dependent patterns
            sequence_patterns = await self._analyze_sequence_patterns(interaction_data)
            patterns.extend(sequence_patterns)
            
            # 5. Time-dependent patterns
            time_patterns = await self._analyze_time_patterns(evaluation_data, interaction_data)
            patterns.extend(time_patterns)
            
            # 6. Compound failure patterns
            compound_patterns = await self._analyze_compound_patterns(patterns, evaluation_data)
            patterns.extend(compound_patterns)
            
            # Filter, prioritize, and enrich patterns
            significant_patterns = self._filter_significant_patterns(patterns)
            prioritized_patterns = await self._prioritize_patterns(significant_patterns)
            enriched_patterns = await self._enrich_patterns_with_actions(prioritized_patterns)
            
            self.logger.info(f"Detected {len(enriched_patterns)} significant loss patterns")
            return enriched_patterns
            
        except Exception as e:
            self.logger.error(f"Loss pattern analysis failed: {e}")
            return []
    
    async def get_pattern_insights(self, patterns: List[LossPatternDetection]) -> Dict[str, Any]:
        """
        Generate actionable insights from detected patterns
        
        Args:
            patterns: List of detected loss patterns
            
        Returns:
            Structured insights for enterprise teams
        """
        if not patterns:
            return {"insights": ["No significant loss patterns detected"]}
        
        insights = {
            "summary": self._generate_pattern_summary(patterns),
            "critical_issues": [p for p in patterns if p.severity == PatternSeverity.CRITICAL],
            "high_impact_opportunities": self._identify_high_impact_opportunities(patterns),
            "quick_wins": self._identify_quick_wins(patterns),
            "systemic_issues": self._identify_systemic_issues(patterns),
            "improvement_roadmap": self._generate_improvement_roadmap(patterns),
            "business_impact": self._calculate_business_impact(patterns),
            "developer_actions": self._prioritize_developer_actions(patterns)
        }
        
        return insights
    
    async def _analyze_intent_patterns(self, evaluation_data: List[Dict], interaction_data: List[Dict]) -> List[LossPatternDetection]:
        """Analyze failure patterns by user intent"""
        patterns = []
        
        # Group failures by intent
        intent_failures = defaultdict(list)
        intent_totals = defaultdict(int)
        
        for eval_result in evaluation_data:
            intent = eval_result.get('intent', 'unknown')
            intent_totals[intent] += 1
            
            if eval_result.get('failure_detected', False):
                intent_failures[intent].append(eval_result)
        
        # Analyze each intent for patterns
        for intent, failures in intent_failures.items():
            if len(failures) < self.min_occurrences:
                continue
                
            total_sessions = intent_totals[intent]
            failure_rate = len(failures) / max(total_sessions, 1)
            
            if failure_rate < self.min_failure_rate:
                continue
            
            # Analyze root causes for this intent
            root_causes = self._analyze_intent_root_causes(failures)
            contributing_factors = self._analyze_contributing_factors(failures)
            
            # Calculate business impact
            business_impact = self._calculate_intent_business_impact(intent, failure_rate, len(failures))
            
            # Determine severity
            severity = self._determine_pattern_severity(failure_rate, len(failures), business_impact)
            
            # Generate recommendations
            recommendations = self._generate_intent_recommendations(intent, root_causes, failure_rate)
            
            pattern = LossPatternDetection(
                pattern_id=f"intent_{intent}_{int(datetime.now().timestamp())}",
                pattern_type=FailurePattern.INTENT_SPECIFIC,
                severity=severity,
                pattern_name=f"{intent.replace('_', ' ').title()} Intent Failures",
                description=f"Systematic failures in {intent} interactions with {failure_rate:.1%} failure rate",
                affected_intent=intent,
                workflow_step=None,
                tool_involved=None,
                failure_rate=failure_rate,
                total_occurrences=len(failures),
                affected_sessions=len(set(f.get('session_id') for f in failures if f.get('session_id'))),
                business_impact_score=business_impact,
                root_causes=root_causes,
                contributing_factors=contributing_factors,
                failure_context={"intent": intent, "common_errors": self._extract_common_errors(failures)},
                example_failures=failures[:3],
                failure_timeline=[datetime.fromisoformat(f['timestamp']) for f in failures if f.get('timestamp')],
                correlation_data={"failure_rate": failure_rate},
                recommended_actions=recommendations,
                priority_score=self._calculate_priority_score(failure_rate, len(failures), business_impact),
                estimated_fix_effort=self._estimate_fix_effort(intent, root_causes),
                expected_improvement=f"Could improve {len(failures)} failed interactions",
                detection_confidence=min(0.95, 0.7 + (len(failures) / 50)),
                first_detected=datetime.now(),
                last_updated=datetime.now(),
                pattern_stability=0.8  # Intent patterns tend to be stable
            )
            
            patterns.append(pattern)
        
        return patterns
    
    async def _analyze_workflow_patterns(self, interaction_data: List[Dict]) -> List[LossPatternDetection]:
        """Analyze failure patterns by workflow step"""
        patterns = []
        
        # Group by workflow step and identify failures
        step_failures = defaultdict(list)
        step_totals = defaultdict(int)
        
        for interaction in interaction_data:
            step = interaction.get('workflow_step', 1)
            step_totals[step] += 1
            
            # Identify workflow failures (incomplete, error responses)
            if self._is_workflow_failure(interaction):
                step_failures[step].append(interaction)
        
        # Analyze each step for patterns
        for step, failures in step_failures.items():
            if len(failures) < self.min_occurrences:
                continue
                
            total_at_step = step_totals[step]
            failure_rate = len(failures) / max(total_at_step, 1)
            
            if failure_rate < self.min_failure_rate:
                continue
            
            # Analyze what causes failures at this step
            root_causes = self._analyze_workflow_step_causes(step, failures)
            
            # Calculate business impact of workflow failures
            business_impact = self._calculate_workflow_business_impact(step, failure_rate, len(failures))
            severity = self._determine_pattern_severity(failure_rate, len(failures), business_impact)
            
            recommendations = self._generate_workflow_recommendations(step, root_causes)
            
            pattern = LossPatternDetection(
                pattern_id=f"workflow_step_{step}_{int(datetime.now().timestamp())}",
                pattern_type=FailurePattern.WORKFLOW_STEP,
                severity=severity,
                pattern_name=f"Workflow Step {step} Failures",
                description=f"High failure rate at workflow step {step}: {failure_rate:.1%} of interactions fail",
                affected_intent=None,
                workflow_step=step,
                tool_involved=None,
                failure_rate=failure_rate,
                total_occurrences=len(failures),
                affected_sessions=len(set(f.get('session_id') for f in failures if f.get('session_id'))),
                business_impact_score=business_impact,
                root_causes=root_causes,
                contributing_factors=self._analyze_workflow_contributing_factors(failures),
                failure_context={"workflow_step": step, "step_analysis": self._analyze_step_context(step, failures)},
                example_failures=failures[:3],
                failure_timeline=[datetime.now()],  # Would extract from actual data
                correlation_data={"step": step, "failure_rate": failure_rate},
                recommended_actions=recommendations,
                priority_score=self._calculate_priority_score(failure_rate, len(failures), business_impact),
                estimated_fix_effort=self._estimate_workflow_fix_effort(step, root_causes),
                expected_improvement=f"Could prevent {len(failures)} workflow failures",
                detection_confidence=0.85,
                first_detected=datetime.now(),
                last_updated=datetime.now(),
                pattern_stability=0.75
            )
            
            patterns.append(pattern)
        
        return patterns
    
    async def _analyze_tool_patterns(self, evaluation_data: List[Dict], interaction_data: List[Dict]) -> List[LossPatternDetection]:
        """Analyze failure patterns related to tool usage"""
        patterns = []
        
        # Extract tool usage and failures
        tool_failures = defaultdict(list)
        tool_usage = defaultdict(int)
        
        for interaction in interaction_data:
            tool_calls = interaction.get('tool_calls', '[]')
            try:
                tools = json.loads(tool_calls) if isinstance(tool_calls, str) else tool_calls
                for tool in tools:
                    tool_name = tool.get('name', 'unknown_tool')
                    tool_usage[tool_name] += 1
                    
                    # Check for tool failures
                    if tool.get('result') == 'error' or 'error' in str(tool.get('result', '')).lower():
                        tool_failures[tool_name].append({
                            **interaction,
                            'tool_error': tool.get('result'),
                            'tool_name': tool_name
                        })
            except:
                continue
        
        # Analyze each tool for failure patterns
        for tool_name, failures in tool_failures.items():
            if len(failures) < self.min_occurrences:
                continue
                
            total_usage = tool_usage[tool_name]
            failure_rate = len(failures) / max(total_usage, 1)
            
            if failure_rate < self.min_failure_rate:
                continue
            
            # Analyze tool-specific root causes
            root_causes = self._analyze_tool_root_causes(tool_name, failures)
            business_impact = self._calculate_tool_business_impact(tool_name, failure_rate, len(failures))
            severity = self._determine_pattern_severity(failure_rate, len(failures), business_impact)
            
            recommendations = self._generate_tool_recommendations(tool_name, root_causes)
            
            pattern = LossPatternDetection(
                pattern_id=f"tool_{tool_name}_{int(datetime.now().timestamp())}",
                pattern_type=FailurePattern.TOOL_FAILURE,
                severity=severity,
                pattern_name=f"{tool_name} Tool Failures",
                description=f"High failure rate for {tool_name}: {failure_rate:.1%} of calls fail",
                affected_intent=None,
                workflow_step=None,
                tool_involved=tool_name,
                failure_rate=failure_rate,
                total_occurrences=len(failures),
                affected_sessions=len(set(f.get('session_id') for f in failures if f.get('session_id'))),
                business_impact_score=business_impact,
                root_causes=root_causes,
                contributing_factors=self._analyze_tool_contributing_factors(failures),
                failure_context={"tool": tool_name, "error_types": self._extract_tool_errors(failures)},
                example_failures=failures[:3],
                failure_timeline=[datetime.now()],
                correlation_data={"tool": tool_name, "failure_rate": failure_rate},
                recommended_actions=recommendations,
                priority_score=self._calculate_priority_score(failure_rate, len(failures), business_impact),
                estimated_fix_effort=self._estimate_tool_fix_effort(tool_name, root_causes),
                expected_improvement=f"Could fix {len(failures)} tool call failures",
                detection_confidence=0.9,
                first_detected=datetime.now(),
                last_updated=datetime.now(),
                pattern_stability=0.85
            )
            
            patterns.append(pattern)
        
        return patterns
    
    async def _analyze_sequence_patterns(self, interaction_data: List[Dict]) -> List[LossPatternDetection]:
        """Analyze failure patterns in multi-step sequences"""
        patterns = []
        
        # Group interactions by session to analyze sequences
        sessions = defaultdict(list)
        for interaction in interaction_data:
            session_id = interaction.get('session_id')
            if session_id:
                sessions[session_id].append(interaction)
        
        # Analyze sequences for failure patterns
        sequence_failures = defaultdict(list)
        
        for session_id, interactions in sessions.items():
            # Sort by workflow step
            sorted_interactions = sorted(interactions, key=lambda x: x.get('workflow_step', 0))
            
            # Identify failure sequences
            for i in range(len(sorted_interactions) - 1):
                current = sorted_interactions[i]
                next_step = sorted_interactions[i + 1]
                
                if self._is_sequence_failure(current, next_step):
                    sequence_key = f"step_{current.get('workflow_step', 0)}_to_{next_step.get('workflow_step', 1)}"
                    sequence_failures[sequence_key].append({
                        'session_id': session_id,
                        'current_step': current,
                        'next_step': next_step,
                        'failure_type': self._classify_sequence_failure(current, next_step)
                    })
        
        # Convert to loss patterns
        for sequence, failures in sequence_failures.items():
            if len(failures) < self.min_occurrences:
                continue
            
            # Calculate failure rate for this sequence
            total_sequences = len(sessions)  # Simplified - would need more precise counting
            failure_rate = len(failures) / max(total_sequences, 1)
            
            root_causes = self._analyze_sequence_root_causes(sequence, failures)
            business_impact = self._calculate_sequence_business_impact(sequence, failure_rate, len(failures))
            severity = self._determine_pattern_severity(failure_rate, len(failures), business_impact)
            
            pattern = LossPatternDetection(
                pattern_id=f"sequence_{sequence}_{int(datetime.now().timestamp())}",
                pattern_type=FailurePattern.SEQUENCE_DEPENDENT,
                severity=severity,
                pattern_name=f"Sequence Failure: {sequence.replace('_', ' ').title()}",
                description=f"Multi-step sequence failures at {sequence} with {failure_rate:.1%} rate",
                affected_intent=None,
                workflow_step=None,
                tool_involved=None,
                failure_rate=failure_rate,
                total_occurrences=len(failures),
                affected_sessions=len(failures),  # Each failure is one session
                business_impact_score=business_impact,
                root_causes=root_causes,
                contributing_factors=self._analyze_sequence_contributing_factors(failures),
                failure_context={"sequence": sequence, "failure_types": [f['failure_type'] for f in failures]},
                example_failures=failures[:3],
                failure_timeline=[datetime.now()],
                correlation_data={"sequence": sequence, "failure_rate": failure_rate},
                recommended_actions=self._generate_sequence_recommendations(sequence, root_causes),
                priority_score=self._calculate_priority_score(failure_rate, len(failures), business_impact),
                estimated_fix_effort="medium",  # Sequence issues often require workflow changes
                expected_improvement=f"Could fix {len(failures)} sequence failures",
                detection_confidence=0.8,
                first_detected=datetime.now(),
                last_updated=datetime.now(),
                pattern_stability=0.7
            )
            
            patterns.append(pattern)
        
        return patterns
    
    async def _analyze_time_patterns(self, evaluation_data: List[Dict], interaction_data: List[Dict]) -> List[LossPatternDetection]:
        """Analyze time-dependent failure patterns"""
        patterns = []
        
        # Extract temporal failure data
        hourly_failures = defaultdict(list)
        daily_failures = defaultdict(list)
        
        for eval_result in evaluation_data:
            if not eval_result.get('failure_detected', False):
                continue
                
            timestamp = eval_result.get('timestamp')
            if not timestamp:
                continue
                
            try:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                hour = dt.hour
                day = dt.weekday()  # Monday = 0
                
                hourly_failures[hour].append(eval_result)
                daily_failures[day].append(eval_result)
            except:
                continue
        
        # Analyze hourly patterns
        total_hourly = defaultdict(int)
        for interaction in interaction_data:
            timestamp = interaction.get('timestamp')
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    total_hourly[dt.hour] += 1
                except:
                    continue
        
        # Identify significant time patterns
        for hour, failures in hourly_failures.items():
            if len(failures) < self.min_occurrences:
                continue
                
            total = total_hourly[hour]
            if total == 0:
                continue
                
            failure_rate = len(failures) / total
            expected_rate = sum(len(f) for f in hourly_failures.values()) / sum(total_hourly.values())
            
            # Only flag if significantly higher than expected
            if failure_rate > expected_rate * 1.5 and failure_rate > self.min_failure_rate:
                root_causes = self._analyze_time_root_causes("hourly", hour, failures)
                
                pattern = LossPatternDetection(
                    pattern_id=f"time_hour_{hour}_{int(datetime.now().timestamp())}",
                    pattern_type=FailurePattern.TIME_DEPENDENT,
                    severity=PatternSeverity.MEDIUM,  # Time patterns usually medium priority
                    pattern_name=f"Hour {hour} Failure Spike",
                    description=f"High failure rate at hour {hour}: {failure_rate:.1%} vs expected {expected_rate:.1%}",
                    affected_intent=None,
                    workflow_step=None,
                    tool_involved=None,
                    failure_rate=failure_rate,
                    total_occurrences=len(failures),
                    affected_sessions=len(set(f.get('session_id') for f in failures if f.get('session_id'))),
                    business_impact_score=failure_rate * 0.5,  # Time patterns have moderate business impact
                    root_causes=root_causes,
                    contributing_factors=[f"Peak usage at hour {hour}", "System load factors"],
                    failure_context={"time_pattern": "hourly", "hour": hour},
                    example_failures=failures[:3],
                    failure_timeline=[datetime.now()],
                    correlation_data={"hour": hour, "failure_rate": failure_rate, "expected_rate": expected_rate},
                    recommended_actions=self._generate_time_recommendations("hourly", hour, root_causes),
                    priority_score=failure_rate * len(failures) * 0.1,  # Lower priority for time patterns
                    estimated_fix_effort="low",
                    expected_improvement=f"Could prevent {len(failures)} time-based failures",
                    detection_confidence=0.75,
                    first_detected=datetime.now(),
                    last_updated=datetime.now(),
                    pattern_stability=0.6  # Time patterns can be volatile
                )
                
                patterns.append(pattern)
        
        return patterns
    
    async def _analyze_compound_patterns(self, existing_patterns: List[LossPatternDetection], evaluation_data: List[Dict]) -> List[LossPatternDetection]:
        """Analyze compound failure patterns involving multiple factors"""
        patterns = []
        
        # Look for intersections between existing patterns
        pattern_intersections = []
        
        for i, pattern1 in enumerate(existing_patterns):
            for j, pattern2 in enumerate(existing_patterns[i+1:], i+1):
                # Check if patterns share common failures
                intersection = self._find_pattern_intersection(pattern1, pattern2)
                if intersection['overlap_rate'] > 0.3:  # 30% overlap threshold
                    pattern_intersections.append({
                        'pattern1': pattern1,
                        'pattern2': pattern2,
                        'intersection': intersection
                    })
        
        # Create compound patterns for significant intersections
        for intersection_data in pattern_intersections:
            pattern1 = intersection_data['pattern1']
            pattern2 = intersection_data['pattern2']
            intersection = intersection_data['intersection']
            
            compound_failures = intersection['common_failures']
            if len(compound_failures) < self.min_occurrences:
                continue
            
            # Analyze the compound pattern
            failure_rate = intersection['overlap_rate']
            root_causes = pattern1.root_causes + pattern2.root_causes
            business_impact = max(pattern1.business_impact_score, pattern2.business_impact_score) * 1.2  # Compound effect
            
            pattern = LossPatternDetection(
                pattern_id=f"compound_{pattern1.pattern_id}_{pattern2.pattern_id}",
                pattern_type=FailurePattern.COMPOUND_FAILURE,
                severity=PatternSeverity.HIGH,  # Compound patterns are usually high priority
                pattern_name=f"Compound: {pattern1.pattern_name} + {pattern2.pattern_name}",
                description=f"Combined failure pattern affecting {len(compound_failures)} interactions",
                affected_intent=pattern1.affected_intent or pattern2.affected_intent,
                workflow_step=pattern1.workflow_step or pattern2.workflow_step,
                tool_involved=pattern1.tool_involved or pattern2.tool_involved,
                failure_rate=failure_rate,
                total_occurrences=len(compound_failures),
                affected_sessions=len(set(f.get('session_id') for f in compound_failures if f.get('session_id'))),
                business_impact_score=business_impact,
                root_causes=list(set(root_causes)),  # Remove duplicates
                contributing_factors=list(set(pattern1.contributing_factors + pattern2.contributing_factors)),
                failure_context={"compound_of": [pattern1.pattern_id, pattern2.pattern_id]},
                example_failures=compound_failures[:3],
                failure_timeline=[datetime.now()],
                correlation_data={"overlap_rate": intersection['overlap_rate']},
                recommended_actions=self._generate_compound_recommendations(pattern1, pattern2),
                priority_score=business_impact * len(compound_failures),
                estimated_fix_effort="high",  # Compound patterns are complex to fix
                expected_improvement=f"Could resolve {len(compound_failures)} compound failures",
                detection_confidence=min(pattern1.detection_confidence, pattern2.detection_confidence) * 0.9,
                first_detected=datetime.now(),
                last_updated=datetime.now(),
                pattern_stability=0.8
            )
            
            patterns.append(pattern)
        
        return patterns
    
    # Helper methods for root cause analysis
    
    def _analyze_intent_root_causes(self, failures: List[Dict]) -> List[str]:
        """Analyze root causes for intent-specific failures"""
        causes = []
        
        # Analyze failure reasons
        failure_reasons = [f.get('failure_reasoning', '') for f in failures]
        common_reasons = Counter(failure_reasons).most_common(3)
        
        for reason, count in common_reasons:
            if count >= len(failures) * 0.3:  # 30% threshold
                causes.append(reason)
        
        # Add generic causes if none found
        if not causes:
            causes = ["Intent processing errors", "Response quality issues"]
        
        return causes
    
    def _analyze_workflow_step_causes(self, step: int, failures: List[Dict]) -> List[str]:
        """Analyze root causes for workflow step failures"""
        causes = []
        
        if step == 1:
            causes.append("Initial request processing failures")
        elif step == 2:
            causes.append("Secondary processing or tool call failures")
        elif step >= 3:
            causes.append("Complex multi-step workflow failures")
        
        # Analyze error patterns in the failures
        error_patterns = []
        for failure in failures:
            response = failure.get('agent_response', '').lower()
            if 'error' in response:
                error_patterns.append("Explicit error responses")
            elif 'sorry' in response and 'cannot' in response:
                error_patterns.append("Agent giving up responses")
            elif len(response) < 20:
                error_patterns.append("Insufficient response length")
        
        # Add most common error patterns
        common_errors = Counter(error_patterns).most_common(2)
        causes.extend([error for error, count in common_errors if count >= len(failures) * 0.2])
        
        return causes[:5]  # Limit to top 5 causes
    
    def _analyze_tool_root_causes(self, tool_name: str, failures: List[Dict]) -> List[str]:
        """Analyze root causes for tool-specific failures"""
        causes = []
        
        # Tool-specific analysis
        tool_errors = [f.get('tool_error', '') for f in failures if f.get('tool_error')]
        if tool_errors:
            error_types = Counter([self._categorize_tool_error(error) for error in tool_errors])
            for error_type, count in error_types.most_common(3):
                if count >= len(failures) * 0.2:
                    causes.append(f"{tool_name} {error_type}")
        
        # Generic tool causes
        if not causes:
            causes = [f"{tool_name} timeout issues", f"{tool_name} API errors", f"{tool_name} parameter issues"]
        
        return causes
    
    def _categorize_tool_error(self, error: str) -> str:
        """Categorize tool error into common types"""
        error_lower = str(error).lower()
        
        if 'timeout' in error_lower:
            return "timeout errors"
        elif 'auth' in error_lower or 'permission' in error_lower:
            return "authentication errors"
        elif 'rate' in error_lower or 'limit' in error_lower:
            return "rate limiting errors"
        elif 'parameter' in error_lower or 'invalid' in error_lower:
            return "parameter errors"
        elif 'network' in error_lower or 'connection' in error_lower:
            return "network errors"
        else:
            return "generic errors"
    
    # Helper methods for business impact calculation
    
    def _calculate_intent_business_impact(self, intent: str, failure_rate: float, failure_count: int) -> float:
        """Calculate business impact of intent-specific failures"""
        
        # Intent-specific impact weights
        intent_weights = {
            "billing_support": 0.9,      # High business impact
            "account_access": 0.8,       # High user impact
            "sales_inquiry": 0.85,       # Direct revenue impact
            "debugging": 0.7,            # Developer productivity impact
            "general_inquiry": 0.5       # Lower business impact
        }
        
        base_impact = failure_rate * (failure_count / 100)  # Normalize by volume
        intent_weight = intent_weights.get(intent, 0.6)     # Default weight
        
        return min(1.0, base_impact * intent_weight)
    
    def _calculate_workflow_business_impact(self, step: int, failure_rate: float, failure_count: int) -> float:
        """Calculate business impact of workflow step failures"""
        
        # Later steps have higher impact (more work lost)
        step_weight = min(1.0, 0.5 + (step - 1) * 0.2)
        base_impact = failure_rate * (failure_count / 100)
        
        return min(1.0, base_impact * step_weight)
    
    def _calculate_tool_business_impact(self, tool_name: str, failure_rate: float, failure_count: int) -> float:
        """Calculate business impact of tool failures"""
        
        # Critical tools have higher impact
        critical_tools = ["payment_processor", "billing_system", "user_auth", "database"]
        tool_weight = 0.9 if tool_name in critical_tools else 0.6
        
        base_impact = failure_rate * (failure_count / 50)  # Tools failures are serious
        return min(1.0, base_impact * tool_weight)
    
    def _calculate_sequence_business_impact(self, sequence: str, failure_rate: float, failure_count: int) -> float:
        """Calculate business impact of sequence failures"""
        # Sequence failures waste user time through multiple steps
        return min(1.0, failure_rate * (failure_count / 75) * 0.8)
    
    # Pattern filtering and prioritization methods
    
    def _filter_significant_patterns(self, patterns: List[LossPatternDetection]) -> List[LossPatternDetection]:
        """Filter patterns to only include significant ones"""
        
        significant = []
        for pattern in patterns:
            # Significance criteria
            if (pattern.total_occurrences >= self.min_occurrences and 
                pattern.failure_rate >= self.min_failure_rate and
                pattern.detection_confidence >= self.min_confidence):
                significant.append(pattern)
        
        return significant
    
    async def _prioritize_patterns(self, patterns: List[LossPatternDetection]) -> List[LossPatternDetection]:
        """Prioritize patterns by business impact and fix feasibility"""
        
        # Calculate priority scores
        for pattern in patterns:
            pattern.priority_score = self._calculate_priority_score(
                pattern.failure_rate,
                pattern.total_occurrences, 
                pattern.business_impact_score
            )
        
        # Sort by priority score (descending)
        return sorted(patterns, key=lambda p: p.priority_score, reverse=True)
    
    def _calculate_priority_score(self, failure_rate: float, failure_count: int, business_impact: float) -> float:
        """Calculate priority score for pattern"""
        
        # Weighted combination of factors
        volume_score = min(1.0, failure_count / 100)    # Normalize to 0-1
        rate_score = failure_rate                        # Already 0-1
        impact_score = business_impact                   # Already 0-1
        
        # Weighted average
        weights = self.impact_weights
        priority = (
            volume_score * weights["volume"] +
            rate_score * weights["severity"] + 
            impact_score * weights["business_cost"] +
            impact_score * weights["user_impact"]  # Use impact for user_impact too
        )
        
        return priority
    
    # Pattern enrichment methods
    
    async def _enrich_patterns_with_actions(self, patterns: List[LossPatternDetection]) -> List[LossPatternDetection]:
        """Enrich patterns with specific actionable recommendations"""
        
        for pattern in patterns:
            # Generate pattern-specific actions
            if pattern.pattern_type == FailurePattern.INTENT_SPECIFIC:
                pattern.recommended_actions = self._generate_intent_recommendations(
                    pattern.affected_intent, pattern.root_causes, pattern.failure_rate
                )
            elif pattern.pattern_type == FailurePattern.TOOL_FAILURE:
                pattern.recommended_actions = self._generate_tool_recommendations(
                    pattern.tool_involved, pattern.root_causes
                )
            elif pattern.pattern_type == FailurePattern.WORKFLOW_STEP:
                pattern.recommended_actions = self._generate_workflow_recommendations(
                    pattern.workflow_step, pattern.root_causes
                )
            
            # Estimate fix effort
            pattern.estimated_fix_effort = self._estimate_fix_effort(
                pattern.affected_intent or pattern.tool_involved or "general",
                pattern.root_causes
            )
        
        return patterns
    
    def _generate_intent_recommendations(self, intent: str, root_causes: List[str], failure_rate: float) -> List[str]:
        """Generate specific recommendations for intent failures"""
        recommendations = []
        
        if failure_rate > 0.3:
            recommendations.append(f"URGENT: Review and redesign {intent} handling - {failure_rate:.1%} failure rate")
        
        for cause in root_causes[:3]:  # Top 3 causes
            if "quality" in cause.lower():
                recommendations.append(f"Improve response quality for {intent} queries")
            elif "error" in cause.lower():
                recommendations.append(f"Add error handling for {intent} edge cases") 
            elif "processing" in cause.lower():
                recommendations.append(f"Optimize {intent} processing pipeline")
        
        if not recommendations:
            recommendations.append(f"Analyze {intent} interaction patterns and improve responses")
        
        return recommendations
    
    def _generate_workflow_recommendations(self, step: int, root_causes: List[str]) -> List[str]:
        """Generate recommendations for workflow step failures"""
        recommendations = []
        
        recommendations.append(f"Review workflow step {step} for systematic issues")
        
        if step == 1:
            recommendations.append("Improve initial request parsing and validation")
        elif step >= 3:
            recommendations.append("Simplify complex multi-step workflows")
        
        for cause in root_causes[:2]:
            if "tool" in cause.lower():
                recommendations.append(f"Fix tool reliability issues at step {step}")
            elif "timeout" in cause.lower():
                recommendations.append(f"Optimize step {step} performance")
        
        return recommendations
    
    def _generate_tool_recommendations(self, tool_name: str, root_causes: List[str]) -> List[str]:
        """Generate recommendations for tool failures"""
        recommendations = []
        
        recommendations.append(f"Investigate {tool_name} reliability issues")
        
        for cause in root_causes[:3]:
            if "timeout" in cause.lower():
                recommendations.append(f"Increase {tool_name} timeout limits and add retry logic")
            elif "auth" in cause.lower():
                recommendations.append(f"Fix {tool_name} authentication issues")
            elif "parameter" in cause.lower():
                recommendations.append(f"Validate {tool_name} input parameters")
            elif "rate" in cause.lower():
                recommendations.append(f"Implement {tool_name} rate limiting handling")
        
        return recommendations
    
    # Additional helper methods
    
    def _is_workflow_failure(self, interaction: Dict) -> bool:
        """Determine if interaction represents a workflow failure"""
        response = interaction.get('agent_response', '').lower()
        
        # Failure indicators
        failure_indicators = [
            'error', 'failed', 'cannot', 'unable', 'sorry', 'not possible',
            'something went wrong', 'try again', 'timeout'
        ]
        
        return any(indicator in response for indicator in failure_indicators)
    
    def _is_sequence_failure(self, current: Dict, next_step: Dict) -> bool:
        """Determine if there's a sequence failure between steps"""
        
        # Check if next step is unexpectedly short or error-like
        next_response = next_step.get('agent_response', '').lower()
        
        if len(next_response) < 20:
            return True
        
        if any(word in next_response for word in ['error', 'failed', 'cannot continue']):
            return True
            
        return False
    
    def _classify_sequence_failure(self, current: Dict, next_step: Dict) -> str:
        """Classify the type of sequence failure"""
        next_response = next_step.get('agent_response', '').lower()
        
        if 'error' in next_response:
            return "error_propagation"
        elif len(next_response) < 20:
            return "incomplete_response"
        elif 'cannot' in next_response:
            return "capability_limitation"
        else:
            return "general_sequence_failure"
    
    def _find_pattern_intersection(self, pattern1: LossPatternDetection, pattern2: LossPatternDetection) -> Dict[str, Any]:
        """Find intersection between two patterns"""
        
        # For now, return a simulated intersection
        # In production, this would analyze actual failure data overlap
        overlap_rate = 0.0
        common_failures = []
        
        # Simulated overlap detection
        if pattern1.affected_intent and pattern2.affected_intent:
            if pattern1.affected_intent == pattern2.affected_intent:
                overlap_rate = 0.4
        
        return {
            "overlap_rate": overlap_rate,
            "common_failures": common_failures
        }
    
    def _determine_pattern_severity(self, failure_rate: float, failure_count: int, business_impact: float) -> PatternSeverity:
        """Determine pattern severity based on multiple factors"""
        
        if failure_rate > 0.3 or (failure_count > 50 and business_impact > 0.8):
            return PatternSeverity.CRITICAL
        elif failure_rate > 0.2 or (failure_count > 25 and business_impact > 0.6):
            return PatternSeverity.HIGH
        elif failure_rate > 0.1 or failure_count > 10:
            return PatternSeverity.MEDIUM
        else:
            return PatternSeverity.LOW
    
    def _estimate_fix_effort(self, component: str, root_causes: List[str]) -> str:
        """Estimate effort required to fix the pattern"""
        
        if any("timeout" in cause.lower() for cause in root_causes):
            return "low"  # Usually configuration changes
        elif any("tool" in cause.lower() for cause in root_causes):
            return "medium"  # May require integration work
        elif any("workflow" in cause.lower() or "design" in cause.lower() for cause in root_causes):
            return "high"  # Requires architectural changes
        else:
            return "medium"  # Default to medium effort
    
    # Data fetching methods (simplified)
    
    async def _get_evaluation_data(self, hours: int) -> List[Dict]:
        """Get evaluation data for analysis"""
        try:
            response = requests.get(f"{self.api_base}/evaluation/results?hours={hours}", timeout=10)
            if response.status_code == 200:
                return response.json()
            return []
        except:
            return []
    
    async def _get_interaction_data(self, hours: int) -> List[Dict]:
        """Get interaction data for analysis"""
        try:
            response = requests.get(f"{self.api_base}/analytics/interactions?hours={hours}", timeout=10)
            if response.status_code == 200:
                return response.json()
            return []
        except:
            return []
    
    # Additional analysis helper methods
    
    def _extract_common_errors(self, failures: List[Dict]) -> List[str]:
        """Extract most common error types from failures"""
        errors = []
        for failure in failures:
            reasoning = failure.get('failure_reasoning', '')
            if reasoning:
                errors.append(reasoning)
        
        return [error for error, count in Counter(errors).most_common(3)]
    
    def _extract_tool_errors(self, failures: List[Dict]) -> List[str]:
        """Extract tool-specific error types"""
        tool_errors = []
        for failure in failures:
            tool_error = failure.get('tool_error', '')
            if tool_error:
                tool_errors.append(self._categorize_tool_error(tool_error))
        
        return list(set(tool_errors))
    
    def _analyze_contributing_factors(self, failures: List[Dict]) -> List[str]:
        """Analyze contributing factors to failures"""
        factors = []
        
        # Analyze patterns in the failure data
        response_lengths = [len(f.get('agent_response', '')) for f in failures]
        avg_length = sum(response_lengths) / len(response_lengths) if response_lengths else 0
        
        if avg_length < 50:
            factors.append("Responses too short")
        
        # Check for time patterns
        timestamps = [f.get('timestamp') for f in failures if f.get('timestamp')]
        if len(timestamps) > 3:
            factors.append("Consistent failure timing")
        
        return factors
    
    # Generate summary insights
    
    def _generate_pattern_summary(self, patterns: List[LossPatternDetection]) -> Dict[str, Any]:
        """Generate high-level summary of detected patterns"""
        
        if not patterns:
            return {"total_patterns": 0, "summary": "No significant loss patterns detected"}
        
        critical_count = len([p for p in patterns if p.severity == PatternSeverity.CRITICAL])
        high_count = len([p for p in patterns if p.severity == PatternSeverity.HIGH])
        
        total_affected_sessions = sum(p.affected_sessions for p in patterns)
        avg_failure_rate = sum(p.failure_rate for p in patterns) / len(patterns)
        
        return {
            "total_patterns": len(patterns),
            "critical_issues": critical_count,
            "high_priority_issues": high_count, 
            "total_affected_sessions": total_affected_sessions,
            "average_failure_rate": f"{avg_failure_rate:.1%}",
            "summary": f"Detected {len(patterns)} loss patterns affecting {total_affected_sessions} sessions"
        }
    
    def _identify_high_impact_opportunities(self, patterns: List[LossPatternDetection]) -> List[Dict[str, Any]]:
        """Identify patterns with highest improvement potential"""
        
        opportunities = []
        
        for pattern in patterns[:5]:  # Top 5 by priority
            if pattern.business_impact_score > 0.6:
                opportunities.append({
                    "pattern": pattern.pattern_name,
                    "impact": f"Could recover {pattern.affected_sessions} sessions",
                    "effort": pattern.estimated_fix_effort,
                    "priority": pattern.severity.value,
                    "actions": pattern.recommended_actions[:2]
                })
        
        return opportunities
    
    def _identify_quick_wins(self, patterns: List[LossPatternDetection]) -> List[Dict[str, str]]:
        """Identify patterns that can be fixed with low effort"""
        
        quick_wins = []
        
        for pattern in patterns:
            if pattern.estimated_fix_effort == "low" and pattern.total_occurrences >= 10:
                quick_wins.append({
                    "pattern": pattern.pattern_name,
                    "fix": pattern.recommended_actions[0] if pattern.recommended_actions else "Quick configuration fix",
                    "impact": f"{pattern.total_occurrences} failures"
                })
        
        return quick_wins[:3]  # Top 3 quick wins
    
    def _identify_systemic_issues(self, patterns: List[LossPatternDetection]) -> List[str]:
        """Identify systemic issues affecting multiple patterns"""
        
        issues = []
        
        # Look for common root causes across patterns
        all_causes = []
        for pattern in patterns:
            all_causes.extend(pattern.root_causes)
        
        common_causes = [cause for cause, count in Counter(all_causes).items() if count >= 2]
        
        for cause in common_causes:
            issues.append(f"Systemic issue: {cause} affects multiple patterns")
        
        return issues
    
    def _generate_improvement_roadmap(self, patterns: List[LossPatternDetection]) -> List[Dict[str, Any]]:
        """Generate prioritized improvement roadmap"""
        
        roadmap = []
        
        # Group by effort level
        low_effort = [p for p in patterns if p.estimated_fix_effort == "low"]
        medium_effort = [p for p in patterns if p.estimated_fix_effort == "medium"]
        high_effort = [p for p in patterns if p.estimated_fix_effort == "high"]
        
        roadmap.append({
            "phase": "Quick Wins (Week 1-2)",
            "patterns": [p.pattern_name for p in low_effort[:3]],
            "expected_impact": f"Fix {sum(p.total_occurrences for p in low_effort[:3])} failures"
        })
        
        roadmap.append({
            "phase": "Medium Impact (Week 3-6)",
            "patterns": [p.pattern_name for p in medium_effort[:2]],
            "expected_impact": f"Improve {sum(p.affected_sessions for p in medium_effort[:2])} sessions"
        })
        
        if high_effort:
            roadmap.append({
                "phase": "Strategic Improvements (Month 2-3)",
                "patterns": [p.pattern_name for p in high_effort[:1]],
                "expected_impact": "Address systemic architectural issues"
            })
        
        return roadmap
    
    def _calculate_business_impact(self, patterns: List[LossPatternDetection]) -> Dict[str, Any]:
        """Calculate overall business impact of detected patterns"""
        
        total_failures = sum(p.total_occurrences for p in patterns)
        total_sessions_affected = sum(p.affected_sessions for p in patterns)
        
        # Estimate cost (simplified)
        avg_cost_per_failure = 5.0  # $5 per failed interaction (example)
        estimated_cost = total_failures * avg_cost_per_failure
        
        return {
            "total_failure_occurrences": total_failures,
            "total_sessions_affected": total_sessions_affected,
            "estimated_monthly_cost": f"${estimated_cost:.0f}",
            "top_cost_pattern": patterns[0].pattern_name if patterns else None,
            "potential_savings": f"${estimated_cost * 0.7:.0f}"  # 70% of current cost
        }
    
    def _prioritize_developer_actions(self, patterns: List[LossPatternDetection]) -> List[Dict[str, str]]:
        """Prioritize actions for developer teams"""
        
        actions = []
        
        for i, pattern in enumerate(patterns[:10], 1):  # Top 10 patterns
            primary_action = pattern.recommended_actions[0] if pattern.recommended_actions else "Investigate pattern"
            
            actions.append({
                "priority": str(i),
                "action": primary_action,
                "pattern": pattern.pattern_name,
                "impact": f"{pattern.total_occurrences} failures",
                "effort": pattern.estimated_fix_effort,
                "timeline": self._estimate_timeline(pattern.estimated_fix_effort)
            })
        
        return actions
    
    def _estimate_timeline(self, effort: str) -> str:
        """Estimate timeline based on effort level"""
        timelines = {
            "low": "1-2 weeks",
            "medium": "2-4 weeks", 
            "high": "1-2 months"
        }
        return timelines.get(effort, "2-4 weeks")


# Convenience functions
async def analyze_agent_loss_patterns(time_window_hours: int = 168) -> List[LossPatternDetection]:
    """Quick function to analyze loss patterns"""
    analyzer = LossPatternAnalyzer()
    return await analyzer.analyze_loss_patterns(time_window_hours)

async def get_loss_pattern_insights(patterns: List[LossPatternDetection]) -> Dict[str, Any]:
    """Quick function to get pattern insights"""
    analyzer = LossPatternAnalyzer()
    return await analyzer.get_pattern_insights(patterns)