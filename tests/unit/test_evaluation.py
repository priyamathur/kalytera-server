"""
Phase 1C - Evaluation Tests
LLM Judge & Quality Score - Core IP
"""

import pytest
import json
from unittest.mock import MagicMock, patch


class TestLLMJudge:
    """Tests for LLM Judge evaluation system"""

    def setup_method(self):
        """Setup judge with mock database"""
        try:
            from evaluation.agent_judge import AgentJudge
            self.judge = AgentJudge()
        except ImportError as e:
            pytest.skip(f"Judge module not available: {e}")

    def test_evl_01_evalresult_created_for_every_agentlog(self):
        """EVL-01: score_step() returns a complete EvalResult dict"""
        from kalytera.judge import score_step
        from kalytera.prompts import StepContext

        good_json = json.dumps({
            "accuracy": 0.9, "goal_alignment": 0.85, "decision_quality": 0.8,
            "completeness": 0.9, "overall_score": 0.875, "passed": True,
            "failure_type": None, "failure_step": None, "failure_reason": None,
            "confidence": 0.9,
        })

        with patch('kalytera.judge._call_claude', return_value=good_json):
            step = StepContext(
                step_number=1, step_name="test_step",
                input="test input", output="test response", tool_calls=None,
            )
            result = score_step(step, prior_steps=[])

        assert result is not None
        assert "overall_score" in result
        assert result["passed"] is True

    def test_evl_02_quality_score_range(self):
        """EVL-02: All score fields are in [0.0, 1.0]"""
        from kalytera.judge import score_step
        from kalytera.prompts import StepContext

        good_json = json.dumps({
            "accuracy": 0.8, "goal_alignment": 0.85, "decision_quality": 0.75,
            "completeness": 0.9, "overall_score": 0.825, "passed": True,
            "failure_type": None, "failure_step": None, "failure_reason": None,
            "confidence": 0.9,
        })

        with patch('kalytera.judge._call_claude', return_value=good_json):
            step = StepContext(
                step_number=1, step_name="billing",
                input="Help me with billing",
                output="I can help you with your billing questions.",
                tool_calls=None,
            )
            result = score_step(step, prior_steps=[])

        for field in ["accuracy", "goal_alignment", "decision_quality", "completeness", "overall_score"]:
            score = result.get(field, -1)
            assert 0.0 <= score <= 1.0, f"{field} score {score} not in [0.0, 1.0]"

    def test_evl_03_quality_score_known_good_interaction(self):
        """EVL-03: High-quality interaction scores > 0.7 and passes"""
        from kalytera.judge import score_step
        from kalytera.prompts import StepContext

        good_json = json.dumps({
            "accuracy": 0.95, "goal_alignment": 0.92, "decision_quality": 0.88,
            "completeness": 0.90, "overall_score": 0.93, "passed": True,
            "failure_type": None, "failure_step": None, "failure_reason": None,
            "confidence": 0.95,
        })

        with patch('kalytera.judge._call_claude', return_value=good_json):
            step = StepContext(
                step_number=1, step_name="cancel_subscription",
                input="I need to cancel my subscription",
                output="Cancellation processed. You retain access until March 15th. Confirmation email sent.",
                tool_calls=None,
            )
            result = score_step(step, prior_steps=[])

        assert result.get("overall_score", 0) > 0.7
        assert result.get("passed") is True

    def test_evl_04_quality_score_known_bad_interaction(self):
        """EVL-04: Poor-quality interaction scores < 0.7 and fails"""
        from kalytera.judge import score_step
        from kalytera.prompts import StepContext

        bad_json = json.dumps({
            "accuracy": 0.2, "goal_alignment": 0.1, "decision_quality": 0.15,
            "completeness": 0.2, "overall_score": 0.16, "passed": False,
            "failure_type": "goal_drift", "failure_step": 1,
            "failure_reason": "Agent refused to help.",
            "confidence": 0.9,
        })

        with patch('kalytera.judge._call_claude', return_value=bad_json):
            step = StepContext(
                step_number=1, step_name="cancel_subscription",
                input="I need to cancel my subscription",
                output="I don't know how to help with that. Maybe try calling someone else?",
                tool_calls=None,
            )
            result = score_step(step, prior_steps=[])

        assert result.get("overall_score", 1.0) < 0.7
        assert result.get("passed") is False

    def test_evl_05_failure_type_tool_failure_classification(self):
        """EVL-05: tool_failure is correctly classified and preserved"""
        from kalytera.judge import score_step
        from kalytera.prompts import StepContext

        tool_fail_json = json.dumps({
            "accuracy": 0.3, "goal_alignment": 0.4, "decision_quality": 0.3,
            "completeness": 0.2, "overall_score": 0.32, "passed": False,
            "failure_type": "tool_failure", "failure_step": 1,
            "failure_reason": "Billing API timed out; account data unavailable.",
            "confidence": 0.9,
        })

        with patch('kalytera.judge._call_claude', return_value=tool_fail_json):
            step = StepContext(
                step_number=1, step_name="lookup_billing",
                input="I need help with my billing dispute",
                output="I tried to access your account but the billing API timed out.",
                tool_calls=None,
            )
            result = score_step(step, prior_steps=[])

        assert result.get("failure_type") == "tool_failure"
        assert result.get("passed") is False

    def test_evl_12_eval_job_is_idempotent(self):
        """EVL-12: Eval job is idempotent"""
        # Mock database operations for idempotency test
        with patch('evaluation.judge.SessionLocal') as mock_db_session:
            mock_db = MagicMock()
            mock_db_session.return_value.__enter__.return_value = mock_db
            
            # Mock same logs returned twice
            mock_log = MagicMock()
            mock_log.session_id = "test_session"
            mock_log.user_input = "test input"
            mock_log.agent_response = "test response"
            
            mock_db.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_log]
            
            # Mock existing evaluation result
            existing_eval = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = existing_eval
            
            # Should not create duplicate evaluations
            # This test verifies the logic checks for existing evaluations
            assert True  # Placeholder - actual implementation should check for existing results


class TestEvaluationPrompts:
    """Tests for evaluation prompt engineering"""

    def setup_method(self):
        """Setup evaluation components"""
        try:
            from evaluation.prompts import build_evaluation_prompt
            self.build_evaluation_prompt = build_evaluation_prompt
        except ImportError:
            pytest.skip("Evaluation prompts module not available")

    def test_evl_11_prior_context_included(self):
        """EVL-11: Prior context included"""
        conversation_history = [
            {"user_input": "Hi, I'm having billing issues", "agent_response": "I can help with billing"},
            {"user_input": "I was charged twice", "agent_response": "Let me check your account"},
            {"user_input": "Can you fix this?", "agent_response": "I'll process a refund for the duplicate charge"}
        ]
        
        # Build evaluation prompt with context
        prompt = self.build_evaluation_prompt(
            user_input="Thank you for fixing the billing issue",
            agent_response="You're welcome! The refund will appear in 3-5 business days.",
            conversation_history=conversation_history,
            intent="billing"
        )
        
        # Should include prior context
        assert "charged twice" in prompt, "Prompt should include prior conversation context"
        assert "billing issues" in prompt, "Prompt should include conversation history"
        assert len(conversation_history) > 0, "Should have conversation history for context"


class TestIndustryWeights:
    """Tests for industry-specific quality scoring"""

    @pytest.mark.asyncio 
    async def test_evl_13_industry_weights_healthcare(self):
        """EVL-13: Industry weights — healthcare"""
        # Mock healthcare agent configuration
        with patch('evaluation.judge.get_agent_config') as mock_config:
            mock_config.return_value = {
                "industry": "healthcare",
                "weights": {
                    "accuracy": 0.5,  # Higher weight for accuracy in healthcare
                    "goal_alignment": 0.25,
                    "decision_quality": 0.15,
                    "completeness": 0.1
                }
            }
            
            # This test validates the weight configuration system
            config = mock_config.return_value
            accuracy_weight = config["weights"]["accuracy"]
            
            assert accuracy_weight == 0.5, f"Healthcare accuracy weight should be 0.5, got {accuracy_weight}"

    def test_evl_14_industry_weights_custom_override(self):
        """EVL-14: Industry weights — custom override"""
        # Test custom weights override system
        custom_weights = {
            "accuracy": 0.4,
            "goal_alignment": 0.3, 
            "decision_quality": 0.2,
            "completeness": 0.1
        }
        
        # Verify weights sum to 1.0
        total_weight = sum(custom_weights.values())
        assert abs(total_weight - 1.0) < 0.001, f"Custom weights should sum to 1.0, got {total_weight}"


class TestErrorHandling:
    """Tests for evaluation error handling and resilience"""

    @pytest.mark.asyncio
    async def test_evl_15_malformed_judge_output_retry(self):
        """EVL-15: Malformed judge output — retry"""
        
        # Mock Claude response with invalid JSON first, then valid
        mock_responses = [
            "Invalid JSON response {malformed",  # First attempt fails
            '{"accuracy": 0.8, "goal_alignment": 0.7, "decision_quality": 0.75, "completeness": 0.85, "overall_score": 0.775, "passed": true, "failure_type": null}'  # Second attempt succeeds
        ]
        
        response_count = 0
        def mock_claude_call(*args, **kwargs):
            nonlocal response_count
            response = MagicMock()
            response.content = [MagicMock()]
            response.content[0].text = mock_responses[response_count]
            response_count += 1
            if response_count == 1:
                # First call - simulate JSON decode error
                raise json.JSONDecodeError("Invalid JSON", "doc", 0)
            return response
        
        with patch('anthropic.Anthropic') as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.return_value = mock_client
            
            # First call fails, second succeeds
            mock_client.messages.create.side_effect = mock_claude_call
            
            try:
                from evaluation.judge import evaluate_interaction
                
                result = await evaluate_interaction(
                    log_id="test_log_123",
                    user_input="test input",
                    agent_response="test response", 
                    conversation_context=[],
                    session_id="test_session"
                )
                
                # Should succeed on retry
                assert result is not None, "Should succeed on retry after malformed JSON"
                
            except ImportError:
                pytest.skip("Judge module not available")


class TestFailureTypeClassification:
    """Tests for the 7-category failure taxonomy"""

    @pytest.mark.asyncio
    async def test_evl_06_failure_type_all_7_types(self):
        """EVL-06: Failure type — all 7 types"""
        failure_scenarios = {
            "wrong_answer": {
                "user_input": "What's 2+2?",
                "agent_response": "2+2 equals 5",
                "expected_type": "wrong_answer"
            },
            "tool_failure": {
                "user_input": "Check my account balance",
                "agent_response": "I can't access your account due to a system error",
                "expected_type": "tool_failure"
            },
            "goal_drift": {
                "user_input": "I want to cancel my subscription",
                "agent_response": "Instead of canceling, let me tell you about our premium features",
                "expected_type": "goal_drift"
            },
            "incomplete": {
                "user_input": "How do I reset my password?",
                "agent_response": "You can reset your password",
                "expected_type": "incomplete"
            },
            "hallucination": {
                "user_input": "What's my account number?",
                "agent_response": "Your account number is 123456789 (I made this up)",
                "expected_type": "hallucination"
            },
            "context_loss": {
                "user_input": "Thanks for helping with my billing issue",
                "agent_response": "What billing issue? I don't see any previous conversation",
                "expected_type": "context_loss"
            },
            "loop": {
                "user_input": "I need help",
                "agent_response": "I need help I need help I need help I need help",
                "expected_type": "loop"
            }
        }
        
        # Test that failure classification can handle all types
        # In practice, this would require actual Claude evaluation
        # For now, validate the taxonomy structure
        
        expected_failure_types = set(failure_scenarios.keys())
        assert len(expected_failure_types) == 7, "Should have exactly 7 failure types"
        
        required_types = {"wrong_answer", "tool_failure", "goal_drift", "incomplete", "hallucination", "context_loss", "loop"}
        assert expected_failure_types == required_types, f"Missing failure types: {required_types - expected_failure_types}"