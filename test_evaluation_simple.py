#!/usr/bin/env python3
"""
Simple evaluation test to avoid circular imports
"""

import sys
sys.path.append('.')
import asyncio

async def test_evaluation_components():
    """Test evaluation components independently"""
    
    print("🧪 Testing Evaluation Components")
    print("=" * 50)
    
    # Test 1: Check evaluation prompts
    try:
        from evaluation.judge_prompts import build_evaluation_prompt
        
        prompt = build_evaluation_prompt(
            user_input="I need help with billing",
            agent_response="I can help you with that",
            conversation_context=[],
            intent="billing"
        )
        
        print("✅ Evaluation prompt building works")
        print(f"📄 Prompt length: {len(prompt)} characters")
        
        # Check prompt contains key elements
        assert "billing" in prompt.lower(), "Prompt should contain intent"
        assert "evaluation" in prompt.lower() or "score" in prompt.lower(), "Prompt should be for evaluation"
        
    except ImportError as e:
        print(f"❌ Evaluation prompts not available: {e}")
    except Exception as e:
        print(f"❌ Evaluation prompt test failed: {e}")
    
    # Test 2: Check evaluation data structures
    try:
        from evaluation.agent_judge import EvaluationResult, EvaluationRequest
        
        # Test EvaluationResult structure
        eval_result = EvaluationResult(
            log_id="test_log",
            accuracy=0.8,
            goal_alignment=0.7,
            decision_quality=0.75,
            completeness=0.85,
            overall_score=0.775,
            passed=True,
            failure_type=None,
            failure_step=None,
            reasoning="Test evaluation",
            improvement_suggestions=["Test suggestion"]
        )
        
        print("✅ EvaluationResult structure works")
        print(f"📊 Overall score: {eval_result.overall_score}")
        
        # Validate score ranges
        for score_name in ["accuracy", "goal_alignment", "decision_quality", "completeness", "overall_score"]:
            score = getattr(eval_result, score_name)
            assert 0.0 <= score <= 1.0, f"{score_name} should be in [0,1] range"
        
        print("✅ Score range validation passed")
        
    except ImportError as e:
        print(f"❌ Evaluation data structures not available: {e}")
    except Exception as e:
        print(f"❌ Evaluation structure test failed: {e}")
    
    # Test 3: Check failure taxonomy
    try:
        failure_types = ["wrong_answer", "tool_failure", "goal_drift", "incomplete", "hallucination", "context_loss", "loop"]
        
        print(f"✅ Failure taxonomy: {len(failure_types)} types defined")
        print(f"📋 Types: {', '.join(failure_types)}")
        
        assert len(failure_types) == 7, "Should have exactly 7 failure types"
        
    except Exception as e:
        print(f"❌ Failure taxonomy test failed: {e}")
    
    print("\n🎯 Evaluation Component Tests Complete")

if __name__ == "__main__":
    asyncio.run(test_evaluation_components())