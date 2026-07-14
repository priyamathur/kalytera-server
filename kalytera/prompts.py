"""
agentiq/prompts.py — judge prompt construction. Core IP.
Public API: build_prompt(), build_retry_prompt(), system_prompt().
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

FAILURE_TYPES: frozenset[str] = frozenset({
    "wrong_answer",
    "tool_failure",
    "goal_drift",
    "incomplete",
    "hallucination",
    "context_loss",
    "loop",
})

EXPECTED_KEYS: frozenset[str] = frozenset({
    "accuracy",
    "goal_alignment",
    "decision_quality",
    "completeness",
    "overall_score",
    "passed",
    "failure_type",
    "failure_step",
    "failure_reason",
    "confidence",
})

_SYSTEM = (
    "You are an expert AI agent quality evaluator. "
    "You evaluate agent interactions across multiple dimensions. "
    "You always respond with valid JSON only. No prose. No markdown. No code fences."
)

_FAILURE_LIST = " | ".join(sorted(FAILURE_TYPES))

_JSON_TEMPLATE = """{
  "accuracy": 0.0,
  "goal_alignment": 0.0,
  "decision_quality": 0.0,
  "completeness": 0.0,
  "overall_score": 0.0,
  "passed": true,
  "failure_type": null,
  "failure_step": null,
  "failure_reason": null,
  "confidence": 0.0
}"""


def _build_json_template(custom_metrics: List[Dict[str, Any]]) -> str:
    if not custom_metrics:
        return _JSON_TEMPLATE
    custom_lines = "".join(f'  "{m["name"]}": 0.0,\n' for m in custom_metrics)
    return (
        "{\n"
        "  \"accuracy\": 0.0,\n"
        "  \"goal_alignment\": 0.0,\n"
        "  \"decision_quality\": 0.0,\n"
        "  \"completeness\": 0.0,\n"
        + custom_lines +
        "  \"overall_score\": 0.0,\n"
        "  \"passed\": true,\n"
        "  \"failure_type\": null,\n"
        "  \"failure_step\": null,\n"
        "  \"failure_reason\": null,\n"
        "  \"confidence\": 0.0\n"
        "}"
    )


@dataclass
class StepContext:
    step_number: int
    step_name: str
    input: str
    output: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)


def system_prompt() -> str:
    return _SYSTEM


def build_prompt(
    step: StepContext,
    prior_steps: List[StepContext],
    custom_metrics: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    """
    Returns an Anthropic messages list for the judge call.
    Includes up to the last 3 prior steps as context.
    custom_metrics: list of {"name": "helpfulness", "description": "..."} dicts.
    """
    context_steps = prior_steps[-3:]
    prior_text = _format_prior_steps(context_steps)
    tool_text = _format_tool_calls(step.tool_calls)
    custom = custom_metrics or []

    dim_lines = (
        "1. accuracy: Was the response factually correct given available context?\n"
        "2. goal_alignment: Did the agent serve what the user actually needed?\n"
        "3. decision_quality: Was the reasoning sound and tool selection appropriate?\n"
        "4. completeness: Was the request fully resolved?"
    )
    if custom:
        extras = "\n".join(
            f"{4 + i + 1}. {m['name']}: {m.get('description', 'Custom evaluation dimension.')}"
            for i, m in enumerate(custom)
        )
        dim_lines = dim_lines + "\n" + extras

    json_template = _build_json_template(custom)

    user = (
        f"Prior context (last {len(context_steps)} steps):\n"
        f"{prior_text}\n\n"
        f"Current step to evaluate:\n"
        f"Step {step.step_number}: {step.step_name}\n"
        f"Input: {step.input}\n"
        f"Output: {step.output}\n"
        f"Tool calls: {tool_text}\n\n"
        f"Score this step on all dimensions (0.0 to 1.0):\n"
        f"{dim_lines}\n\n"
        f"If any dimension is below 0.7, identify the failure type:\n"
        f"{_FAILURE_LIST}\n\n"
        f"failure_reason: one short phrase, max 12 words. "
        f'Format: "[what failed] at {step.step_name}; [one-word consequence]." '
        f"Example: \"Payment API timed out at process_payment; charge not completed.\"\n\n"
        f"Respond with JSON only:\n"
        f"{json_template}"
    )

    return [{"role": "user", "content": user}]


def build_retry_prompt(step: StepContext) -> List[Dict[str, str]]:
    """
    Simplified prompt for the second attempt after malformed JSON.
    Truncates input/output to reduce noise.
    """
    user = (
        f"Rate this agent step. Reply with JSON only, no other text.\n\n"
        f"Step: {step.step_name}\n"
        f"Input: {step.input[:200]}\n"
        f"Output: {step.output[:200]}\n\n"
        f'JSON format (0.0-1.0 for scores):\n'
        f'{{"accuracy":0.0,"goal_alignment":0.0,"decision_quality":0.0,'
        f'"completeness":0.0,"overall_score":0.0,"passed":true,'
        f'"failure_type":null,"failure_step":null,"failure_reason":null,"confidence":0.0}}'
    )
    return [{"role": "user", "content": user}]


def _format_prior_steps(steps: List[StepContext]) -> str:
    if not steps:
        return "  (none)"
    lines = []
    for s in steps:
        lines.append(
            f"  Step {s.step_number} ({s.step_name}): "
            f"Input={s.input[:120]!r} → Output={s.output[:120]!r}"
        )
    return "\n".join(lines)


def _format_tool_calls(tool_calls: List[Dict[str, Any]]) -> str:
    if not tool_calls:
        return "none"
    parts = []
    for tc in tool_calls:
        name = tc.get("name", "unknown")
        success = tc.get("success", True)
        parts.append(f"{name}({'ok' if success else 'failed'})")
    return ", ".join(parts)
