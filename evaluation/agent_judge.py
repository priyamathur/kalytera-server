"""
AgentJudge - LLM-powered evaluation engine for agent conversations
Core IP: Sophisticated evaluation using Claude with 4-dimensional scoring and failure taxonomy
"""

import json
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import uuid
from dataclasses import dataclass
from sqlalchemy.orm import Session
from sqlalchemy import text

from db.models import EvalResult
from evaluation.judge_prompts import build_evaluation_prompt
from api.security import optimized_claude_client, key_manager


@dataclass
class EvaluationRequest:
    """Single evaluation request"""
    log_id: str
    user_input: str
    agent_response: str
    conversation_context: List[Dict[str, Any]]
    tool_results: Optional[str]
    intent: Optional[str]
    session_id: str


@dataclass
class EvaluationResult:
    """Evaluation result from Claude judge"""
    log_id: str
    accuracy_score: float
    goal_alignment_score: float
    decision_quality_score: float
    completeness_score: float
    overall_score: float
    primary_failure_mode: Optional[str]
    failure_reasoning: Optional[str]
    specific_issues: List[str]
    improvement_suggestions: List[str]
    confidence_level: float
    evaluation_timestamp: datetime
    evaluator_model: str


class AgentJudge:
    """
    LLM-powered agent conversation evaluator
    
    Features:
    - 4-dimensional scoring (accuracy, goal_alignment, decision_quality, completeness)
    - 7-category failure taxonomy (wrong_answer, tool_failure, goal_drift, etc.)
    - Batch processing for efficiency
    - Context-aware evaluation using conversation history
    - Intent-specific specialized prompts
    """
    
    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-haiku-20240307"):
        """Initialize AgentJudge with secure Claude API"""
        self.key_manager = key_manager
        self.claude_client = optimized_claude_client
        self.judge_available = key_manager.is_available
        self.evaluation_version = "2.0_optimized"
        self.model = model  # Store model for reference
        
        if self.judge_available:
            print(f"✅ Secure AgentJudge initialized (key: {key_manager.get_masked_key()})")
        else:
            print("⚠️  Claude API unavailable - using fallback evaluation")
    
    async def evaluate_interaction(
        self, 
        user_input: str,
        agent_response: str,
        conversation_context: Optional[List[Dict[str, Any]]] = None,
        tool_results: Optional[str] = None,
        intent: Optional[str] = None,
        session_id: Optional[str] = None,
        log_id: Optional[str] = None
    ) -> EvaluationResult:
        """
        Evaluate a single agent interaction
        
        Args:
            user_input: User's message
            agent_response: Agent's response
            conversation_context: Previous conversation steps for context
            tool_results: Results from tool/API calls
            intent: Classified user intent
            
        Returns:
            EvaluationResult with scores and failure analysis
        """
        
        # Build evaluation prompt
        prompt = build_evaluation_prompt(
            user_input=user_input,
            agent_response=agent_response,
            conversation_context=conversation_context or [],
            tool_results=tool_results,
            intent=intent
        )
        
        try:
            # Call Claude for evaluation
            response = self.claude_client.messages.create(
                model=self.model,
                max_tokens=2000,
                temperature=0.1,  # Low temperature for consistent scoring
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            # Parse Claude's response
            result = self._parse_evaluation_response(response.content[0].text)
            result.evaluation_timestamp = datetime.now()
            result.evaluator_model = self.model
            
            return result
            
        except Exception as e:
            print(f"⚠️  Evaluation failed: {e}")
            # Return fallback evaluation
            return self._create_fallback_evaluation()
    
    async def evaluate_batch(
        self, 
        requests: List[EvaluationRequest],
        batch_size: int = 10
    ) -> List[EvaluationResult]:
        """
        Evaluate multiple interactions in batches for efficiency
        
        Args:
            requests: List of evaluation requests
            batch_size: Number of concurrent evaluations (max 10 for API limits)
            
        Returns:
            List of evaluation results
        """
        
        results = []
        
        # Process in batches to respect API rate limits
        for i in range(0, len(requests), batch_size):
            batch = requests[i:i + batch_size]
            
            # Create concurrent evaluation tasks
            tasks = []
            for req in batch:
                task = self.evaluate_interaction(
                    user_input=req.user_input,
                    agent_response=req.agent_response,
                    conversation_context=req.conversation_context,
                    tool_results=req.tool_results,
                    intent=req.intent
                )
                tasks.append(task)
            
            # Execute batch concurrently
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results and handle exceptions
            for j, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    print(f"⚠️  Evaluation failed for request {i+j}: {result}")
                    result = self._create_fallback_evaluation()
                
                # Set log_id from request
                result.log_id = batch[j].log_id
                results.append(result)
            
            # Rate limiting pause between batches
            if i + batch_size < len(requests):
                await asyncio.sleep(1)
        
        return results
    
    async def evaluate_new_logs(self, db: Session, hours_back: float = 0.5) -> List[EvaluationResult]:
        """
        Find and evaluate new agent logs that haven't been evaluated yet
        
        Args:
            db: Database session
            hours_back: How far back to look for new logs (hours)
            
        Returns:
            List of evaluation results for new logs
        """
        
        # Find logs that need evaluation
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        
        query = text("""
            SELECT 
                al.id,
                al.session_id,
                al.user_input,
                al.agent_response,
                al.intent,
                al.tool_calls,
                al.timestamp,
                al.workflow_step
            FROM agent_logs al
            LEFT JOIN eval_results er ON al.id = er.agent_log_id
            WHERE er.id IS NULL 
            AND al.timestamp >= :cutoff_time
            ORDER BY al.timestamp ASC
        """)
        
        logs_to_evaluate = db.execute(query, {'cutoff_time': cutoff_time}).fetchall()
        
        if not logs_to_evaluate:
            print(f"📊 No new logs to evaluate in last {hours_back} hours")
            return []
        
        print(f"📊 Found {len(logs_to_evaluate)} new logs to evaluate")
        
        # Build evaluation requests with context
        evaluation_requests = []
        
        for log in logs_to_evaluate:
            # Get conversation context (last 3 steps before current)
            context = self._get_conversation_context(
                db, log.session_id, log.workflow_step, context_steps=3
            )
            
            request = EvaluationRequest(
                log_id=log.id,
                user_input=log.user_input,
                agent_response=log.agent_response,
                conversation_context=context,
                tool_results=log.tool_calls,
                intent=log.intent,
                session_id=log.session_id
            )
            
            evaluation_requests.append(request)
        
        # Run batch evaluation
        results = await self.evaluate_batch(evaluation_requests)
        
        # Store results in database
        self._store_evaluation_results(db, results)
        
        print(f"✅ Completed evaluation of {len(results)} interactions")
        
        return results
    
    def _get_conversation_context(
        self, 
        db: Session, 
        session_id: str, 
        current_step: int, 
        context_steps: int = 3
    ) -> List[Dict[str, Any]]:
        """Get conversation context for evaluation"""
        
        query = text("""
            SELECT user_input, agent_response, workflow_step
            FROM agent_logs 
            WHERE session_id = :session_id 
            AND workflow_step < :current_step
            ORDER BY workflow_step DESC
            LIMIT :context_steps
        """)
        
        context_rows = db.execute(query, {
            'session_id': session_id,
            'current_step': current_step,
            'context_steps': context_steps
        }).fetchall()
        
        # Reverse to get chronological order
        context = []
        for row in reversed(context_rows):
            context.append({
                'user_input': row.user_input,
                'agent_response': row.agent_response,
                'workflow_step': row.workflow_step
            })
        
        return context
    
    def _parse_evaluation_response(self, response_text: str) -> EvaluationResult:
        """Parse Claude's JSON evaluation response"""
        
        try:
            # Extract JSON from response
            response_text = response_text.strip()
            
            # Find JSON block
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}') + 1
            
            if start_idx >= 0 and end_idx > start_idx:
                json_str = response_text[start_idx:end_idx]
                result_data = json.loads(json_str)
            else:
                raise ValueError("No JSON found in response")
            
            # Parse into EvaluationResult
            return EvaluationResult(
                log_id="",  # Will be set by caller
                accuracy_score=float(result_data.get('accuracy_score', 0.5)),
                goal_alignment_score=float(result_data.get('goal_alignment_score', 0.5)),
                decision_quality_score=float(result_data.get('decision_quality_score', 0.5)),
                completeness_score=float(result_data.get('completeness_score', 0.5)),
                overall_score=float(result_data.get('overall_score', 0.5)),
                primary_failure_mode=result_data.get('primary_failure_mode'),
                failure_reasoning=result_data.get('failure_reasoning'),
                specific_issues=result_data.get('specific_issues', []),
                improvement_suggestions=result_data.get('improvement_suggestions', []),
                confidence_level=float(result_data.get('confidence_level', 0.8)),
                evaluation_timestamp=datetime.now(),
                evaluator_model=self.model
            )
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"⚠️  Failed to parse evaluation response: {e}")
            print(f"Raw response: {response_text[:200]}...")
            return self._create_fallback_evaluation()
    
    def _create_fallback_evaluation(self) -> EvaluationResult:
        """Create fallback evaluation when Claude evaluation fails"""
        
        return EvaluationResult(
            log_id="",
            accuracy_score=0.5,
            goal_alignment_score=0.5,
            decision_quality_score=0.5,
            completeness_score=0.5,
            overall_score=0.5,
            primary_failure_mode="evaluation_error",
            failure_reasoning="LLM evaluation failed, using fallback scores",
            specific_issues=["Evaluation system error"],
            improvement_suggestions=["Retry evaluation with working system"],
            confidence_level=0.1,
            evaluation_timestamp=datetime.now(),
            evaluator_model=self.model
        )
    
    def _store_evaluation_results(self, db: Session, results: List[EvaluationResult]):
        """Store evaluation results in database"""
        
        for result in results:
            eval_record = EvalResult(
                id=str(uuid.uuid4()),
                agent_log_id=result.log_id,
                evaluated_at=result.evaluation_timestamp,
                accuracy_score=result.accuracy_score,
                relevance_score=result.goal_alignment_score,  # Map to existing schema
                helpfulness_score=result.completeness_score,
                goal_alignment_score=result.decision_quality_score,
                overall_score=result.overall_score,
                evaluation_reasoning=result.failure_reasoning,
                improvement_suggestions=json.dumps(result.improvement_suggestions),
                evaluator_model=result.evaluator_model,
                evaluation_version=self.evaluation_version
            )
            
            db.add(eval_record)
        
        db.commit()
    
    def get_evaluation_summary(self, db: Session, hours_back: int = 24) -> Dict[str, Any]:
        """Get summary of recent evaluations"""
        
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        
        query = text("""
            SELECT 
                COUNT(*) as total_evaluations,
                AVG(overall_score) as avg_overall_score,
                AVG(accuracy_score) as avg_accuracy,
                AVG(goal_alignment_score) as avg_goal_alignment,
                AVG(relevance_score) as avg_relevance,
                AVG(helpfulness_score) as avg_helpfulness,
                SUM(CASE WHEN overall_score < 0.7 THEN 1 ELSE 0 END) as low_quality_count
            FROM eval_results er
            JOIN agent_logs al ON er.agent_log_id = al.id
            WHERE er.evaluated_at >= :cutoff_time
        """)
        
        result = db.execute(query, {'cutoff_time': cutoff_time}).fetchone()
        
        if result and result.total_evaluations > 0:
            return {
                'total_evaluations': result.total_evaluations,
                'avg_overall_score': round(result.avg_overall_score, 3),
                'avg_accuracy': round(result.avg_accuracy, 3),
                'avg_goal_alignment': round(result.avg_goal_alignment, 3),
                'avg_relevance': round(result.avg_relevance, 3),
                'avg_helpfulness': round(result.avg_helpfulness, 3),
                'low_quality_count': result.low_quality_count,
                'quality_rate': round((result.total_evaluations - result.low_quality_count) / result.total_evaluations, 3),
                'evaluation_period_hours': hours_back,
                'last_updated': datetime.now().isoformat()
            }
        else:
            return {
                'total_evaluations': 0,
                'message': f'No evaluations found in last {hours_back} hours'
            }


class EvaluationScheduler:
    """Background scheduler for automated evaluation jobs"""
    
    def __init__(self, judge: AgentJudge, db_session_factory):
        self.judge = judge
        self.db_session_factory = db_session_factory
        self.is_running = False
    
    async def start_background_evaluation(self, interval_minutes: int = 30):
        """Start background evaluation job"""
        
        self.is_running = True
        print(f"🚀 Starting background evaluation job (every {interval_minutes} minutes)")
        
        while self.is_running:
            try:
                # Create new database session for this job
                db = self.db_session_factory()
                
                # Evaluate new logs
                results = await self.judge.evaluate_new_logs(db, hours_back=interval_minutes/60)
                
                if results:
                    print(f"📊 Background evaluation completed: {len(results)} interactions evaluated")
                    
                    # Log summary
                    summary = self.judge.get_evaluation_summary(db, hours_back=1)
                    print(f"🎯 Quality metrics: {summary.get('avg_overall_score', 'N/A')} avg score, "
                          f"{summary.get('quality_rate', 'N/A')} quality rate")
                
                db.close()
                
            except Exception as e:
                print(f"❌ Background evaluation error: {e}")
            
            # Wait for next cycle
            await asyncio.sleep(interval_minutes * 60)
    
    def stop_background_evaluation(self):
        """Stop background evaluation job"""
        self.is_running = False
        print("⏹️  Background evaluation job stopped")