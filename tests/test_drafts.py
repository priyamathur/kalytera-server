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
    assert rule["reason"] == "Refund needs a person to approve it when the amount is over 480"
    assert rule["agent_id"] == "billing"
    assert d["warnings"] == []
    assert any("amount" in e and "480" in e for e in d["evidence"])
    parse_rule(rule)  # the draft is a valid rule


def test_string_values_only_seen_in_failures_become_in():
    failing = [[_call("ship", False, country=c)] for c in ("BR", "IN", "BR", "IN")]
    passing = [[_call("ship", country="US")], [_call("ship", country="CA")]]
    rule = draft_rule("a", "workflow_step", "shipping", failing, passing)["rule"]
    assert rule["match"]["args"] == [{"field": "country", "op": "in", "value": ["BR", "IN"]}]


def test_nested_and_json_string_args():
    failing = [[{"name": "t", "success": False, "input": '{"customer": {"tier": "trial"}}'}]] * 2
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


def test_coverage_replays_sessions():
    failing = [[_call("refund_api", False, amount=900)], [_call("refund_api", False, amount=650)],
               [_call("lookup")]]
    passing = [[_call("refund_api", amount=120)], [_call("refund_api", amount=480)]]
    d = draft_rule("a", "failure_type", "tool_failure", failing, passing)
    assert d["coverage"] == {"failing_matched": 2, "failing_total": 3, "passing_matched": 0, "passing_total": 2}


def test_coverage_counts_loops_in_order():
    failing = [[_call("search")] * 5, [_call("search")] * 2]
    d = draft_rule("a", "failure_type", "loop", failing, [[_call("search")]])
    # a successful session called search once, so the draft flags the 2nd call: both failing sessions match
    assert d["rule"]["session_conditions"][0]["value"] == 2
    assert d["coverage"]["failing_matched"] == 2 and d["coverage"]["passing_matched"] == 0


def test_repeat_count_separates_when_args_do_not():
    failing = [[_call("lookup_order", order_id="a")] * 6, [_call("lookup_order", order_id="b")] * 5]
    passing = [[_call("lookup_order", order_id="c")] * 2, [_call("lookup_order", order_id="d")]]
    d = draft_rule("a", "workflow_step", "find_order", failing, passing)
    cond = d["rule"]["session_conditions"][0]
    assert cond["value"] == 3 and cond["tool"] == "lookup_order"
    assert d["coverage"]["failing_matched"] == 2 and d["coverage"]["passing_matched"] == 0
    assert d["warnings"] == []


def test_unique_ids_are_not_proposed_as_value_lists():
    failing = [[_call("refund_api", False, order_id=f"o{i}")] for i in range(5)]
    passing = [[_call("refund_api", order_id=f"p{i}")] for i in range(5)]
    d = draft_rule("a", "failure_type", "tool_failure", failing, passing)
    assert d["rule"]["match"]["args"] == []


def test_one_mislabelled_session_does_not_block_the_cutoff():
    # What production did: the judge passed one large refund among 30 that failed.
    failing = [[_call("refund_api", False, amount=a)] for a in [620, 750, 890, 940, 1200] * 6][:29]
    passing = [[_call("refund_api", amount=a)] for a in [25, 60, 120, 199, 310, 450] * 7] + \
              [[_call("refund_api", amount=1350)]]
    d = draft_rule("a", "workflow_step", "issue_refund", failing, passing)
    assert d["rule"]["match"]["args"] == [{"field": "amount", "op": ">", "value": 450}]
    assert d["coverage"]["failing_matched"] == 29 and d["coverage"]["passing_matched"] == 1
    assert any("29 of 29 failing calls" in e and "only 1 of 43 passing" in e for e in d["evidence"])


def test_noise_beyond_the_limits_gives_no_cutoff():
    failing = [[_call("refund_api", False, amount=a)] for a in (900, 100, 120, 950)]   # only half are large
    passing = [[_call("refund_api", amount=a)] for a in (110, 130, 90)]
    assert draft_rule("a", "failure_type", "x", failing, passing)["rule"]["match"]["args"] == []


def test_lower_cutoff_mirror_case():
    failing = [[_call("transfer", False, balance=a)] for a in (5, 10, 2, 8)]
    passing = [[_call("transfer", balance=a)] for a in (50, 80, 120, 300)]
    assert draft_rule("a", "failure_type", "x", failing, passing)["rule"]["match"]["args"] == [
        {"field": "balance", "op": "<", "value": 50}]
