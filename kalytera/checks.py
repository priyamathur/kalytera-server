"""
Deterministic step checks — no LLM call, no network, no API key.

Each check reads a session's steps (dicts shaped like kalytera.trace() arguments)
and returns Findings. Used by `kalytera demo`; cheap enough to run on every step.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

_FAILED_STATUSES = {"error", "failed", "failure", "timeout", "timed_out"}


@dataclass
class Finding:
    check: str          # "tool_failure" | "loop"
    step_number: int    # step where the problem starts
    step_name: str
    message: str
    last_step: int = 0  # last affected step (loops span several); 0 = same as step_number


def tool_failure_reason(call: Any) -> Optional[str]:
    """Why a tool call failed, or None if it didn't. Accepts error / status / status_code keys."""
    if not isinstance(call, dict):
        return None
    if call.get("error"):
        return str(call["error"])
    if call.get("success") is False:
        return "success=False"
    status = str(call.get("status", "")).lower()
    if status in _FAILED_STATUSES:
        return status
    code = call.get("status_code")
    if isinstance(code, int) and code >= 400:
        return f"HTTP {code}"
    return None


def find_tool_failures(steps: List[Dict[str, Any]]) -> List[Finding]:
    """One finding per failing tool — at the first step it failed, with the total count."""
    first: Dict[str, Tuple[Dict[str, Any], str]] = {}
    counts: Dict[str, int] = {}
    for step in steps:
        for call in step.get("tool_calls") or []:
            reason = tool_failure_reason(call)
            if reason is None:
                continue
            name = str(call.get("name", "unknown_tool"))
            counts[name] = counts.get(name, 0) + 1
            first.setdefault(name, (step, reason))
    findings = []
    for name, (step, reason) in first.items():
        times = f" ({counts[name]} failed calls in this session)" if counts[name] > 1 else ""
        findings.append(Finding(
            check="tool_failure",
            step_number=int(step.get("step_number", 0)),
            step_name=str(step.get("step_name", "")),
            message=f"{name} failed: {reason}{times}",
        ))
    return findings


def find_loops(steps: List[Dict[str, Any]], min_repeats: int = 3) -> List[Finding]:
    """Flag runs of >= min_repeats consecutive steps that repeat the same step, tools and output."""
    def signature(step: Dict[str, Any]) -> Tuple[str, Tuple[str, ...], str]:
        tools = tuple(str(c.get("name", "")) for c in step.get("tool_calls") or [] if isinstance(c, dict))
        return str(step.get("step_name", "")), tools, str(step.get("output", ""))

    findings = []
    i = 0
    while i < len(steps):
        j = i
        while j + 1 < len(steps) and signature(steps[j + 1]) == signature(steps[i]):
            j += 1
        run = j - i + 1
        if run >= min_repeats:
            start, end = steps[i], steps[j]
            findings.append(Finding(
                check="loop",
                step_number=int(start.get("step_number", 0)),
                step_name=str(start.get("step_name", "")),
                message=(
                    f"'{start.get('step_name')}' repeated {run} times in a row with identical output "
                    f"(steps {start.get('step_number')}–{end.get('step_number')})"
                ),
                last_step=int(end.get("step_number", 0)),
            ))
        i = j + 1
    return findings


def run_checks(steps: List[Dict[str, Any]]) -> List[Finding]:
    """All deterministic checks, ordered by the step where each problem starts."""
    findings = find_tool_failures(steps) + find_loops(steps)
    return sorted(findings, key=lambda f: (f.step_number, f.check))
