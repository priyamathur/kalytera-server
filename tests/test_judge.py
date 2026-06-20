"""Tests for agentiq/judge.py — scoring logic, JSON parsing, error handling."""
import json
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from agentiq.judge import (
    _build_result,
    _clamp,
    _error_result,
    _parse_json,
    score_step,
)
from agentiq.prompts import StepContext

_WEIGHTS = {"accuracy": 0.35, "goal_alignment": 0.35, "decision_quality": 0.15, "completeness": 0.15}
_PASS_THRESHOLD = 0.7


def _step(n: int = 1, name: str = "retrieve_policy") -> StepContext:
    return StepContext(
        step_number=n,
        step_name=name,
        input="What is the refund policy?",
        output="The refund window is 30 days.",
    )


def _good_json(
    accuracy: float = 0.9,
    goal_alignment: float = 0.9,
    decision_quality: float = 0.85,
    completeness: float = 0.9,
) -> str:
    return json.dumps({
        "accuracy": accuracy,
        "goal_alignment": goal_alignment,
        "decision_quality": decision_quality,
        "completeness": completeness,
        "overall_score": 0.9,         # model's value — we recompute
        "passed": True,
        "failure_type": None,
        "failure_step": None,
        "failure_reason": None,
        "confidence": 0.95,
    })


def _failure_json(failure_type: str = "tool_failure") -> str:
    return json.dumps({
        "accuracy": 0.3,
        "goal_alignment": 0.4,
        "decision_quality": 0.3,
        "completeness": 0.2,
        "overall_score": 0.3,
        "passed": False,
        "failure_type": failure_type,
        "failure_step": 2,
        "failure_reason": "Agent applied wrong refund policy for product category.",
        "confidence": 0.88,
    })


# --- _parse_json ---

def test_parse_json_valid() -> None:
    result = _parse_json(_good_json())
    assert result is not None
    assert "accuracy" in result


def test_parse_json_empty_string() -> None:
    assert _parse_json("") is None


def test_parse_json_malformed() -> None:
    assert _parse_json("{not valid json}") is None


def test_parse_json_missing_keys() -> None:
    incomplete = json.dumps({"accuracy": 0.9, "passed": True})
    assert _parse_json(incomplete) is None


def test_parse_json_strips_code_fences() -> None:
    fenced = "```json\n" + _good_json() + "\n```"
    result = _parse_json(fenced)
    assert result is not None


# --- _clamp ---

def test_clamp_normal() -> None:
    assert _clamp(0.75) == 0.75


def test_clamp_above_one() -> None:
    assert _clamp(1.5) == 1.0


def test_clamp_below_zero() -> None:
    assert _clamp(-0.1) == 0.0


def test_clamp_non_numeric() -> None:
    assert _clamp("bad") == 0.0


# --- _build_result ---

def test_build_result_computes_weighted_score() -> None:
    parsed = json.loads(_good_json(accuracy=1.0, goal_alignment=1.0, decision_quality=1.0, completeness=1.0))
    result = _build_result(parsed, _WEIGHTS, _PASS_THRESHOLD, step_number=1)
    assert result["overall_score"] == 1.0
    assert result["passed"] is True
    assert result["eval_error"] is False


def test_build_result_ignores_models_overall_score() -> None:
    """We recompute overall_score from weights; don't trust the model's value."""
    parsed = json.loads(_good_json(accuracy=0.5, goal_alignment=0.5, decision_quality=0.5, completeness=0.5))
    parsed["overall_score"] = 0.99  # model claims high score
    result = _build_result(parsed, _WEIGHTS, _PASS_THRESHOLD, step_number=1)
    expected = 0.5 * 0.35 + 0.5 * 0.35 + 0.5 * 0.15 + 0.5 * 0.15
    assert abs(result["overall_score"] - expected) < 0.001


def test_build_result_failure_sets_fields() -> None:
    parsed = json.loads(_failure_json("tool_failure"))
    result = _build_result(parsed, _WEIGHTS, _PASS_THRESHOLD, step_number=2)
    assert result["passed"] is False
    assert result["failure_type"] == "tool_failure"
    assert result["failure_reason"] is not None
    assert result["failure_step"] == 2


def test_build_result_rejects_unknown_failure_type() -> None:
    parsed = json.loads(_failure_json("made_up_type"))
    result = _build_result(parsed, _WEIGHTS, _PASS_THRESHOLD, step_number=1)
    assert result["failure_type"] is None


def test_build_result_passed_clears_failure_fields() -> None:
    parsed = json.loads(_good_json())
    parsed["failure_type"] = "tool_failure"  # model incorrectly set this on a pass
    result = _build_result(parsed, _WEIGHTS, _PASS_THRESHOLD, step_number=1)
    assert result["passed"] is True
    assert result["failure_type"] is None
    assert result["failure_reason"] is None


def test_build_result_custom_weights() -> None:
    parsed = json.loads(_good_json(accuracy=1.0, goal_alignment=0.0, decision_quality=0.0, completeness=0.0))
    weights = {"accuracy": 1.0, "goal_alignment": 0.0, "decision_quality": 0.0, "completeness": 0.0}
    result = _build_result(parsed, weights, _PASS_THRESHOLD, step_number=1)
    assert result["overall_score"] == 1.0


# --- _error_result ---

def test_error_result_sets_eval_error() -> None:
    result = _error_result(_step())
    assert result["eval_error"] is True
    assert result["passed"] is False
    assert result["overall_score"] == 0.0


# --- score_step (mocked Claude) ---

def test_score_step_passes_on_good_response() -> None:
    with patch("agentiq.judge._call_claude", return_value=_good_json()):
        result = score_step(_step(), prior_steps=[])
    assert result["passed"] is True
    assert result["eval_error"] is False
    assert 0.0 <= result["overall_score"] <= 1.0


def test_score_step_failure_on_low_scores() -> None:
    with patch("agentiq.judge._call_claude", return_value=_failure_json("context_loss")):
        result = score_step(_step(), prior_steps=[])
    assert result["passed"] is False
    assert result["failure_type"] == "context_loss"
    assert result["failure_reason"] is not None


def test_score_step_retries_on_bad_json() -> None:
    """First call returns bad JSON; second (retry) returns good JSON."""
    responses = ["not json at all", _good_json()]
    with patch("agentiq.judge._call_claude", side_effect=responses):
        result = score_step(_step(), prior_steps=[])
    assert result["eval_error"] is False
    assert result["passed"] is True


def test_score_step_eval_error_on_double_failure() -> None:
    with patch("agentiq.judge._call_claude", return_value=""):
        result = score_step(_step(), prior_steps=[])
    assert result["eval_error"] is True


def test_score_step_uses_prior_context() -> None:
    """Verify prior_steps are passed to build_prompt (not build_retry_prompt)."""
    prior = [_step(n=1, name="fetch_order")]
    with patch("agentiq.judge._call_claude", return_value=_good_json()) as mock_call:
        with patch("agentiq.judge.build_prompt", wraps=__import__("agentiq.prompts", fromlist=["build_prompt"]).build_prompt) as mock_bp:
            score_step(_step(n=2), prior_steps=prior)
            args = mock_bp.call_args
            assert args[0][1] == prior  # prior_steps forwarded


def test_score_step_custom_weights() -> None:
    weights = {"accuracy": 1.0, "goal_alignment": 0.0, "decision_quality": 0.0, "completeness": 0.0}
    raw = json.dumps({
        "accuracy": 0.8, "goal_alignment": 0.0, "decision_quality": 0.0, "completeness": 0.0,
        "overall_score": 0.8, "passed": True, "failure_type": None,
        "failure_step": None, "failure_reason": None, "confidence": 0.9,
    })
    with patch("agentiq.judge._call_claude", return_value=raw):
        result = score_step(_step(), prior_steps=[], weights=weights)
    assert abs(result["overall_score"] - 0.8) < 0.001


def test_score_step_custom_pass_threshold() -> None:
    """With threshold=0.95, a score of 0.9 should fail."""
    with patch("agentiq.judge._call_claude", return_value=_good_json(
        accuracy=0.9, goal_alignment=0.9, decision_quality=0.9, completeness=0.9
    )):
        result = score_step(_step(), prior_steps=[], pass_threshold=0.95)
    assert result["passed"] is False
