"""
Session builder for computing SessionSummary on ingest
Aggregates interactions into sessions with intent, workflow_path, drop_off_step, completion status
"""
from __future__ import annotations

from typing import List, Dict, Optional, Tuple, Any
import statistics
import json
from dataclasses import dataclass
import uuid

from db.models import AgentLog
from evaluation.intent_classifier import IntentClassifier, IntentClassification
from ingestion.parsers import ParsedInteraction

# Imported lazily at runtime to avoid circular import (api -> ingest_endpoints -> here)
# Declared here so tests can patch 'ingestion.session_builder.SessionLocal'
SessionLocal = None


def _get_session_local():
    global SessionLocal
    if SessionLocal is None:
        from api.database import SessionLocal as _SL
        SessionLocal = _SL
    return SessionLocal


@dataclass
class WorkflowPath:
    """Represents the path through a conversation workflow"""
    steps: List[str]
    tools_used: List[str]
    decision_points: List[Dict[str, Any]]
    success_indicators: List[str]
    failure_points: List[str]


class SessionBuilder:
    """Builds session summaries from parsed interactions"""
    
    def __init__(self, intent_classifier: Optional[IntentClassifier] = None):
        """Initialize session builder with optional intent classifier"""
        self.intent_classifier = intent_classifier
        
    async def build_session_summary(
        self, 
        session_id: str, 
        interactions: List[ParsedInteraction]
    ) -> Tuple[SessionSummary, List[AgentLog]]:
        """
        Build session summary and agent logs from parsed interactions
        
        Args:
            session_id: Unique session identifier
            interactions: List of parsed interactions in chronological order
            
        Returns:
            Tuple of (SessionSummary, List[AgentLog])
        """
        
        if not interactions:
            raise ValueError("Cannot build session from empty interactions")
        
        # Sort interactions by timestamp
        interactions = sorted(interactions, key=lambda x: x.timestamp)
        
        # Create AgentLog entries
        agent_logs = []
        for i, interaction in enumerate(interactions):
            agent_log = AgentLog(
                id=str(uuid.uuid4()),
                session_id=session_id,
                timestamp=interaction.timestamp,
                user_input=interaction.user_input,
                agent_response=interaction.agent_response,
                intent=None,  # Will be set from classification
                workflow_step=interaction.workflow_step or (i + 1),
                tool_calls=json.dumps(interaction.tool_calls) if interaction.tool_calls else None,
                response_time_ms=interaction.response_time_ms or 1000,
                tokens_used=interaction.tokens_used or 50,
                error_occurred=interaction.error_occurred,
                error_message=interaction.error_message
            )
            agent_logs.append(agent_log)
        
        # Classify intent if classifier available
        intent_classification = None
        if self.intent_classifier:
            try:
                interaction_dicts = [
                    {
                        "user_input": interaction.user_input,
                        "agent_response": interaction.agent_response
                    }
                    for interaction in interactions
                ]
                intent_classification = await self.intent_classifier.classify_session_intent(interaction_dicts)
                
                # Set intent on agent logs
                for log in agent_logs:
                    log.intent = intent_classification.primary_intent
                    
            except Exception as e:
                print(f"⚠️  Intent classification failed for session {session_id}: {e}")
        
        # Analyze workflow path
        workflow_analysis = self._analyze_workflow_path(interactions)
        
        # Determine completion status
        completion_analysis = self._analyze_completion_status(interactions, workflow_analysis)
        
        # Calculate session metrics
        session_metrics = self._calculate_session_metrics(interactions)
        
        # Create session summary
        session_summary = SessionSummary(
            id=session_id,
            started_at=interactions[0].timestamp,
            ended_at=interactions[-1].timestamp,
            duration_seconds=int((interactions[-1].timestamp - interactions[0].timestamp).total_seconds()),
            total_interactions=len(interactions),
            primary_intent=intent_classification.primary_intent if intent_classification else None,
            intent_confidence=intent_classification.confidence if intent_classification else None,
            workflow_completed=completion_analysis["completed"],
            drop_off_step=completion_analysis["drop_off_step"],
            total_tokens=session_metrics["total_tokens"],
            avg_response_time_ms=session_metrics["avg_response_time"],
            errors_count=session_metrics["error_count"],
            success_score=self._calculate_success_score(
                interactions, 
                completion_analysis, 
                session_metrics,
                intent_classification
            )
        )
        
        return session_summary, agent_logs
    
    async def update_session_summary(self, session_id: str, db) -> None:
        """
        Update or create session summary in real-time as new interactions arrive
        
        Args:
            session_id: Session to update
            db: Database session
        """
        try:
            from sqlalchemy import text
            
            # Get all interactions for this session
            interactions_query = text("""
                SELECT 
                    user_input, agent_response, timestamp, workflow_step,
                    tool_calls, response_time_ms, tokens_used, 
                    error_occurred, error_message, intent
                FROM agent_logs 
                WHERE session_id = :session_id 
                ORDER BY timestamp ASC
            """)
            
            result = db.execute(interactions_query, {"session_id": session_id})
            interaction_rows = result.fetchall()
            
            if not interaction_rows:
                return
            
            # Convert to ParsedInteraction format for existing logic
            parsed_interactions = []
            for row in interaction_rows:
                # Parse tool_calls JSON if present
                tool_calls = None
                if row[4]:  # tool_calls column
                    try:
                        import json
                        tool_calls = json.loads(row[4])
                    except:
                        tool_calls = []
                
                # Create a simple object that matches ParsedInteraction interface
                class SimpleInteraction:
                    def __init__(self, **kwargs):
                        for key, value in kwargs.items():
                            setattr(self, key, value)
                
                parsed_interaction = SimpleInteraction(
                    session_id=session_id,
                    user_input=row[0],
                    agent_response=row[1], 
                    timestamp=row[2],
                    workflow_step=row[3] or 1,
                    tool_calls=tool_calls,
                    response_time_ms=row[5] or 1000,
                    tokens_used=row[6] or 50,
                    error_occurred=row[7] or False,
                    error_message=row[8],
                    intent=row[9]  # Already classified intent
                )
                parsed_interactions.append(parsed_interaction)
            
            # Calculate session metrics using existing methods
            workflow_analysis = self._analyze_workflow_path(parsed_interactions)
            completion_analysis = self._analyze_completion_status(parsed_interactions, workflow_analysis)
            session_metrics = self._calculate_session_metrics(parsed_interactions)
            
            # Get intent from first interaction (already classified)
            primary_intent = parsed_interactions[0].intent if parsed_interactions else None
            intent_confidence = 0.8 if primary_intent else None  # Default confidence
            
            # Calculate success score
            success_score = self._calculate_success_score(
                parsed_interactions, 
                completion_analysis, 
                session_metrics,
                None  # No IntentClassification object in real-time mode
            )
            
            # Check if session summary already exists
            existing_summary_query = text("""
                SELECT id FROM session_summaries WHERE id = :session_id
            """)
            existing = db.execute(existing_summary_query, {"session_id": session_id}).fetchone()
            
            if existing:
                # Update existing summary
                update_query = text("""
                    UPDATE session_summaries SET
                        ended_at = :ended_at,
                        duration_seconds = :duration_seconds,
                        total_interactions = :total_interactions,
                        primary_intent = :primary_intent,
                        intent_confidence = :intent_confidence,
                        workflow_completed = :workflow_completed,
                        drop_off_step = :drop_off_step,
                        total_tokens = :total_tokens,
                        avg_response_time_ms = :avg_response_time_ms,
                        errors_count = :errors_count,
                        success_score = :success_score
                    WHERE id = :session_id
                """)
                
                db.execute(update_query, {
                    "session_id": session_id,
                    "ended_at": parsed_interactions[-1].timestamp,
                    "duration_seconds": int((parsed_interactions[-1].timestamp - parsed_interactions[0].timestamp).total_seconds()),
                    "total_interactions": len(parsed_interactions),
                    "primary_intent": primary_intent,
                    "intent_confidence": intent_confidence,
                    "workflow_completed": completion_analysis["completed"],
                    "drop_off_step": completion_analysis["drop_off_step"],
                    "total_tokens": session_metrics["total_tokens"],
                    "avg_response_time_ms": session_metrics["avg_response_time"],
                    "errors_count": session_metrics["error_count"],
                    "success_score": success_score
                })
            else:
                # Create new summary
                insert_query = text("""
                    INSERT INTO session_summaries 
                    (id, started_at, ended_at, duration_seconds, total_interactions,
                     primary_intent, intent_confidence, workflow_completed, drop_off_step,
                     total_tokens, avg_response_time_ms, errors_count, success_score)
                    VALUES (:session_id, :started_at, :ended_at, :duration_seconds, :total_interactions,
                            :primary_intent, :intent_confidence, :workflow_completed, :drop_off_step,
                            :total_tokens, :avg_response_time_ms, :errors_count, :success_score)
                """)
                
                db.execute(insert_query, {
                    "session_id": session_id,
                    "started_at": parsed_interactions[0].timestamp,
                    "ended_at": parsed_interactions[-1].timestamp,
                    "duration_seconds": int((parsed_interactions[-1].timestamp - parsed_interactions[0].timestamp).total_seconds()),
                    "total_interactions": len(parsed_interactions),
                    "primary_intent": primary_intent,
                    "intent_confidence": intent_confidence,
                    "workflow_completed": completion_analysis["completed"],
                    "drop_off_step": completion_analysis["drop_off_step"],
                    "total_tokens": session_metrics["total_tokens"],
                    "avg_response_time_ms": session_metrics["avg_response_time"],
                    "errors_count": session_metrics["error_count"],
                    "success_score": success_score
                })
            
        except Exception as e:
            # Log error but don't raise - real-time updates should be best effort
            print(f"⚠️  Failed to update session summary for {session_id}: {e}")
    
    def _analyze_workflow_path(self, interactions: List[ParsedInteraction]) -> WorkflowPath:
        """Analyze the workflow path through the conversation"""
        
        steps = []
        tools_used = []
        decision_points = []
        success_indicators = []
        failure_points = []
        
        for i, interaction in enumerate(interactions):
            step_number = i + 1
            
            # Classify conversation steps
            step_type = self._classify_conversation_step(interaction, step_number)
            steps.append(step_type)
            
            # Track tool usage
            if interaction.tool_calls:
                tools_used.extend(interaction.tool_calls)
            
            # Identify decision points (questions, confirmations, choices)
            if self._is_decision_point(interaction):
                decision_points.append({
                    "step": step_number,
                    "type": self._get_decision_type(interaction),
                    "user_input": interaction.user_input,
                    "agent_response": interaction.agent_response
                })
            
            # Identify success indicators
            if self._has_success_indicators(interaction):
                success_indicators.append(f"step_{step_number}: {self._extract_success_indicator(interaction)}")
            
            # Identify failure points
            if interaction.error_occurred or self._has_failure_indicators(interaction):
                failure_points.append(f"step_{step_number}: {interaction.error_message or 'implicit failure'}")
        
        return WorkflowPath(
            steps=steps,
            tools_used=list(set(tools_used)),  # Deduplicate
            decision_points=decision_points,
            success_indicators=success_indicators,
            failure_points=failure_points
        )
    
    def _classify_conversation_step(self, interaction: ParsedInteraction, step_number: int) -> str:
        """Classify what type of step this is in the conversation"""
        
        user_input = interaction.user_input.lower()
        agent_response = interaction.agent_response.lower()
        
        # First interaction is always greeting/problem_statement
        if step_number == 1:
            return "initial_request"
        
        # Look for specific patterns
        if any(word in agent_response for word in ["clarify", "understand", "tell me more"]):
            return "information_gathering"
        
        if any(word in agent_response for word in ["let me", "i'll", "i can", "processing"]):
            return "action_execution"
        
        if any(word in agent_response for word in ["completed", "done", "finished", "resolved"]):
            return "resolution"
        
        if any(word in user_input for word in ["yes", "no", "ok", "sure", "correct"]):
            return "confirmation"
        
        if any(word in user_input for word in ["help", "explain", "how", "what", "why"]):
            return "clarification_request"
        
        if interaction.error_occurred:
            return "error_handling"
        
        return "dialogue_continuation"
    
    def _is_decision_point(self, interaction: ParsedInteraction) -> bool:
        """Check if this interaction represents a decision point"""
        
        agent_response = interaction.agent_response.lower()
        
        # Look for questions, choices, confirmations
        decision_indicators = [
            "?", "would you like", "do you want", "choose", "select", 
            "confirm", "verify", "which option", "prefer"
        ]
        
        return any(indicator in agent_response for indicator in decision_indicators)
    
    def _get_decision_type(self, interaction: ParsedInteraction) -> str:
        """Classify the type of decision being made"""
        
        agent_response = interaction.agent_response.lower()
        
        if any(word in agent_response for word in ["confirm", "verify", "correct"]):
            return "confirmation"
        elif any(word in agent_response for word in ["choose", "select", "option"]):
            return "selection"
        elif "?" in agent_response:
            return "information_request"
        else:
            return "general_decision"
    
    def _has_success_indicators(self, interaction: ParsedInteraction) -> bool:
        """Check if interaction contains success indicators"""
        
        agent_response = interaction.agent_response.lower()
        user_input = interaction.user_input.lower()
        
        success_words = [
            "completed", "successful", "resolved", "done", "finished",
            "thank you", "thanks", "perfect", "great", "excellent"
        ]
        
        return any(word in agent_response or word in user_input for word in success_words)
    
    def _extract_success_indicator(self, interaction: ParsedInteraction) -> str:
        """Extract specific success indicator from interaction"""
        
        response_lower = interaction.agent_response.lower()
        
        if "completed" in response_lower:
            return "task_completed"
        elif "resolved" in response_lower:
            return "issue_resolved"
        elif "successful" in response_lower:
            return "operation_successful"
        elif any(word in interaction.user_input.lower() for word in ["thank", "perfect", "great"]):
            return "user_satisfaction"
        else:
            return "positive_outcome"
    
    def _has_failure_indicators(self, interaction: ParsedInteraction) -> bool:
        """Check if interaction contains failure indicators"""
        
        agent_response = interaction.agent_response.lower()
        user_input = interaction.user_input.lower()
        
        failure_words = [
            "sorry", "unable", "cannot", "failed", "error", "problem",
            "frustrated", "angry", "disappointed", "doesn't work", "broken"
        ]
        
        return any(word in agent_response or word in user_input for word in failure_words)
    
    def _analyze_completion_status(
        self, 
        interactions: List[ParsedInteraction], 
        workflow_path: WorkflowPath
    ) -> Dict[str, Any]:
        """Analyze whether the session completed successfully"""
        
        # Check explicit completion indicators
        last_interaction = interactions[-1]
        
        # Strong completion signals
        completion_signals = [
            "resolved", "completed", "done", "finished", "thank you",
            "that helps", "perfect", "exactly what i needed"
        ]
        
        explicit_completion = any(
            signal in last_interaction.agent_response.lower() or 
            signal in last_interaction.user_input.lower()
            for signal in completion_signals
        )
        
        # Check for natural conversation ending
        natural_ending = self._appears_naturally_concluded(interactions)
        
        # Check for positive sentiment in final exchanges
        positive_ending = self._has_positive_ending_sentiment(interactions[-2:])
        
        # Check for unresolved issues or user dissatisfaction
        unresolved_issues = any(
            word in last_interaction.user_input.lower()
            for word in ["still", "but", "however", "not working", "doesn't help"]
        )
        
        # Analyze drop-off patterns
        drop_off_step = None
        if not (explicit_completion or natural_ending):
            drop_off_step = self._detect_drop_off_point(interactions, workflow_path)
        
        # Determine overall completion
        completed = (
            explicit_completion or 
            (natural_ending and positive_ending and not unresolved_issues)
        )
        
        return {
            "completed": completed,
            "drop_off_step": drop_off_step,
            "completion_indicators": {
                "explicit_completion": explicit_completion,
                "natural_ending": natural_ending,
                "positive_ending": positive_ending,
                "unresolved_issues": unresolved_issues
            }
        }
    
    def _appears_naturally_concluded(self, interactions: List[ParsedInteraction]) -> bool:
        """Check if conversation appears to have naturally concluded"""
        
        if len(interactions) < 2:
            return False
        
        # Check final exchanges for conclusion patterns
        final_exchanges = interactions[-2:]
        
        # Look for wrapping up language
        conclusion_patterns = [
            "anything else", "help you with", "is there anything",
            "that's all", "all set", "we're done"
        ]
        
        return any(
            pattern in interaction.agent_response.lower()
            for interaction in final_exchanges
            for pattern in conclusion_patterns
        )
    
    def _has_positive_ending_sentiment(self, final_interactions: List[ParsedInteraction]) -> bool:
        """Check if final interactions have positive sentiment"""
        
        positive_words = ["thank", "great", "perfect", "helpful", "appreciate", "excellent"]
        negative_words = ["frustrated", "disappointed", "useless", "terrible", "awful"]
        
        positive_count = 0
        negative_count = 0
        
        for interaction in final_interactions:
            text = (interaction.user_input + " " + interaction.agent_response).lower()
            positive_count += sum(1 for word in positive_words if word in text)
            negative_count += sum(1 for word in negative_words if word in text)
        
        return positive_count > negative_count
    
    def _detect_drop_off_point(
        self, 
        interactions: List[ParsedInteraction], 
        workflow_path: WorkflowPath
    ) -> Optional[int]:
        """Detect where in the workflow the user dropped off"""
        
        # Look for signs of user disengagement
        for i, interaction in enumerate(interactions):
            step_number = i + 1
            
            # Very short user responses may indicate disengagement
            if len(interaction.user_input.strip()) < 10 and step_number > 1:
                return step_number
            
            # User expressing frustration
            if any(word in interaction.user_input.lower() 
                   for word in ["frustrated", "forget it", "never mind", "this isn't working"]):
                return step_number
            
            # Agent unable to help
            if any(phrase in interaction.agent_response.lower()
                   for phrase in ["unable to help", "can't assist", "need to transfer"]):
                return step_number + 1  # User likely dropped off after this
        
        # If no explicit drop-off detected but conversation seems incomplete
        if len(interactions) > 1:
            last_step_type = workflow_path.steps[-1] if workflow_path.steps else None
            if last_step_type in ["information_gathering", "action_execution"]:
                return len(interactions)  # Dropped off during process
        
        return None
    
    def _calculate_session_metrics(self, interactions: List[ParsedInteraction]) -> Dict[str, Any]:
        """Calculate aggregate session metrics"""
        
        total_tokens = sum(
            interaction.tokens_used or 50  # Default if missing
            for interaction in interactions
        )
        
        response_times = [
            interaction.response_time_ms
            for interaction in interactions
            if interaction.response_time_ms
        ]
        
        avg_response_time = statistics.mean(response_times) if response_times else 1000.0
        
        error_count = sum(
            1 for interaction in interactions
            if interaction.error_occurred
        )
        
        return {
            "total_tokens": total_tokens,
            "avg_response_time": avg_response_time,
            "error_count": error_count,
            "interaction_count": len(interactions)
        }
    
    def _calculate_success_score(
        self,
        interactions: List[ParsedInteraction],
        completion_analysis: Dict[str, Any],
        session_metrics: Dict[str, Any],
        intent_classification: Optional[IntentClassification]
    ) -> float:
        """Calculate overall session success score (0.0 - 1.0)"""
        
        score = 0.5  # Base score
        
        # Completion bonus (+0.3)
        if completion_analysis["completed"]:
            score += 0.3
        
        # Positive ending bonus (+0.1)
        if completion_analysis["completion_indicators"]["positive_ending"]:
            score += 0.1
        
        # Penalty for errors (-0.1 per error, max -0.3)
        error_penalty = min(0.3, session_metrics["error_count"] * 0.1)
        score -= error_penalty
        
        # Penalty for drop-off (-0.2)
        if completion_analysis["drop_off_step"]:
            score -= 0.2
        
        # Penalty for unresolved issues (-0.15)
        if completion_analysis["completion_indicators"]["unresolved_issues"]:
            score -= 0.15
        
        # Efficiency bonus/penalty based on interaction count
        interaction_count = session_metrics["interaction_count"]
        if intent_classification:
            expected_complexity = {
                "low": 3, "medium": 5, "high": 7
            }
            intent_details = IntentClassifier.INTENT_CATEGORIES.get(
                intent_classification.primary_intent, {}
            )
            expected_interactions = expected_complexity.get(
                intent_details.get("complexity", "medium"), 5
            )
            
            # Efficiency score based on how close to expected length
            if interaction_count <= expected_interactions:
                score += 0.1  # Efficient resolution
            elif interaction_count > expected_interactions * 1.5:
                score -= 0.1  # Inefficient, too many back-and-forth
        
        # Response time penalty for very slow responses
        avg_response_time = session_metrics["avg_response_time"]
        if avg_response_time > 3000:  # > 3 seconds
            score -= 0.05
        
        # Ensure score is between 0.0 and 1.0
        return max(0.0, min(1.0, round(score, 2)))


    def build_session_summary(self, agent_log: AgentLog) -> None:
        """Build or update session data when a session ends. Uses SessionLocal internally."""
        if not getattr(agent_log, 'session_ended', False):
            return
        _SessionLocal = SessionLocal or _get_session_local()
        with _SessionLocal() as db:
            logs = db.query(AgentLog).filter(AgentLog.session_id == agent_log.session_id).all()
            if not logs:
                return
            # SessionSummary removed in MVP rewrite — session data served via db/queries.py

    def _create_session_summary(self, session_id: str, logs: list) -> "SessionSummaryData":
        """Create a SessionSummaryData from a list of AgentLog objects."""
        completed = any(getattr(log, 'session_ended', False) for log in logs)
        max_step = max((getattr(log, 'workflow_step', 0) or 0) for log in logs) if logs else 0
        drop_off_step = max_step if not completed else None
        workflow_path = " > ".join(
            f"step_{getattr(log, 'workflow_step', i + 1)}" for i, log in enumerate(logs)
        )
        return SessionSummaryData(
            session_id=session_id,
            total_interactions=len(logs),
            completed=completed,
            drop_off_step=drop_off_step,
            workflow_path=workflow_path,
        )


@dataclass
class SessionSummaryData:
    """Lightweight data container for session summary results"""
    session_id: str
    total_interactions: int
    completed: bool
    drop_off_step: Optional[int]
    workflow_path: str


class BatchSessionBuilder:
    """Build multiple sessions efficiently"""
    
    def __init__(self, session_builder: SessionBuilder):
        self.session_builder = session_builder
    
    async def build_sessions_from_parsed_data(
        self, 
        parsed_interactions: List[ParsedInteraction]
    ) -> Tuple[List[SessionSummary], List[AgentLog]]:
        """Build sessions from a list of parsed interactions"""
        
        # Group interactions by session_id
        sessions_data = {}
        for interaction in parsed_interactions:
            session_id = interaction.session_id
            if session_id not in sessions_data:
                sessions_data[session_id] = []
            sessions_data[session_id].append(interaction)
        
        all_summaries = []
        all_logs = []
        
        print(f"📊 Building {len(sessions_data)} sessions from parsed data...")
        
        for i, (session_id, interactions) in enumerate(sessions_data.items()):
            try:
                summary, logs = await self.session_builder.build_session_summary(
                    session_id, interactions
                )
                all_summaries.append(summary)
                all_logs.extend(logs)
                
                if i % 10 == 0 and i > 0:
                    print(f"   Built {i}/{len(sessions_data)} sessions...")
                
            except Exception as e:
                print(f"⚠️  Failed to build session {session_id}: {e}")
                continue
        
        print(f"✅ Successfully built {len(all_summaries)} sessions with {len(all_logs)} interactions")
        
        return all_summaries, all_logs