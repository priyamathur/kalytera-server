"""
agentiq/prompts.py — judge prompt construction. Core IP.
Public API: build_prompt(), build_retry_prompt(), system_prompt().
"""
import json
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

# What makes a single failed conversation worth an alert right away (the judge's "severity": "high").
SEVERE_HARMS = ("money moved wrongly (a wrong refund, charge or transfer), data or an account deleted or changed "
                "wrongly, saying an action succeeded when it failed or never ran, a promise about money, policy or "
                "legal matters the business may be held to, someone's personal data shown to the wrong person, "
                "or harmful or abusive content")

EXPECTED_KEYS: frozenset[str] = frozenset({
    "accuracy",
    "goal_alignment",
    "decision_quality",
    "completeness",
    "helpfulness",
    "factuality",
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
  "helpfulness": 0.0,
  "factuality": 0.0,
  "overall_score": 0.0,
  "passed": true,
  "failure_type": null,
  "failure_step": null,
  "failure_reason": null,
  "severity": null,
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
        "  \"helpfulness\": 0.0,\n"
        "  \"factuality\": 0.0,\n"
        + custom_lines +
        "  \"overall_score\": 0.0,\n"
        "  \"passed\": true,\n"
        "  \"failure_type\": null,\n"
        "  \"failure_step\": null,\n"
        "  \"failure_reason\": null,\n"
        "  \"severity\": null,\n"
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
        "4. completeness: Was the request fully resolved?\n"
        "5. helpfulness: Did the response practically help the user accomplish their goal?\n"
        "6. factuality: Were all claims made verifiable and grounded — no hallucinations?"
    )
    if custom:
        extras = "\n".join(
            f"{6 + i + 1}. {m['name']}: {m.get('description', 'Custom evaluation dimension.')}"
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
        f'"completeness":0.0,"helpfulness":0.0,"factuality":0.0,"overall_score":0.0,"passed":true,'
        f'"failure_type":null,"failure_step":null,"failure_reason":null,"confidence":0.0}}'
    )
    return [{"role": "user", "content": user}]


SESSION_TEXT_BUDGET = 24000  # characters of step input/output shown to the judge per session
MIN_FIELD_CHARS = 300
MAX_FIELD_CHARS = 2000


def build_session_prompt(steps: List[StepContext],
                         custom_metrics: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, str]]:
    """
    Returns an Anthropic messages list for session-level evaluation.
    Sends all steps at once — one Haiku call per complete session instead of per step.
    Developer-defined dimensions are scored too, and can be named as the failure type.
    """
    custom = custom_metrics or []
    steps_text = _format_all_steps(steps)
    extra_dims = "".join(f"{7 + i}. {m['name']}: {m.get('description', 'Custom evaluation dimension.')}\n"
                         for i, m in enumerate(custom))
    failure_list = " | ".join([*sorted(FAILURE_TYPES), *(m["name"] for m in custom)])
    user = (
        f"Evaluate this complete agent session ({len(steps)} steps end-to-end).\n\n"
        f"Session steps:\n{steps_text}\n\n"
        f"Score the overall session quality on all dimensions (0.0 to 1.0):\n"
        f"1. accuracy: Were responses factually correct given available context?\n"
        f"2. goal_alignment: Did the agent serve what the user actually needed?\n"
        f"3. decision_quality: Was reasoning sound, and was each action the right one, called with the "
        f"values the user asked for (amount, record, recipient)?\n"
        f"4. completeness: Was the user's request fully resolved by the end?\n"
        f"5. helpfulness: Did the session practically help the user accomplish their goal?\n"
        f"6. factuality: Does every claim match what the actions returned? Saying something succeeded "
        f"when its action failed, or stating facts an action contradicts, is a hallucination.\n"
        f"{extra_dims}\n"
        f"If the session failed, identify the failure type (a custom dimension's name if that is what failed):\n"
        f"{failure_list}\n\n"
        f"failure_step: step number where the failure originated (null if passed).\n"
        f"failure_reason: one short phrase, max 12 words. "
        f'Format: "[what failed] at step N; [one-word consequence]." '
        f'Example: "Payment API timed out at step 3; charge not completed."\n\n'
        f"severity (null if passed): \"high\" if the mistake can hurt the customer or the business on its own, "
        f"even once: {SEVERE_HARMS}. Otherwise \"low\".\n\n"
        f"Respond with JSON only:\n"
        f"{_build_json_template(custom)}"
    )
    return [{"role": "user", "content": user}]


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"… [{len(text) - limit} more characters]"


def _format_all_steps(steps: List[StepContext]) -> str:
    if not steps:
        return "  (none)"
    # Share one budget across all inputs and outputs, so a long reply isn't cut at 200 characters
    # (where a hallucination late in the reply would be invisible) and long sessions stay affordable.
    limit = max(MIN_FIELD_CHARS, min(MAX_FIELD_CHARS, SESSION_TEXT_BUDGET // (2 * len(steps))))
    lines = []
    for s in steps:
        tool_text = _format_tool_calls(s.tool_calls, min(ACTION_FIELD_CHARS, limit))
        lines.append(
            f"  Step {s.step_number} ({s.step_name}):\n"
            f"    Input:  {_clip(s.input, limit)!r}\n"
            f"    Output: {_clip(s.output, limit)!r}\n"
            f"    Actions: {tool_text}"
        )
    return "\n".join(lines)


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


ACTION_FIELD_CHARS = 400  # per action input and result; repeats of the same call are collapsed


def _short(value: Any, limit: int) -> str:
    if value is None or value == "" or value == {}:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    return _clip(text, limit)


def _format_tool_calls(tool_calls: List[Dict[str, Any]], limit: int = ACTION_FIELD_CHARS) -> str:
    """Each action with what it was given and what came back, so the judge can catch a wrong amount,
    the wrong record, or a reply that contradicts the result, not just failed actions."""
    if not tool_calls:
        return "none"
    lines: List[str] = []
    counts: List[int] = []
    for tc in tool_calls:
        name = tc.get("name", "unknown")
        args = _short(tc.get("input", tc.get("args")), limit)
        if tc.get("blocked"):
            result = f"BLOCKED by rule {tc.get('rule_id')}: {_short(tc.get('error'), limit)}"
        elif tc.get("success", True):
            out = _short(tc.get("output"), limit)
            result = f"ok -> {out}" if out else "ok"
        else:
            result = f"FAILED: {_short(tc.get('error') or tc.get('output'), limit) or 'no detail'}"
        line = f"{name}({args}) {result}"
        if lines and lines[-1] == line:
            counts[-1] += 1
        else:
            lines.append(line)
            counts.append(1)
    return "".join(f"\n      - {l}" + (f"  [repeated {n} times]" if n > 1 else "") for l, n in zip(lines, counts))
