"""
kalytera/judge.py — LLM-agnostic agent quality judge.
Runs asynchronously. Never called in the trace path.

Public API:
  score_step()      — pure scoring function, no DB side effects (testable)
  score_session()   — score a full session in one LLM call (free-tier mode)
  evaluate_log()    — fetch log from DB, score it, write EvalResult
  evaluate_session()— fetch session logs, score as one unit, write EvalResult

Supported judge providers (KALYTERA_JUDGE_PROVIDER env var):
  anthropic  — Claude Haiku 4.5 (default); prompt caching enabled
  openai     — GPT-4o mini
  gemini     — Gemini 1.5 Flash
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
    build_session_prompt,
    system_prompt,
)


logger = logging.getLogger(__name__)

_DEFAULT_ANTHROPIC_MODEL = "claude-haiku-5-5"
_DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
_DEFAULT_GEMINI_MODEL = "gemini-1.5-flash"
_MAX_TOKENS = 512
# Haiku 5.5 thinks before answering. Brief thinking caught 40/40 labelled mistakes (4.5: 34/40;
# 5.5 without thinking: 37/40 with more false alarms) at ~$0.00025 a conversation. Thinking counts
# toward max_tokens, so it gets more room.
_THINKING_MODELS: Dict[str, Dict[str, Any]] = {
    "claude-haiku-5-5": {"thinking": {"type": "adaptive"}, "output_config": {"effort": "low"}},
}
_THINKING_MAX_TOKENS = 1500
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
    Score one agent step using the configured judge provider.
    Returns a dict matching EvalResult fields. Never raises.
    On double judge failure returns eval_error=True.
    custom_metrics: list of {"name": "helpfulness", "weight": 0.2, "description": "..."}
    """
    w = weights or _DEFAULT_WEIGHTS
    custom = custom_metrics or []

    raw = _call_judge(build_prompt(step, prior_steps, custom_metrics=custom))
    parsed = _parse_json(raw, custom_names=[m["name"] for m in custom])

    if parsed is None:
        raw2 = _call_judge(build_retry_prompt(step))
        parsed = _parse_json(raw2)

    if parsed is None:
        return _error_result(step, custom)

    return _build_result(parsed, w, pass_threshold, step.step_number, custom)


def score_session(
    steps: List[StepContext],
    weights: Optional[Dict[str, float]] = None,
    pass_threshold: float = _PASS_THRESHOLD,
    custom_metrics: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Score a complete session (all steps) with one LLM call.
    Returns a dict matching EvalResult fields. Never raises.
    Costs ~5x less than per-step scoring for a 5-step session.
    """
    if not steps:
        dummy = StepContext(step_number=0, step_name="unknown", input="", output="")
        return _error_result(dummy)

    w = weights or _DEFAULT_WEIGHTS

    raw = _call_judge(build_session_prompt(steps, custom_metrics))
    parsed = _parse_json(raw)

    if parsed is None:
        raw2 = _call_judge(build_retry_prompt(steps[-1]))
        parsed = _parse_json(raw2)

    if parsed is None:
        return _error_result(steps[-1])

    return _build_result(parsed, w, pass_threshold, steps[-1].step_number, custom_metrics)


def evaluate_session(session_id: str, db: Any) -> Optional[Dict[str, Any]]:
    """
    Fetch all AgentLog rows for a session, score it with one LLM call,
    write one EvalResult linked to the session_ended log (or the last step, for a
    session that went idle without being marked ended). None if the session has no steps.
    """
    from db.models import AgentLog, EvalResult, AgentQualityConfig

    ended_log: Optional[Any] = (
        db.query(AgentLog)
        .filter(AgentLog.session_id == session_id, AgentLog.session_ended == True)  # noqa: E712
        .first()
    ) or (  # a session that went idle without being marked ended: judge it at its last step
        db.query(AgentLog)
        .filter(AgentLog.session_id == session_id)
        .order_by(AgentLog.step_number.desc(), AgentLog.timestamp.desc())
        .first()
    )
    if ended_log is None:
        logger.warning("No steps for session %s", session_id)
        return None

    all_logs = (
        db.query(AgentLog)
        .filter(AgentLog.session_id == session_id)
        .order_by(AgentLog.step_number)
        .all()
    )
    steps = [_log_to_step(log) for log in all_logs]

    config: Optional[Any] = (
        db.query(AgentQualityConfig)
        .filter(AgentQualityConfig.agent_id == ended_log.agent_id)
        .first()
    )
    weights, pass_threshold, custom_metrics = _weights_from_config(config)

    result = score_session(steps, weights=weights, pass_threshold=pass_threshold, custom_metrics=custom_metrics)

    result_for_db = {k: v for k, v in result.items() if k != "custom_scores"}
    custom_scores_json = json.dumps(result.get("custom_scores") or {}) or None

    row = EvalResult(
        id=str(uuid.uuid4()),
        log_id=ended_log.id,
        session_id=session_id,
        agent_id=ended_log.agent_id,
        evaluated_at=datetime.now(timezone.utc),
        custom_scores=custom_scores_json,
        failure_action=failure_action(steps, result),
        **result_for_db,
    )
    db.add(row)
    db.commit()

    return result


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

    result_for_db = {k: v for k, v in result.items() if k != "custom_scores"}
    custom_scores_json = json.dumps(result.get("custom_scores") or {}) or None

    row = EvalResult(
        id=str(uuid.uuid4()),
        log_id=log_id,
        session_id=log.session_id,
        agent_id=log.agent_id,
        evaluated_at=datetime.now(timezone.utc),
        custom_scores=custom_scores_json,
        failure_action=failure_action([step], result),
        **result_for_db,
    )
    db.add(row)
    db.commit()

    return result



def failure_action(steps: List[StepContext], result: Dict[str, Any]) -> Optional[str]:
    """
    The action a failed conversation's mistake was about, so problems group by what went wrong
    (refunds, order lookups) rather than by the judge's label, which varies for the same mistake.
    One action in the conversation: that one. Several: the one the judge's explanation names, else the
    one that failed. None when it can't tell; the problem then groups by failure type.
    """
    if result.get("passed") is not False:
        return None
    calls = [c for st in steps for c in (st.tool_calls or []) if isinstance(c, dict) and c.get("name")]
    names = list(dict.fromkeys(str(c["name"]) for c in calls))
    if len(names) <= 1:
        return names[0] if names else None
    reason = (result.get("failure_reason") or "").lower()

    def named(name: str) -> bool:
        words = [w for w in name.lower().replace("-", "_").split("_") if len(w) > 2 and w not in ("api", "tool", "get")]
        return name.lower() in reason or any(w in reason for w in words)

    for pick in ([n for n in names if named(n)],
                 list(dict.fromkeys(str(c["name"]) for c in calls if c.get("success") is False or c.get("error")))):
        if len(pick) == 1:
            return pick[0]
    return None

# ---------------------------------------------------------------------------
# Provider dispatch
# ---------------------------------------------------------------------------

def _call_judge(messages: List[Dict[str, str]], system: Optional[str] = None) -> str:
    """
    Dispatch to the configured LLM judge provider. Never raises.
    Reads KALYTERA_JUDGE_PROVIDER at call time so env changes take effect immediately.
    `system` replaces the judging instructions (e.g. to name a problem); default: judge a conversation.
    """
    provider = os.getenv("KALYTERA_JUDGE_PROVIDER", "anthropic").lower()
    try:
        if provider == "openai":
            return _call_openai(messages, system)
        elif provider in ("google", "gemini"):
            return _call_gemini(messages, system)
        else:
            return _call_anthropic(messages, system)
    except Exception as exc:
        logger.error("Judge call failed [provider=%s]: %s", provider, exc)
        return ""


def _call_anthropic(messages: List[Dict[str, str]], system: Optional[str] = None) -> str:
    """Call Claude Haiku with prompt caching on the system prompt."""
    model = os.getenv("KALYTERA_JUDGE_MODEL", "") or _DEFAULT_ANTHROPIC_MODEL
    key = os.getenv("BYOK_ANTHROPIC_API_KEY", "") or os.getenv("ANTHROPIC_API_KEY", "")
    client = anthropic.Anthropic(api_key=key)
    extra = _THINKING_MODELS.get(model, {})
    response = client.messages.create(
        model=model,
        max_tokens=_THINKING_MAX_TOKENS if extra else _MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": system or system_prompt(),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=messages,
        **extra,
    )
    return "".join(b.text for b in response.content if b.type == "text")  # skip thinking blocks


def _call_openai(messages: List[Dict[str, str]], system: Optional[str] = None) -> str:
    """Call OpenAI (gpt-4o-mini by default)."""
    import openai as openai_lib  # lazy — only required when provider=openai
    model = os.getenv("KALYTERA_JUDGE_MODEL", "") or _DEFAULT_OPENAI_MODEL
    key = os.getenv("BYOK_OPENAI_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
    client = openai_lib.OpenAI(api_key=key)
    full_messages: List[Dict[str, str]] = [
        {"role": "system", "content": system or system_prompt()},
        *messages,
    ]
    resp = client.chat.completions.create(
        model=model,
        messages=full_messages,
        max_tokens=_MAX_TOKENS,
    )
    content = resp.choices[0].message.content
    return content if content is not None else ""


def _call_gemini(messages: List[Dict[str, str]], system: Optional[str] = None) -> str:
    """Call Google Gemini (gemini-1.5-flash by default)."""
    import google.generativeai as genai  # lazy — only required when provider=gemini
    model_name = os.getenv("KALYTERA_JUDGE_MODEL", "") or _DEFAULT_GEMINI_MODEL
    key = os.getenv("BYOK_GOOGLE_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
    genai.configure(api_key=key)
    model = genai.GenerativeModel(model_name, system_instruction=system or system_prompt())
    user_text = messages[-1]["content"] if messages else ""
    response = model.generate_content(
        user_text,
        generation_config={"max_output_tokens": _MAX_TOKENS},
    )
    text: str = response.text if response.text else ""
    return text


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _parse_json(
    text: str,
    custom_names: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Parse and validate the judge's JSON response. Returns None if invalid."""
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
        if not passed and raw_failure_type in FAILURE_TYPES | {m["name"] for m in custom}
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
