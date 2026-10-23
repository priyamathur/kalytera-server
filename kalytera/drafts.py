"""
Draft a guard rule from a detected failure pattern (spec step 5).

Pure: takes the tool calls from failing and passing sessions and proposes a
rule plus a plain-English list of the evidence behind it. Nothing is saved —
a person edits the draft and creates it, and it starts in shadow mode.

Heuristics (deliberately simple, every one explained in `evidence`):
  - tool:   the tool with the most failed calls in failing sessions, else the
            tool called most often in them
  - number: `field > T` (or `<`), T a passing value, catching at least 60% of
            failing calls and at most 10% of passing ones — the odd mislabelled
            session doesn't stop a clear cut-off
  - text:   `field in [...]` if failing sessions used a few values that
            passing sessions never did, and each value recurs across failing
            sessions (so IDs, which are unique per session, are never proposed)
  - repeat: if failing sessions call the tool more often than any passing
            session does, `count_in_window >= N` with N one above the most
            calls a passing session made (for loop patterns with nothing to
            compare against: the fewest calls in a failing session, at least 3)
"""
import json
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple

MAX_IN_VALUES = 5
MIN_FAIL_SHARE = 0.6    # a numeric cut-off must catch at least this share of failing calls
MAX_PASS_SHARE = 0.1    # …and match at most this share of passing calls
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


def _calls_named(sessions: Iterable[List[Call]], tool: str) -> List[Tuple[int, Call]]:
    """(session index, call) for every call to `tool`."""
    return [(i, c) for i, calls in enumerate(sessions) for c in calls if c.get("name") == tool]


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


def _arg_predicates(fail_calls: List[Tuple[int, Call]],
                    pass_calls: List[Tuple[int, Call]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    fail_args = [_flatten(c.get("input")) for _, c in fail_calls]
    pass_args = [_flatten(c.get("input")) for _, c in pass_calls]
    fail_sessions = [i for i, _ in fail_calls]
    fields = sorted({f for a in fail_args for f in a})
    preds: List[Dict[str, Any]] = []
    evidence: List[str] = []
    for field in fields:
        fv = [a[field] for a in fail_args if field in a]
        pv = [a[field] for a in pass_args if field in a]
        if not fv or not pv:
            continue
        if all(_is_number(v) for v in fv + pv):
            best = _threshold(fv, pv)
            if best:
                op, t, fa, pa = best
                preds.append({"field": field, "op": op, "value": t})
                side = "above" if op == ">" else "below"
                if fa == len(fv) and pa == 0:
                    evidence.append(f"Every failing call had `{field}` {side} {t} (failing: {min(fv)}–{max(fv)}); "
                                    f"no passing call did.")
                else:
                    evidence.append(f"{fa} of {len(fv)} failing calls had `{field}` {side} {t}; "
                                    f"only {pa} of {len(pv)} passing calls did.")
        elif all(isinstance(v, str) for v in fv + pv):
            only_failing = sorted(set(fv) - set(pv))
            sessions_with_field = {fail_sessions[k] for k, a in enumerate(fail_args) if field in a}
            recurs = len(only_failing) * 2 <= len(sessions_with_field)
            if only_failing and set(fv) <= set(only_failing) and len(only_failing) <= MAX_IN_VALUES and recurs:
                preds.append({"field": field, "op": "in", "value": only_failing})
                evidence.append(f"Failing calls used `{field}` = {', '.join(only_failing)}; passing calls never did.")
    return preds, evidence


def _threshold(fv: List[float], pv: List[float]) -> Optional[Tuple[str, float, int, int]]:
    """
    (op, value, failing calls matched, passing calls matched) for the cut-off that
    best separates failing values from passing ones, or None.

    Real traffic is noisy — the judge passes the odd bad session — so the cut-off
    doesn't need to be perfect: it must catch at least MIN_FAIL_SHARE of failing
    calls and at most MAX_PASS_SHARE of passing ones. Candidate cut-offs are passing
    values, so the rule reads "more than <a value that went fine>".
    """
    best: Optional[Tuple[int, int, str, float]] = None
    for t in sorted(set(pv)):
        for op, fa, pa in ((">", sum(v > t for v in fv), sum(v > t for v in pv)),
                           ("<", sum(v < t for v in fv), sum(v < t for v in pv))):
            if fa < MIN_FAIL_SHARE * len(fv) or pa > MAX_PASS_SHARE * len(pv):
                continue
            # Most failures caught, then fewest good calls hit, then the most conservative cut-off.
            key = (fa - pa, -pa, op, t if op == ">" else -t)
            if best is None or key > best:
                best = key
    if best is None:
        return None
    _, neg_pa, op, signed_t = best
    t = signed_t if op == ">" else -signed_t
    return op, t, sum((v > t) if op == ">" else (v < t) for v in fv), -neg_pa


def _repeat_threshold(tool: str, failing: List[List[Call]], passing: List[List[Call]],
                      is_loop: bool) -> Optional[Tuple[int, str]]:
    """(N, explanation) for a count_in_window condition, or None if call counts don't separate."""
    fail_counts = [n for n in (sum(1 for c in calls if c.get("name") == tool) for calls in failing) if n > 0]
    pass_counts = [sum(1 for c in calls if c.get("name") == tool) for calls in passing]
    pass_counts = [n for n in pass_counts if n > 0]
    if not fail_counts:
        return None
    if pass_counts:
        if min(fail_counts) <= max(pass_counts):
            return None
        n = max(pass_counts) + 1
        return n, (f"Failing sessions called `{tool}` {min(fail_counts)}+ times; successful ones at most "
                   f"{max(pass_counts)}. The draft flags the {n}th call within {LOOP_WINDOW_S // 60} minutes.")
    if not is_loop:
        return None
    n = max(MIN_LOOP_COUNT, min(fail_counts))
    return n, (f"Loop pattern: failing sessions called `{tool}` at least {n} times, "
               f"so the draft flags the {n}th call within {LOOP_WINDOW_S // 60} minutes.")


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
    Returns {"rule": {...} or None, "evidence": [str], "warnings": [str], "coverage": {...}}.

    coverage: how many failing / passing sessions the drafted rule would have
    matched, replayed call by call — the citation shown next to a suggestion.

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
        return {"rule": None, "evidence": evidence, "warnings": warnings, "coverage": None}

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

    repeat = _repeat_threshold(tool, failing_sessions, passing_sessions,
                               is_loop=pattern_value == "loop" or pattern_type == "loop")
    if repeat and (not preds or pattern_value == "loop"):
        n, why = repeat
        rule["session_conditions"] = [{"type": "count_in_window", "tool": tool, "op": ">=",
                                       "value": n, "window_seconds": LOOP_WINDOW_S}]
        rule["action"] = "ESCALATE"
        evidence.append(why)
    elif not preds:
        if not pass_calls:
            warnings.append(f"No passing session called `{tool}`, so there is nothing to compare against.")
        warnings.append(f"No argument separates failing calls from passing ones. As drafted, the rule matches "
                        f"every call to `{tool}` — narrow it before promoting.")
    rule["reason"] = rule_reason(rule)
    return {"rule": rule, "evidence": evidence, "warnings": warnings,
            "coverage": coverage(rule, failing_sessions, passing_sessions)}


_OP_WORDS = {">": "is over", ">=": "is at least", "<": "is under", "<=": "is at most", "==": "is", "!=": "isn't"}


def _value(v: Any) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, list):
        return " or ".join(_value(x) for x in v)
    return str(v)


def rule_reason(rule: Dict[str, Any]) -> str:
    """What the rule does, in words an end customer can read: an agent passes it on when an action is
    stopped ("I can't do that automatically: <reason>"). Never one conversation's details."""
    tool = str((rule.get("match") or {}).get("tool") or "This action")
    words = [w for w in re.split(r"[_\-\s]+", tool) if w and w.lower() not in ("api", "tool", "fn")] or [tool]
    action = " ".join(words).capitalize()
    conds = []
    for p in (rule.get("match") or {}).get("args") or []:
        field = str(p.get("field", "")).replace("_", " ").split(".")[-1]
        verb = "is" if p.get("op") == "in" else _OP_WORDS.get(str(p.get("op")), str(p.get("op")))
        conds.append(f"the {field} {verb} {_value(p.get('value'))}")
    for c in rule.get("session_conditions") or []:
        if c.get("type") == "count_in_window":
            conds.append(f"it's tried {_value(c.get('value'))} times within {int(c.get('window_seconds', 0)) // 60 or 1} "
                         f"minutes")
    when = f" when {' and '.join(conds)}" if conds else ""
    return f"{action} needs a person to approve it{when}"


def _session_matches(rule: Any, calls: List[Call]) -> bool:
    """Replay a session's calls through the rule (enforced) and report whether any call matches."""
    from .rules import ALLOW, SessionHistory, evaluate

    history = SessionHistory()
    for call in calls:
        name = call.get("name")
        if not name:
            continue
        args = call.get("input")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        if evaluate([rule], name, args if isinstance(args, dict) else {}, "s", history).decision != ALLOW:
            return True
        history.record("s", name)
    return False


def coverage(raw_rule: Dict[str, Any], failing: List[List[Call]], passing: List[List[Call]]) -> Dict[str, int]:
    """{"failing_matched", "failing_total", "passing_matched", "passing_total"}."""
    from .rules import parse_rule

    rule = parse_rule({**raw_rule, "mode": "enforce"})
    return {
        "failing_matched": sum(_session_matches(rule, calls) for calls in failing),
        "failing_total": len(failing),
        "passing_matched": sum(_session_matches(rule, calls) for calls in passing),
        "passing_total": len(passing),
    }
