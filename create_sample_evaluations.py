"""
Create sample evaluation data to demonstrate pattern analysis system
Generates realistic failure patterns for testing Day 5 functionality
"""

import uuid
import random
from datetime import datetime, timedelta
from api.database import SessionLocal
from db.models import AgentLog, EvalResult


def create_sample_evaluations():
    """Create sample evaluation data based on existing agent logs"""
    
    db = SessionLocal()
    
    try:
        # Get agent logs for evaluation
        logs = db.query(AgentLog).limit(100).all()  # Take first 100 for quick demo
        
        print(f"Creating evaluations for {len(logs)} agent logs...")
        
        evaluations_created = 0
        
        for log in logs:
            # Create realistic evaluation based on intent and step
            overall_score = _generate_realistic_score(log)
            
            # Only create evaluation if it would be a "failure" (< 0.7) for pattern detection
            if overall_score < 0.7:
                eval_result = EvalResult(
                    id=str(uuid.uuid4()),
                    agent_log_id=log.id,
                    evaluated_at=datetime.now() - timedelta(hours=random.randint(1, 24)),
                    accuracy_score=_generate_score_component(overall_score, 0.1),
                    relevance_score=_generate_score_component(overall_score, 0.1),
                    helpfulness_score=_generate_score_component(overall_score, 0.1),
                    goal_alignment_score=_generate_score_component(overall_score, 0.1),
                    overall_score=overall_score,
                    evaluation_reasoning=_generate_failure_reasoning(log, overall_score),
                    improvement_suggestions='{"suggestions": ["Improve response accuracy", "Better intent understanding"]}',
                    evaluator_model="claude-3-sonnet-test",
                    evaluation_version="1.0"
                )
                
                db.add(eval_result)
                evaluations_created += 1
        
        db.commit()
        print(f"✅ Created {evaluations_created} evaluation records")
        
        return evaluations_created
        
    except Exception as e:
        db.rollback()
        print(f"❌ Failed to create evaluations: {e}")
        return 0
        
    finally:
        db.close()


def _generate_realistic_score(log: AgentLog) -> float:
    """Generate realistic overall score based on log characteristics"""
    
    # Different failure patterns based on intent and step
    intent = log.intent or "unknown"
    step = log.workflow_step or 1
    
    if intent == "billing":
        if step >= 3:
            return random.uniform(0.2, 0.6)  # Often fails at step 3+ (tool failures)
        else:
            return random.uniform(0.6, 0.9)  # Usually OK early on
    
    elif intent == "refunds":
        if step >= 2:
            return random.uniform(0.3, 0.6)  # Policy confusion
        else:
            return random.uniform(0.7, 0.9)
    
    elif intent == "account_recovery":
        return random.uniform(0.4, 0.8)  # Security complexity causes issues
        
    elif intent == "subscriptions":
        if step == 1:
            return random.uniform(0.8, 0.95)  # Good initial responses
        else:
            return random.uniform(0.5, 0.7)  # Cancellation complexity
    
    else:  # general_inquiry
        return random.uniform(0.7, 0.9)  # Usually handles well


def _generate_score_component(overall: float, variance: float) -> float:
    """Generate individual score component around overall score"""
    component = overall + random.uniform(-variance, variance)
    return max(0.0, min(1.0, component))


def _generate_failure_reasoning(log: AgentLog, score: float) -> str:
    """Generate realistic failure reasoning"""
    
    intent = log.intent or "unknown"
    step = log.workflow_step or 1
    
    if score < 0.4:  # Severe failures
        if intent == "billing" and step >= 3:
            return "tool_failure - billing API timeout prevented account access"
        elif intent == "refunds":
            return "wrong_answer - incorrect refund policy information provided"
        elif intent == "account_recovery":
            return "incomplete - security verification process not completed"
        else:
            return "goal_drift - agent lost track of user's primary objective"
    
    elif score < 0.6:  # Moderate failures
        if intent == "billing":
            return "incomplete - billing explanation lacked specific charge details"
        elif intent == "subscriptions":
            return "tool_failure - subscription management API returned error"
        else:
            return "context_loss - agent forgot previous conversation details"
    
    else:  # Minor failures (0.6-0.7)
        return "decision_quality - suboptimal process choice but functional outcome"


if __name__ == "__main__":
    print("🔧 Creating sample evaluation data for pattern analysis...")
    count = create_sample_evaluations()
    print(f"🎯 Ready to test pattern analysis with {count} failure examples")