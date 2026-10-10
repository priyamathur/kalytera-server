"""Tests for kalytera/rules.py — rule schema validation and in-process evaluation."""
import time
from typing import Any, Dict

import pytest

from kalytera.rules import (
    ALLOW,
    DENY,
    ESCALATE,
    RuleError,
    SessionHistory,
    evaluate,
    parse_rule,
)


def _rule(**overrides: Any) -> Dict[str, Any]:
    raw: Dict[str, Any] = {
        "id": "rule_refund_cap",
        "agent_id": "billing-agent",
        "version": 1,
        "match": {"tool": "refund_api", "args": [{"field": "amount", "op": ">", "value": 500}]},
        "action": "DENY",
        "mode": "enforce",
        "reason": "Refunds over 500 need review",
    }
    raw.update(overrides)
    return raw


def _pred(op: str, value: Any, field: str = "x") -> Dict[str, Any]:
    return _rule(match={"tool": "t", "args": [{"field": field, "op": op, "value": value}]})


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("op,value,actual,expected", [
    ("==", 5, 5, True), ("==", 5, 6, False), ("==", "a", "a", True),
    ("!=", 5, 6, True), ("!=", 5, 5, False),
    (">", 5, 6, True), (">", 5, 5, False),
    (">=", 5, 5, True), (">=", 5, 4, False),
    ("<", 5, 4, True), ("<", 5, 5, False),
    ("<=", 5, 5, True), ("<=", 5, 6, False),
    ("in", ["US", "CA"], "CA", True), ("in", ["US", "CA"], "MX", False),
])
def test_each_operator(op: str, value: Any, actual: Any, expected: bool) -> None:
    rule = parse_rule(_pred(op, value))
    d = evaluate([rule], "t", {"x": actual})
    assert (d.decision == DENY) is expected


def test_missing_field_does_not_match() -> None:
    assert evaluate([parse_rule(_pred(">", 5))], "t", {"y": 10}).decision == ALLOW


def test_type_mismatch_does_not_match_or_raise() -> None:
    assert evaluate([parse_rule(_pred(">", 5))], "t", {"x": "lots"}).decision == ALLOW
    assert evaluate([parse_rule(_pred(">", 0))], "t", {"x": True}).decision == ALLOW


def test_dotted_field_path() -> None:
    rule = parse_rule(_pred("==", "gold", field="customer.tier"))
    assert evaluate([rule], "t", {"customer": {"tier": "gold"}}).decision == DENY
    assert evaluate([rule], "t", {"customer": "gold"}).decision == ALLOW


def test_all_predicates_must_hold() -> None:
    rule = parse_rule(_rule(match={"tool": "refund_api", "args": [
        {"field": "amount", "op": ">", "value": 500},
        {"field": "currency", "op": "==", "value": "USD"},
    ]}))
    assert evaluate([rule], "refund_api", {"amount": 900, "currency": "USD"}).decision == DENY
    assert evaluate([rule], "refund_api", {"amount": 900, "currency": "EUR"}).decision == ALLOW


def test_other_tool_is_not_matched() -> None:
    assert evaluate([parse_rule(_rule())], "lookup_order", {"amount": 900}).decision == ALLOW


def test_rule_without_args_matches_every_call_to_tool() -> None:
    rule = parse_rule(_rule(match={"tool": "delete_account"}))
    assert evaluate([rule], "delete_account").decision == DENY


# ---------------------------------------------------------------------------
# Modes and precedence
# ---------------------------------------------------------------------------

def test_enforce_mode_denies_matching_call() -> None:
    d = evaluate([parse_rule(_rule())], "refund_api", {"amount": 900})
    assert d.decision == DENY
    assert d.rule_id == "rule_refund_cap" and d.rule_version == 1
    assert d.reason == "Refunds over 500 need review"
    assert not d.allowed


def test_shadow_mode_never_changes_decision() -> None:
    rule = parse_rule(_rule(mode="shadow"))
    d = evaluate([rule], "refund_api", {"amount": 900})
    assert d.decision == ALLOW and d.allowed
    assert d.rule_id == ""
    assert [h.rule_id for h in d.shadow_hits] == ["rule_refund_cap"]


def test_shadow_mode_records_nothing_when_not_matching() -> None:
    d = evaluate([parse_rule(_rule(mode="shadow"))], "refund_api", {"amount": 100})
    assert d.decision == ALLOW and d.shadow_hits == ()


def test_deny_beats_escalate() -> None:
    esc = parse_rule(_rule(id="esc", action="ESCALATE"))
    deny = parse_rule(_rule(id="deny"))
    assert evaluate([esc, deny], "refund_api", {"amount": 900}).rule_id == "deny"


def test_escalate_returned_when_only_escalate_matches() -> None:
    d = evaluate([parse_rule(_rule(action="ESCALATE"))], "refund_api", {"amount": 900})
    assert d.decision == ESCALATE


def test_shadow_and_enforce_together() -> None:
    shadow = parse_rule(_rule(id="s", mode="shadow"))
    enforce = parse_rule(_rule(id="e", action="ESCALATE"))
    d = evaluate([shadow, enforce], "refund_api", {"amount": 900})
    assert d.decision == ESCALATE and d.rule_id == "e"
    assert [h.rule_id for h in d.shadow_hits] == ["s"]


def test_mode_defaults_to_shadow() -> None:
    raw = _rule()
    del raw["mode"]
    assert parse_rule(raw).mode == "shadow"


# ---------------------------------------------------------------------------
# count_in_window
# ---------------------------------------------------------------------------

def _window_rule(op: str = ">=", value: int = 3, window: int = 600) -> Any:
    return parse_rule(_rule(
        match={"tool": "refund_api"},
        session_conditions=[{"type": "count_in_window", "tool": "refund_api",
                             "op": op, "value": value, "window_seconds": window}],
    ))


def test_count_in_window_includes_current_call() -> None:
    rule, h, now = _window_rule(), SessionHistory(), 1000.0
    assert evaluate([rule], "refund_api", session_id="s1", history=h, now=now).decision == ALLOW
    h.record("s1", "refund_api", now)
    assert evaluate([rule], "refund_api", session_id="s1", history=h, now=now).decision == ALLOW
    h.record("s1", "refund_api", now)
    # third call
    assert evaluate([rule], "refund_api", session_id="s1", history=h, now=now).decision == DENY


def test_count_in_window_ignores_calls_outside_window() -> None:
    rule, h = _window_rule(window=600), SessionHistory()
    h.record("s1", "refund_api", 0.0)
    h.record("s1", "refund_api", 0.0)
    assert evaluate([rule], "refund_api", session_id="s1", history=h, now=601.0).decision == ALLOW


def test_count_in_window_is_per_session() -> None:
    rule, h = _window_rule(), SessionHistory()
    h.record("s1", "refund_api", 10.0)
    h.record("s1", "refund_api", 10.0)
    assert evaluate([rule], "refund_api", session_id="s2", history=h, now=20.0).decision == ALLOW
    assert evaluate([rule], "refund_api", session_id="s1", history=h, now=20.0).decision == DENY


def test_count_in_window_counts_only_named_tool() -> None:
    rule, h = _window_rule(), SessionHistory()
    h.record("s1", "lookup_order", 10.0)
    h.record("s1", "lookup_order", 10.0)
    assert evaluate([rule], "refund_api", session_id="s1", history=h, now=20.0).decision == ALLOW


def test_count_in_window_on_a_different_tool() -> None:
    # Block refund_api once lookup_order has been called 2+ times (current call not counted).
    rule = parse_rule(_rule(
        match={"tool": "refund_api"},
        session_conditions=[{"type": "count_in_window", "tool": "lookup_order",
                             "op": ">=", "value": 2, "window_seconds": 60}],
    ))
    h = SessionHistory()
    h.record("s1", "lookup_order", 10.0)
    assert evaluate([rule], "refund_api", session_id="s1", history=h, now=20.0).decision == ALLOW
    h.record("s1", "lookup_order", 15.0)
    assert evaluate([rule], "refund_api", session_id="s1", history=h, now=20.0).decision == DENY


def test_count_in_window_without_history_counts_current_call_only() -> None:
    assert evaluate([_window_rule(value=1)], "refund_api", session_id="s1").decision == DENY


def test_session_history_is_bounded() -> None:
    h = SessionHistory(max_sessions=2, max_calls=3)
    for _ in range(5):
        h.record("a", "t", 1.0)
    assert h.count("a", "t", 10, 2.0) == 3
    h.record("b", "t", 1.0)
    h.record("c", "t", 1.0)  # evicts "a"
    assert h.count("a", "t", 10, 2.0) == 0
    assert h.count("c", "t", 10, 2.0) == 1


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("change,message", [
    ({"id": ""}, "id is required"),
    ({"version": 0}, "version"),
    ({"match": {}}, "match.tool"),
    ({"match": {"tool": "t", "args": [{"field": "x", "op": "~=", "value": 1}]}}, "op must be one of"),
    ({"match": {"tool": "t", "args": [{"field": "x", "op": "in", "value": "US"}]}}, "'in' needs a list"),
    ({"match": {"tool": "t", "args": [{"op": "==", "value": 1}]}}, "field is required"),
    ({"match": {"tool": "t", "args": [{"field": "x", "op": "=="}]}}, "value is required"),
    ({"action": "ALLOW"}, "action must be one of"),
    ({"mode": "live"}, "mode must be one of"),
    ({"fail_closed": "yes"}, "fail_closed"),
    ({"session_conditions": [{"type": "rate", "tool": "t", "op": ">", "value": 1, "window_seconds": 1}]}, "type must be one of"),
    ({"session_conditions": [{"type": "count_in_window", "tool": "t", "op": "in", "value": 1, "window_seconds": 1}]}, "comparison operator"),
    ({"session_conditions": [{"type": "count_in_window", "tool": "t", "op": ">", "value": 1, "window_seconds": 0}]}, "window_seconds"),
    ({"session_conditions": [{"type": "count_in_window", "tool": "t", "op": ">", "value": -1, "window_seconds": 5}]}, "non-negative"),
])
def test_invalid_rules_are_rejected(change: Dict[str, Any], message: str) -> None:
    with pytest.raises(RuleError, match=message):
        parse_rule(_rule(**change))


def test_spec_example_rule_parses() -> None:
    rule = parse_rule({
        "id": "rule_refund_cap",
        "agent_id": "billing-agent",
        "version": 1,
        "match": {"tool": "refund_api", "args": [{"field": "amount", "op": ">", "value": 500}]},
        "session_conditions": [{"type": "count_in_window", "tool": "refund_api", "op": ">=", "value": 3, "window_seconds": 600}],
        "action": "DENY",
        "mode": "shadow",
        "reason": "Refunds over 500 need review",
    })
    assert rule.mode == "shadow" and not rule.fail_closed


# ---------------------------------------------------------------------------
# Latency budget: guard() must add < 5 ms at p99 with cached rules
# ---------------------------------------------------------------------------

def test_evaluate_p99_under_5ms_with_100_rules() -> None:
    rules = [parse_rule(_rule(id=f"r{i}", match={"tool": "refund_api", "args": [
        {"field": "amount", "op": ">", "value": 10_000 + i},
        {"field": "customer.region", "op": "in", "value": ["EU", "UK"]},
    ]}, session_conditions=[{"type": "count_in_window", "tool": "refund_api",
                              "op": ">=", "value": 50, "window_seconds": 600}]))
        for i in range(100)]
    h = SessionHistory()
    for _ in range(100):
        h.record("s1", "refund_api")
    args = {"amount": 20_000, "customer": {"region": "EU"}}
    timings = []
    for _ in range(500):
        start = time.perf_counter()
        evaluate(rules, "refund_api", args, "s1", h)
        timings.append(time.perf_counter() - start)
    timings.sort()
    assert timings[int(len(timings) * 0.99)] < 0.005
