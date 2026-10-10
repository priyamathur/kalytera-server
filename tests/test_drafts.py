"""Tests for kalytera/drafts.py — drafting a guard rule from a failure pattern."""
from kalytera.drafts import draft_rule
from kalytera.rules import parse_rule


def _call(name, success=True, **args):
    return {"name": name, "input": args, "success": success}


def test_numeric_threshold_separates_failing_from_passing():
    failing = [[_call("lookup"), _call("refund_api", False, amount=900)],
               [_call("refund_api", False, amount=650)]]
    passing = [[_call("refund_api", amount=120)], [_call("refund_api", amount=480)]]
    d = draft_rule("billing", "failure_type", "tool_failure", failing, passing, root_cause="Large refunds fail")
    rule = d["rule"]
    assert rule["match"] == {"tool": "refund_api", "args": [{"field": "amount", "op": ">", "value": 480}]}
    assert rule["reason"] == "Large refunds fail" and rule["agent_id"] == "billing"
    assert d["warnings"] == []
    assert any("amount" in e and "480" in e for e in d["evidence"])
    parse_rule(rule)  # the draft is a valid rule


def test_string_values_only_seen_in_failures_become_in():
    failing = [[_call("ship", False, country="BR")], [_call("ship", False, country="IN")]]
    passing = [[_call("ship", country="US")], [_call("ship", country="CA")]]
    rule = draft_rule("a", "workflow_step", "shipping", failing, passing)["rule"]
    assert rule["match"]["args"] == [{"field": "country", "op": "in", "value": ["BR", "IN"]}]


def test_nested_and_json_string_args():
    failing = [[{"name": "t", "success": False, "input": '{"customer": {"tier": "trial"}}'}]]
    passing = [[{"name": "t", "input": {"customer": {"tier": "gold"}}}]]
    rule = draft_rule("a", "failure_type", "wrong_answer", failing, passing)["rule"]
    assert rule["match"]["args"] == [{"field": "customer.tier", "op": "in", "value": ["trial"]}]


def test_overlapping_values_give_tool_only_rule_with_warning():
    failing = [[_call("refund_api", False, amount=300)]]
    passing = [[_call("refund_api", amount=500)], [_call("refund_api", amount=100)]]
    d = draft_rule("a", "failure_type", "tool_failure", failing, passing)
    assert d["rule"]["match"]["args"] == []
    assert any("matches every call" in w for w in d["warnings"])


def test_loop_pattern_adds_count_in_window_and_escalates():
    failing = [[_call("search")] * 7, [_call("search")] * 4]
    d = draft_rule("a", "failure_type", "loop", failing, [])
    rule = d["rule"]
    assert rule["action"] == "ESCALATE"
    assert rule["session_conditions"] == [{"type": "count_in_window", "tool": "search", "op": ">=",
                                           "value": 4, "window_seconds": 600}]
    parse_rule(rule)


def test_prefers_tool_with_failed_calls():
    failing = [[_call("lookup"), _call("lookup"), _call("lookup"), _call("charge", False, amount=5)]]
    assert draft_rule("a", "failure_type", "tool_failure", failing, [])["rule"]["match"]["tool"] == "charge"


def test_no_tool_calls_gives_no_rule():
    d = draft_rule("a", "failure_type", "goal_drift", [[], []], [])
    assert d["rule"] is None
    assert any("tool_calls" in w for w in d["warnings"])
