"""
Tests for kalytera/judge.py — scoring logic, JSON parsing, error handling,
provider dispatch, BYOK key resolution, and session-level evaluation.
"""
import json
from typing import List
from unittest.mock import MagicMock, patch

from kalytera.judge import (
    _build_result,
    _call_anthropic,
    _call_gemini,
    _call_judge,
    _call_openai,
    _clamp,
    _error_result,
    _parse_json,
    score_session,
    score_step,
)
from kalytera.prompts import StepContext

# Weights that sum to 1.0 across all six scoring dimensions.
_WEIGHTS = {
    "accuracy": 0.35,
    "goal_alignment": 0.35,
    "decision_quality": 0.15,
    "completeness": 0.15,
    "helpfulness": 0.0,
    "factuality": 0.0,
}
_PASS_THRESHOLD = 0.7


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _step(n: int = 1, name: str = "retrieve_policy") -> StepContext:
    return StepContext(
        step_number=n,
        step_name=name,
        input="What is the refund policy?",
        output="The refund window is 30 days.",
    )


def _steps(count: int = 3) -> List[StepContext]:
    names = ["retrieve_policy", "calculate_refund", "process_payment"]
    return [_step(n=i + 1, name=names[i % len(names)]) for i in range(count)]


def _good_json(
    accuracy: float = 0.9,
    goal_alignment: float = 0.9,
    decision_quality: float = 0.85,
    completeness: float = 0.9,
    helpfulness: float = 0.9,
    factuality: float = 0.9,
) -> str:
    return json.dumps({
        "accuracy": accuracy,
        "goal_alignment": goal_alignment,
        "decision_quality": decision_quality,
        "completeness": completeness,
        "helpfulness": helpfulness,
        "factuality": factuality,
        "overall_score": 0.9,         # model's value — we recompute from weights
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
        "helpfulness": 0.2,
        "factuality": 0.2,
        "overall_score": 0.3,
        "passed": False,
        "failure_type": failure_type,
        "failure_step": 2,
        "failure_reason": "Agent applied wrong refund policy for product category.",
        "confidence": 0.88,
    })


# ---------------------------------------------------------------------------
# _parse_json
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# _clamp
# ---------------------------------------------------------------------------

def test_clamp_normal() -> None:
    assert _clamp(0.75) == 0.75


def test_clamp_above_one() -> None:
    assert _clamp(1.5) == 1.0


def test_clamp_below_zero() -> None:
    assert _clamp(-0.1) == 0.0


def test_clamp_non_numeric() -> None:
    assert _clamp("bad") == 0.0


# ---------------------------------------------------------------------------
# _build_result
# ---------------------------------------------------------------------------

def test_build_result_computes_weighted_score() -> None:
    parsed = json.loads(_good_json(accuracy=1.0, goal_alignment=1.0, decision_quality=1.0, completeness=1.0, helpfulness=0.0, factuality=0.0))
    result = _build_result(parsed, _WEIGHTS, _PASS_THRESHOLD, step_number=1)
    assert result["overall_score"] == 1.0
    assert result["passed"] is True
    assert result["eval_error"] is False


def test_build_result_ignores_models_overall_score() -> None:
    """We recompute overall_score from weights; don't trust the model's value."""
    parsed = json.loads(_good_json(accuracy=0.5, goal_alignment=0.5, decision_quality=0.5, completeness=0.5, helpfulness=0.0, factuality=0.0))
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
    parsed = json.loads(_good_json(accuracy=1.0, goal_alignment=0.0, decision_quality=0.0, completeness=0.0, helpfulness=0.0, factuality=0.0))
    weights = {"accuracy": 1.0, "goal_alignment": 0.0, "decision_quality": 0.0, "completeness": 0.0, "helpfulness": 0.0, "factuality": 0.0}
    result = _build_result(parsed, weights, _PASS_THRESHOLD, step_number=1)
    assert result["overall_score"] == 1.0


# ---------------------------------------------------------------------------
# _error_result
# ---------------------------------------------------------------------------

def test_error_result_sets_eval_error() -> None:
    result = _error_result(_step())
    assert result["eval_error"] is True
    assert result["passed"] is False
    assert result["overall_score"] == 0.0


# ---------------------------------------------------------------------------
# score_step (mocked _call_judge)
# ---------------------------------------------------------------------------

def test_score_step_passes_on_good_response() -> None:
    with patch("kalytera.judge._call_judge", return_value=_good_json()):
        result = score_step(_step(), prior_steps=[])
    assert result["passed"] is True
    assert result["eval_error"] is False
    assert 0.0 <= result["overall_score"] <= 1.0


def test_score_step_failure_on_low_scores() -> None:
    with patch("kalytera.judge._call_judge", return_value=_failure_json("context_loss")):
        result = score_step(_step(), prior_steps=[])
    assert result["passed"] is False
    assert result["failure_type"] == "context_loss"
    assert result["failure_reason"] is not None


def test_score_step_retries_on_bad_json() -> None:
    """First call returns bad JSON; second (retry) returns good JSON."""
    responses = ["not json at all", _good_json()]
    with patch("kalytera.judge._call_judge", side_effect=responses):
        result = score_step(_step(), prior_steps=[])
    assert result["eval_error"] is False
    assert result["passed"] is True


def test_score_step_eval_error_on_double_failure() -> None:
    with patch("kalytera.judge._call_judge", return_value=""):
        result = score_step(_step(), prior_steps=[])
    assert result["eval_error"] is True


def test_score_step_uses_prior_context() -> None:
    """Verify prior_steps are forwarded to build_prompt."""
    prior = [_step(n=1, name="fetch_order")]
    with patch("kalytera.judge._call_judge", return_value=_good_json()):
        with patch("kalytera.judge.build_prompt", wraps=__import__("kalytera.prompts", fromlist=["build_prompt"]).build_prompt) as mock_bp:
            score_step(_step(n=2), prior_steps=prior)
            args = mock_bp.call_args
            assert args[0][1] == prior


def test_score_step_custom_weights() -> None:
    weights = {"accuracy": 1.0, "goal_alignment": 0.0, "decision_quality": 0.0, "completeness": 0.0, "helpfulness": 0.0, "factuality": 0.0}
    raw = json.dumps({
        "accuracy": 0.8, "goal_alignment": 0.0, "decision_quality": 0.0, "completeness": 0.0,
        "helpfulness": 0.0, "factuality": 0.0,
        "overall_score": 0.8, "passed": True, "failure_type": None,
        "failure_step": None, "failure_reason": None, "confidence": 0.9,
    })
    with patch("kalytera.judge._call_judge", return_value=raw):
        result = score_step(_step(), prior_steps=[], weights=weights)
    assert abs(result["overall_score"] - 0.8) < 0.001


def test_score_step_custom_pass_threshold() -> None:
    """With threshold=0.95, a score of 0.9 should fail."""
    with patch("kalytera.judge._call_judge", return_value=_good_json(
        accuracy=0.9, goal_alignment=0.9, decision_quality=0.9, completeness=0.9
    )):
        result = score_step(_step(), prior_steps=[], pass_threshold=0.95)
    assert result["passed"] is False


# ---------------------------------------------------------------------------
# score_session (mocked _call_judge)
# ---------------------------------------------------------------------------

def test_score_session_passes_on_good_response() -> None:
    with patch("kalytera.judge._call_judge", return_value=_good_json()):
        result = score_session(_steps())
    assert result["passed"] is True
    assert result["eval_error"] is False
    assert 0.0 <= result["overall_score"] <= 1.0


def test_score_session_failure_on_low_scores() -> None:
    with patch("kalytera.judge._call_judge", return_value=_failure_json("goal_drift")):
        result = score_session(_steps())
    assert result["passed"] is False
    assert result["failure_type"] == "goal_drift"


def test_score_session_retries_on_bad_json() -> None:
    responses = ["not json", _good_json()]
    with patch("kalytera.judge._call_judge", side_effect=responses):
        result = score_session(_steps())
    assert result["eval_error"] is False


def test_score_session_eval_error_on_double_failure() -> None:
    with patch("kalytera.judge._call_judge", return_value=""):
        result = score_session(_steps())
    assert result["eval_error"] is True


def test_score_session_empty_steps_returns_error() -> None:
    result = score_session([])
    assert result["eval_error"] is True


def test_score_session_one_call_for_multi_step_session() -> None:
    """score_session makes exactly 1 LLM call (not 1 per step) on a clean response."""
    with patch("kalytera.judge._call_judge", return_value=_good_json()) as mock_call:
        score_session(_steps(count=5))
    assert mock_call.call_count == 1


# ---------------------------------------------------------------------------
# _call_judge — provider dispatch
# ---------------------------------------------------------------------------

def test_call_judge_defaults_to_anthropic(monkeypatch: object) -> None:
    monkeypatch.setenv("KALYTERA_JUDGE_PROVIDER", "anthropic")
    with patch("kalytera.judge._call_anthropic", return_value="ok") as mock:
        _call_judge([{"role": "user", "content": "test"}])
    mock.assert_called_once()


def test_call_judge_dispatches_to_openai(monkeypatch: object) -> None:
    monkeypatch.setenv("KALYTERA_JUDGE_PROVIDER", "openai")
    with patch("kalytera.judge._call_openai", return_value="ok") as mock:
        _call_judge([{"role": "user", "content": "test"}])
    mock.assert_called_once()


def test_call_judge_dispatches_to_gemini(monkeypatch: object) -> None:
    monkeypatch.setenv("KALYTERA_JUDGE_PROVIDER", "gemini")
    with patch("kalytera.judge._call_gemini", return_value="ok") as mock:
        _call_judge([{"role": "user", "content": "test"}])
    mock.assert_called_once()


def test_call_judge_dispatches_google_alias(monkeypatch: object) -> None:
    """'google' is an accepted alias for 'gemini'."""
    monkeypatch.setenv("KALYTERA_JUDGE_PROVIDER", "google")
    with patch("kalytera.judge._call_gemini", return_value="ok") as mock:
        _call_judge([{"role": "user", "content": "test"}])
    mock.assert_called_once()


def test_call_judge_returns_empty_string_on_exception(monkeypatch: object) -> None:
    monkeypatch.setenv("KALYTERA_JUDGE_PROVIDER", "anthropic")
    with patch("kalytera.judge._call_anthropic", side_effect=RuntimeError("boom")):
        result = _call_judge([{"role": "user", "content": "test"}])
    assert result == ""


# ---------------------------------------------------------------------------
# _call_anthropic — Anthropic SDK + BYOK
# ---------------------------------------------------------------------------

def test_call_anthropic_uses_byok_key_first(monkeypatch: object) -> None:
    monkeypatch.setenv("BYOK_ANTHROPIC_API_KEY", "byok-key-abc")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "platform-key-xyz")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=_good_json())]
    mock_client.messages.create.return_value = mock_response

    with patch("anthropic.Anthropic", return_value=mock_client) as mock_cls:
        _call_anthropic([{"role": "user", "content": "test"}])

    mock_cls.assert_called_once_with(api_key="byok-key-abc")


def test_call_anthropic_falls_back_to_env_key(monkeypatch: object) -> None:
    monkeypatch.delenv("BYOK_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "platform-key-xyz")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=_good_json())]
    mock_client.messages.create.return_value = mock_response

    with patch("anthropic.Anthropic", return_value=mock_client) as mock_cls:
        _call_anthropic([{"role": "user", "content": "test"}])

    mock_cls.assert_called_once_with(api_key="platform-key-xyz")


def test_call_anthropic_sends_system_with_cache_control(monkeypatch: object) -> None:
    monkeypatch.setenv("BYOK_ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=_good_json())]
    mock_client.messages.create.return_value = mock_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        _call_anthropic([{"role": "user", "content": "test"}])

    call_kwargs = mock_client.messages.create.call_args[1]
    system = call_kwargs["system"]
    assert isinstance(system, list)
    assert system[0]["cache_control"] == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# _call_openai — OpenAI SDK + BYOK
# ---------------------------------------------------------------------------

def _make_openai_mock(text: str) -> MagicMock:
    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = text
    mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
    return mock_client


def test_call_openai_uses_byok_key_first(monkeypatch: object) -> None:
    monkeypatch.setenv("BYOK_OPENAI_API_KEY", "byok-oai-key")
    monkeypatch.setenv("OPENAI_API_KEY", "platform-oai-key")
    mock_client = _make_openai_mock(_good_json())

    with patch("openai.OpenAI", return_value=mock_client) as mock_cls:
        _call_openai([{"role": "user", "content": "test"}])

    mock_cls.assert_called_once_with(api_key="byok-oai-key")


def test_call_openai_injects_system_message(monkeypatch: object) -> None:
    monkeypatch.setenv("BYOK_OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    mock_client = _make_openai_mock(_good_json())

    with patch("openai.OpenAI", return_value=mock_client):
        _call_openai([{"role": "user", "content": "hello"}])

    call_kwargs = mock_client.chat.completions.create.call_args[1]
    messages = call_kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


def test_call_openai_returns_content_string(monkeypatch: object) -> None:
    monkeypatch.setenv("BYOK_OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    mock_client = _make_openai_mock(_good_json())

    with patch("openai.OpenAI", return_value=mock_client):
        result = _call_openai([{"role": "user", "content": "test"}])

    assert result == _good_json()


# ---------------------------------------------------------------------------
# _call_gemini — Google Generative AI + BYOK
# ---------------------------------------------------------------------------

def _make_gemini_mocks(text: str) -> tuple:
    mock_genai = MagicMock()
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.text = text
    mock_model.generate_content.return_value = mock_response
    mock_genai.GenerativeModel.return_value = mock_model
    return mock_genai, mock_model


def test_call_gemini_uses_byok_key_first(monkeypatch: object) -> None:
    monkeypatch.setenv("BYOK_GOOGLE_API_KEY", "byok-google-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "platform-google-key")
    mock_genai, _ = _make_gemini_mocks(_good_json())

    with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
        _call_gemini([{"role": "user", "content": "test"}])

    mock_genai.configure.assert_called_once_with(api_key="byok-google-key")


def test_call_gemini_passes_system_instruction(monkeypatch: object) -> None:
    monkeypatch.setenv("BYOK_GOOGLE_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "key")
    mock_genai, _ = _make_gemini_mocks(_good_json())

    with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
        _call_gemini([{"role": "user", "content": "test"}])

    call_kwargs = mock_genai.GenerativeModel.call_args[1]
    assert "system_instruction" in call_kwargs


def test_call_gemini_returns_text(monkeypatch: object) -> None:
    monkeypatch.setenv("BYOK_GOOGLE_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "key")
    mock_genai, _ = _make_gemini_mocks(_good_json())

    with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
        result = _call_gemini([{"role": "user", "content": "test"}])

    assert result == _good_json()


# ---------------------------------------------------------------------------
# End-to-end: score_step + score_session use _call_judge → provider
# ---------------------------------------------------------------------------

def test_end_to_end_score_step_via_openai_provider(monkeypatch: object) -> None:
    """Full flow: score_step → _call_judge → _call_openai (mocked)."""
    monkeypatch.setenv("KALYTERA_JUDGE_PROVIDER", "openai")
    monkeypatch.setenv("BYOK_OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    mock_client = _make_openai_mock(_good_json())

    with patch("openai.OpenAI", return_value=mock_client):
        result = score_step(_step(), prior_steps=[])

    assert result["passed"] is True
    assert result["eval_error"] is False


def test_end_to_end_score_session_via_gemini_provider(monkeypatch: object) -> None:
    """Full flow: score_session → _call_judge → _call_gemini (mocked)."""
    monkeypatch.setenv("KALYTERA_JUDGE_PROVIDER", "gemini")
    monkeypatch.setenv("BYOK_GOOGLE_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    mock_genai, _ = _make_gemini_mocks(_good_json())

    with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
        result = score_session(_steps(count=3))

    assert result["passed"] is True
    assert result["eval_error"] is False


def test_end_to_end_score_step_via_anthropic_provider(monkeypatch: object) -> None:
    """Full flow: score_step → _call_judge → _call_anthropic (mocked)."""
    monkeypatch.setenv("KALYTERA_JUDGE_PROVIDER", "anthropic")
    monkeypatch.setenv("BYOK_ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=_good_json())]
    mock_client.messages.create.return_value = mock_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = score_step(_step(), prior_steps=[])

    assert result["passed"] is True
    assert result["eval_error"] is False
