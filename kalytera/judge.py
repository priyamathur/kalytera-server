"""
agentiq/judge.py — scores agent steps using Claude Haiku.
Runs asynchronously. Never called in the trace path.

Public API:
  score_step()      — pure scoring function, no DB side effects (testable)
  evaluate_log()    — fetch log from DB, score it, write EvalResult
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import anthropic

from kalytera.prompts import (
    EXPECTED_KEYS,
    FAILURE_TYPES,
    StepContext,
    build_prompt,
    build_retry_prompt,
    system_prompt,
)


logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 512
_PASS_THRESHOLD = 0.7

_DEFAULT_WEIGHTS: Dict[str, float] = {
    "accuracy": 0.25,
    "goal_alignment": 0.25,
    "decision_quality": 0.15,
    "completeness": 0.15,
    "helpfulness": 0.10,
    "factuality": 0.10,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_step(
    step: StepContext,
    prior_steps: List[StepContext],
    weights: Optional[Dict[str, float]] = None,
    pass_threshold: float = _PASS_THRESHOLD,
    custom_metrics: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Score one agent step with Claude Haiku.
    Returns a dict matching EvalResult fields. Never raises.
    On double judge failure returns eval_error=True.
    custom_metrics: list of {"name": "helpfulness", "weight": 0.2, "description": "..."}
    """
    w = weights or _DEFAULT_WEIGHTS
    custom = custom_metrics or []
    client = _make_client()

    raw = _call_claude(client, build_prompt(step, prior_steps, custom_metrics=custom))
    parsed = _parse_json(raw, custom_names=[m["name"] for m in custom])

    if parsed is None:
        raw2 = _call_claude(client, build_retry_prompt(step))
        parsed = _parse_json(raw2)

    if parsed is None:
        return _error_result(step, custom)

    return _build_result(parsed, w, pass_threshold, step.step_number, custom)


def evaluate_log(log_id: str, db: Any) -> Optional[Dict[str, Any]]:
    """
    Fetch an AgentLog row, score it, write EvalResult. Returns the result dict.
    Pass a SQLAlchemy Session as `db`. Returns None if the log is not found.
    """
    from db.models import AgentLog, EvalResult, AgentQualityConfig

    log: Optional[Any] = db.query(AgentLog).filter(AgentLog.id == log_id).first()
    if log is None:
        logger.warning("AgentLog %s not found", log_id)
        return None

    config: Optional[Any] = (
        db.query(AgentQualityConfig)
        .filter(AgentQualityConfig.agent_id == log.agent_id)
        .first()
    )
    weights, pass_threshold, custom_metrics = _weights_from_config(config)

    prior_logs = (
        db.query(AgentLog)
        .filter(
            AgentLog.session_id == log.session_id,
            AgentLog.step_number < log.step_number,
        )
        .order_by(AgentLog.step_number.desc())
        .limit(3)
        .all()
    )

    step = _log_to_step(log)
    prior_steps = [_log_to_step(p) for p in reversed(prior_logs)]

    result = score_step(
        step, prior_steps,
        weights=weights,
        pass_threshold=pass_threshold,
        custom_metrics=custom_metrics,
    )

    # custom_scores is a dict — serialize before writing to Text column
    result_for_db = {k: v for k, v in result.items() if k != "custom_scores"}
    custom_scores_json = json.dumps(result.get("custom_scores") or {}) or None

    row = EvalResult(
        id=str(uuid.uuid4()),
        log_id=log_id,
        session_id=log.session_id,
        agent_id=log.agent_id,
        evaluated_at=datetime.now(timezone.utc),
        custom_scores=custom_scores_json,
        **result_for_db,
    )
    db.add(row)
    db.commit()

    return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _make_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))


def _call_claude(
    client: anthropic.Anthropic,
    messages: List[Dict[str, str]],
) -> str:
    """Call Claude Haiku. Returns raw text or '' on error. Never raises."""
    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=system_prompt(),
            messages=messages,
        )
        return response.content[0].text
    except Exception as exc:
        logger.error("Claude API call failed: %s", exc)
        return ""


def _parse_json(
    text: str,
    custom_names: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Parse and validate Claude's JSON response. Returns None if invalid."""
    if not text:
        return None
    try:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            parts = cleaned.split("```")
            cleaned = parts[1].lstrip("json").strip() if len(parts) > 1 else cleaned
        data: Dict[str, Any] = json.loads(cleaned)
        missing = EXPECTED_KEYS - set(data.keys())
        if missing:
            logger.warning("Judge response missing keys: %s", missing)
            return None
        return data
    except json.JSONDecodeError:
        return None


def _build_result(
    parsed: Dict[str, Any],
    weights: Dict[str, float],
    pass_threshold: float,
    step_number: int,
    custom_metrics: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compute overall_score from weights. Never trusts the model's own calculation."""
    accuracy = _clamp(parsed.get("accuracy", 0.0))
    goal_alignment = _clamp(parsed.get("goal_alignment", 0.0))
    decision_quality = _clamp(parsed.get("decision_quality", 0.0))
    completeness = _clamp(parsed.get("completeness", 0.0))
    helpfulness = _clamp(parsed.get("helpfulness", 0.0))
    factuality = _clamp(parsed.get("factuality", 0.0))

    custom = custom_metrics or []
    custom_scores: Dict[str, float] = {
        m["name"]: _clamp(parsed.get(m["name"], 0.0)) for m in custom
    }

    overall_score = round(
        accuracy * weights.get("accuracy", 0.25)
        + goal_alignment * weights.get("goal_alignment", 0.25)
        + decision_quality * weights.get("decision_quality", 0.15)
        + completeness * weights.get("completeness", 0.15)
        + helpfulness * weights.get("helpfulness", 0.10)
        + factuality * weights.get("factuality", 0.10)
        + sum(custom_scores[m["name"]] * weights.get(m["name"], 0.0) for m in custom),
        4,
    )
    passed = overall_score >= pass_threshold

    raw_failure_type = parsed.get("failure_type")
    failure_type = (
        raw_failure_type
        if not passed and raw_failure_type in FAILURE_TYPES
        else None
    )
    failure_reason = parsed.get("failure_reason") if not passed else None

    return {
        "accuracy": accuracy,
        "goal_alignment": goal_alignment,
        "decision_quality": decision_quality,
        "completeness": completeness,
        "helpfulness": helpfulness,
        "factuality": factuality,
        "custom_scores": custom_scores,
        "overall_score": overall_score,
        "passed": passed,
        "failure_type": failure_type,
        "failure_step": parsed.get("failure_step") if not passed else None,
        "failure_reason": failure_reason,
        "confidence": _clamp(parsed.get("confidence", 0.0)),
        "eval_error": False,
    }


def _error_result(
    step: StepContext,
    custom_metrics: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "accuracy": 0.0,
        "goal_alignment": 0.0,
        "decision_quality": 0.0,
        "completeness": 0.0,
        "helpfulness": 0.0,
        "factuality": 0.0,
        "custom_scores": {m["name"]: 0.0 for m in (custom_metrics or [])},
        "overall_score": 0.0,
        "passed": False,
        "failure_type": None,
        "failure_step": str(step.step_number),
        "failure_reason": None,
        "confidence": 0.0,
        "eval_error": True,
    }


def _clamp(val: Any) -> float:
    try:
        return min(max(float(val), 0.0), 1.0)
    except (TypeError, ValueError):
        return 0.0


def _weights_from_config(
    config: Any,
) -> tuple[Dict[str, float], float, List[Dict[str, Any]]]:
    if config is None:
        return _DEFAULT_WEIGHTS, _PASS_THRESHOLD, []

    custom_metrics: List[Dict[str, Any]] = []
    if getattr(config, "custom_metrics", None):
        try:
            custom_metrics = json.loads(config.custom_metrics)
        except (ValueError, TypeError):
            custom_metrics = []

    weights: Dict[str, float] = {
        "accuracy": config.weight_accuracy,
        "goal_alignment": config.weight_goal_alignment,
        "decision_quality": config.weight_decision,
        "completeness": config.weight_completeness,
        "helpfulness": getattr(config, "weight_helpfulness", 0.10) or 0.10,
        "factuality": getattr(config, "weight_factuality", 0.10) or 0.10,
    }
    for m in custom_metrics:
        weights[m["name"]] = float(m.get("weight", 0.0))

    return weights, config.pass_threshold, custom_metrics


def _log_to_step(log: Any) -> StepContext:
    tool_calls: List[Dict[str, Any]] = []
    if getattr(log, "tool_calls", None):
        try:
            tool_calls = json.loads(log.tool_calls)
        except (json.JSONDecodeError, TypeError):
            tool_calls = []
    return StepContext(
        step_number=log.step_number,
        step_name=log.step_name,
        input=log.input,
        output=log.output,
        tool_calls=tool_calls,
    )
