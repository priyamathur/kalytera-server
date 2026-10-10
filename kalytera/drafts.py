"""
Draft a guard rule from a detected failure pattern (spec step 5).

Pure: takes the tool calls from failing and passing sessions and proposes a
rule plus a plain-English list of the evidence behind it. Nothing is saved —
a person edits the draft and creates it, and it starts in shadow mode.

Heuristics (deliberately simple, every one explained in `evidence`):
  - tool:   the tool with the most failed calls in failing sessions, else the
            tool called most often in them
  - number: `field > max(passing)` if every failing value is above every
            passing value (or `<` for the mirror case)
  - text:   `field in [...]` if failing sessions used a few values that
            passing sessions never did
  - loop:   for loop patterns, `count_in_window >= N` where N is the smallest
            per-session call count seen in failing sessions (at least 3)
"""
import json
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple

MAX_IN_VALUES = 5
LOOP_WINDOW_S = 600
MIN_LOOP_COUNT = 3

Call = Dict[str, Any]  # {"name", "input", "success", ...} as sent in trace(tool_calls=...)


def _flatten(args: Any, prefix: str = "") -> Dict[str, Any]:
    """{'customer': {'tier': 'gold'}} -> {'customer.tier': 'gold'}. Two levels deep."""
    out: Dict[str, Any] = {}
    if isinstance(args, str) and not prefix:
        try:
            args = json.loads(args)
        except ValueError:
            return out
    if not isinstance(args, dict):
        return out
    for key, value in args.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and not prefix:
            out.update(_flatten(value, f"{path}."))
        elif isinstance(value, (int, float, str)) and not isinstance(value, bool):
            out[path] = value
    return out


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _calls_named(sessions: Iterable[List[Call]], tool: str) -> List[Call]:
    return [c for calls in sessions for c in calls if c.get("name") == tool]


def _pick_tool(failing: List[List[Call]]) -> Tuple[Optional[str], str]:
    failed = Counter(c.get("name") for calls in failing for c in calls
                     if c.get("name") and c.get("success") is False)
    if failed:
        tool, n = failed.most_common(1)[0]
        return tool, f"`{tool}` had the most failed calls in these sessions ({n})."
    used = Counter(c.get("name") for calls in failing for c in calls if c.get("name"))
    if used:
        tool, n = used.most_common(1)[0]
        return tool, f"`{tool}` was the tool called most often in these sessions ({n} calls)."
    return None, "No tool calls were recorded in these sessions."


def _arg_predicates(fail_calls: List[Call], pass_calls: List[Call]) -> Tuple[List[Dict[str, Any]], List[str]]:
    fail_args = [_flatten(c.get("input")) for c in fail_calls]
    pass_args = [_flatten(c.get("input")) for c in pass_calls]
    fields = sorted({f for a in fail_args for f in a})
    preds: List[Dict[str, Any]] = []
    evidence: List[str] = []
    for field in fields:
        fv = [a[field] for a in fail_args if field in a]
        pv = [a[field] for a in pass_args if field in a]
        if not fv or not pv:
            continue
        if all(_is_number(v) for v in fv + pv):
            if min(fv) > max(pv):
                preds.append({"field": field, "op": ">", "value": max(pv)})
                evidence.append(f"Every failing call had `{field}` above {max(pv)} (failing: {min(fv)}–{max(fv)}); "
                                f"no passing call did.")
            elif max(fv) < min(pv):
                preds.append({"field": field, "op": "<", "value": min(pv)})
                evidence.append(f"Every failing call had `{field}` below {min(pv)}; no passing call did.")
        elif all(isinstance(v, str) for v in fv + pv):
            only_failing = sorted(set(fv) - set(pv))
            if only_failing and set(fv) <= set(only_failing) and len(only_failing) <= MAX_IN_VALUES:
                preds.append({"field": field, "op": "in", "value": only_failing})
                evidence.append(f"Failing calls used `{field}` = {', '.join(only_failing)}; passing calls never did.")
    return preds, evidence


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:48] or "rule"


def draft_rule(
    agent_id: str,
    pattern_type: str,
    pattern_value: str,
    failing_sessions: List[List[Call]],
    passing_sessions: List[List[Call]],
    root_cause: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Returns {"rule": {...} or None, "evidence": [str], "warnings": [str]}.

    failing_sessions / passing_sessions: the tool calls of each session, in order.
    """
    evidence = [f"Built from {len(failing_sessions)} failing and {len(passing_sessions)} passing session(s) "
                f"for pattern {pattern_type} = {pattern_value}."]
    warnings: List[str] = []

    tool, why = _pick_tool(failing_sessions)
    evidence.append(why)
    if tool is None:
        warnings.append("Can't draft a rule without tool calls. Pass tool_calls=[...] to trace() so "
                        "Kalytera can see what the agent did.")
        return {"rule": None, "evidence": evidence, "warnings": warnings}

    fail_calls = _calls_named(failing_sessions, tool)
    pass_calls = _calls_named(passing_sessions, tool)
    preds, arg_evidence = _arg_predicates(fail_calls, pass_calls)
    evidence.extend(arg_evidence)

    rule: Dict[str, Any] = {
        "id": _slug(f"{tool}_{pattern_value}"),
        "agent_id": agent_id,
        "match": {"tool": tool, "args": preds},
        "action": "DENY",
        "reason": root_cause or f"Matches failure pattern {pattern_type} = {pattern_value}",
    }

    if pattern_value == "loop" or pattern_type == "loop":
        counts = [sum(1 for c in calls if c.get("name") == tool) for calls in failing_sessions]
        counts = [n for n in counts if n > 0]
        n = max(MIN_LOOP_COUNT, min(counts)) if counts else MIN_LOOP_COUNT
        rule["session_conditions"] = [{"type": "count_in_window", "tool": tool, "op": ">=",
                                       "value": n, "window_seconds": LOOP_WINDOW_S}]
        rule["action"] = "ESCALATE"
        evidence.append(f"Loop pattern: failing sessions called `{tool}` at least {n} times, "
                        f"so the draft escalates the {n}th call within {LOOP_WINDOW_S // 60} minutes.")
    elif not preds:
        if not pass_calls:
            warnings.append(f"No passing session called `{tool}`, so there is nothing to compare against.")
        warnings.append(f"No argument separates failing calls from passing ones. As drafted, the rule matches "
                        f"every call to `{tool}` — narrow it before promoting.")
    return {"rule": rule, "evidence": evidence, "warnings": warnings}
