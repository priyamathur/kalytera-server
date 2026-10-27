"""Impact report: before/after numbers computed from judged sessions, rule history and guard events."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from db.models import AgentOrg, EvalResult, GuardEvent, GuardRule
from test_guard import AGENT, REFUND_CAP, env  # noqa: F401

NOW = datetime.now(timezone.utc)
SOURCE = {"pattern_type": "failure_type", "pattern_value": "hallucination"}


def _day(n: float) -> datetime:
    return NOW - timedelta(days=n)


def _session(db: Any, sid: str, at: datetime, failed: bool, ftype: str = "hallucination") -> None:
    db.add(EvalResult(log_id=f"log-{sid}", session_id=sid, agent_id=AGENT, accuracy=0.5, goal_alignment=0.5,
                      decision_quality=0.5, completeness=0.5, overall_score=0.3 if failed else 0.9, passed=not failed,
                      failure_type=ftype if failed else None, failure_step="issue_refund" if failed else None,
                      evaluated_at=at))


def _event(db: Any, sid: str, at: datetime, blocked: bool) -> None:
    db.add(GuardEvent(org_id="org-1", agent_id=AGENT, session_id=sid, tool="refund_api", args_hash="h",
                      decision="DENY" if blocked else "ALLOW", rule_id="refund_cap" if blocked else None,
                      rule_version=2 if blocked else None, timestamp=at,
                      shadow_hits="[]" if blocked else json.dumps([{"rule_id": "refund_cap", "rule_version": 1,
                                                                    "action": "DENY"}])))


def _seed(env: SimpleNamespace) -> None:  # noqa: F811
    """20 days. Rule watches from day 20 and blocks from day 10.5.
    Before: 3 hallucinations a day (days 20..11). After: one every other day (days 10, 8, 6, 4, 2)."""
    r = env.client.post("/rules", json={**REFUND_CAP, "source": SOURCE})
    assert r.status_code == 201, r.text
    assert env.client.post("/rules/refund_cap/promote", params={"agent_id": AGENT}).status_code == 200
    db = env.session()
    db.add(AgentOrg(agent_id=AGENT, org_id="org-1"))
    for v in db.query(GuardRule).filter(GuardRule.rule_id == "refund_cap").all():
        v.created_at = _day(20) if v.version == 1 else _day(10.5)
    for d in range(20, 10, -1):
        for i in range(3):
            _session(db, f"b{d}-{i}", _day(d), failed=True)
            _event(db, f"b{d}-{i}", _day(d), blocked=False)  # the rule would have blocked these
        for i in range(2):
            _session(db, f"bp{d}-{i}", _day(d), failed=False)
    for d in range(10, 0, -1):
        if d % 2 == 0:
            _session(db, f"a{d}", _day(d), failed=True)
        _event(db, f"blk{d}", _day(d), blocked=True)
        _session(db, f"blk{d}", _day(d), failed=False)  # blocked, and the agent explained instead
        for i in range(3):
            _session(db, f"ap{d}-{i}", _day(d), failed=False)
    _event(db, "dashboard-test-refund_cap-ab12", _day(1), blocked=True)  # a dashboard live check
    _session(db, "other-type", _day(3), failed=True, ftype="tool_failure")  # a different problem
    db.commit()
    db.close()


def test_report_compares_the_problem_before_and_after_blocking(env: SimpleNamespace) -> None:  # noqa: F811
    _seed(env)
    r = env.client.get(f"/agents/{AGENT}/impact")
    assert r.status_code == 200, r.text
    rule = r.json()["rules"][0]
    assert (rule["rule_id"], rule["mode"], rule["problem"]) == ("refund_cap", "enforce", SOURCE)
    ba = rule["problem_before_after"]
    assert ba["before_per_day"] == round(30 / 9.5, 2)  # tool_failure isn't this problem
    assert ba["after_per_day"] == round(5 / 10.5, 2)
    assert rule["blocked_sessions"] == 10  # the dashboard check isn't counted


def test_rule_stats_ignore_dashboard_checks_too(env: SimpleNamespace) -> None:  # noqa: F811
    _seed(env)
    stats = env.client.get("/rules/refund_cap/stats", params={"agent_id": AGENT}).json()
    assert stats["denied"] == 10 and stats["would_block"] == 30


def test_too_little_time_after_blocking_says_so(env: SimpleNamespace) -> None:  # noqa: F811
    _seed(env)
    db = env.session()
    for v in db.query(GuardRule).filter(GuardRule.rule_id == "refund_cap", GuardRule.version == 2).all():
        v.created_at = _day(3)
    db.commit()
    db.close()
    ba = env.client.get(f"/agents/{AGENT}/impact").json()["rules"][0]["problem_before_after"]
    assert ba["after_per_day"] is None and ba["days_after"] == 3.0  # under 7 days: no comparison


def test_block_feedback_counts_wrong_blocks(env: SimpleNamespace) -> None:  # noqa: F811
    _seed(env)
    blocks = env.client.get(f"/agents/{AGENT}/blocks").json()["blocks"]
    assert len(blocks) == 10 and blocks[0]["session_id"] == "blk1" and blocks[0]["verdict"] is None
    assert all(not b["session_id"].startswith("dashboard-test-") for b in blocks)
    ok = env.client.post(f"/agents/{AGENT}/blocks/feedback",
                         json={"session_id": "blk1", "rule_id": "refund_cap", "wrong": True, "note": "VIP customer"})
    assert ok.status_code == 200 and ok.json()["verdict"] == "wrong"
    env.client.post(f"/agents/{AGENT}/blocks/feedback", json={"session_id": "blk2", "rule_id": "refund_cap",
                                                              "wrong": False})
    # Changing your mind updates the verdict instead of adding a second one.
    env.client.post(f"/agents/{AGENT}/blocks/feedback", json={"session_id": "blk2", "rule_id": "refund_cap",
                                                              "wrong": True})
    env.client.post(f"/agents/{AGENT}/blocks/feedback", json={"session_id": "blk2", "rule_id": "refund_cap",
                                                              "wrong": False})
    t = env.client.get(f"/agents/{AGENT}/impact").json()["rules"][0]
    assert (t["marked_wrong"], t["marked_right"], t["unreviewed"]) == (1, 1, 8)
    blocks = env.client.get(f"/agents/{AGENT}/blocks", params={"rule_id": "refund_cap"}).json()["blocks"]
    assert (blocks[0]["verdict"], blocks[0]["note"]) == ("wrong", "VIP customer")


def test_feedback_needs_a_real_block(env: SimpleNamespace) -> None:  # noqa: F811
    _seed(env)
    r = env.client.post(f"/agents/{AGENT}/blocks/feedback",
                        json={"session_id": "b20-0", "rule_id": "refund_cap", "wrong": True})  # only would-block
    assert r.status_code == 404


def test_another_account_cannot_see_the_report(env: SimpleNamespace) -> None:  # noqa: F811
    _seed(env)
    env.org = SimpleNamespace(id="org-2")
    assert env.client.get(f"/agents/{AGENT}/impact").status_code == 404
    assert env.client.get(f"/agents/{AGENT}/blocks").status_code == 404
    assert env.client.post(f"/agents/{AGENT}/blocks/feedback",
                           json={"session_id": "blk1", "rule_id": "refund_cap", "wrong": True}).status_code == 404


def test_an_agent_without_rules(env: SimpleNamespace) -> None:  # noqa: F811
    db = env.session()
    db.add(AgentOrg(agent_id=AGENT, org_id="org-1"))
    _session(db, "s1", _day(2), failed=True)
    db.commit()
    db.close()
    rep = env.client.get(f"/agents/{AGENT}/impact").json()
    assert (rep["rules"], rep["before_after_blocking"]) == ([], None)


def test_overall_failure_rate_before_and_after_blocking(env: SimpleNamespace) -> None:  # noqa: F811
    _seed(env)
    ba = env.client.get(f"/agents/{AGENT}/impact").json()["before_after_blocking"]
    assert ba["comparable"] is True
    assert (ba["before_sessions"], ba["before_failed"]) == (50, 30)
    assert (ba["after_sessions"], ba["after_failed"]) == (5 + 10 + 30 + 1, 5 + 1)


def test_delete_agent_data_removes_everything_and_frees_the_name(env: SimpleNamespace) -> None:  # noqa: F811
    _seed(env)
    env.client.post(f"/agents/{AGENT}/blocks/feedback", json={"session_id": "blk1", "rule_id": "refund_cap",
                                                              "wrong": True})
    assert env.client.post("/replies/held", json={"agent_id": AGENT, "reply": "Refund done!",
                                                  "reason": "refund_api failed"}).status_code == 201
    env.org = SimpleNamespace(id="org-2")
    assert env.client.delete(f"/agents/{AGENT}/data").status_code == 404  # not yours
    env.org = SimpleNamespace(id="org-1")
    r = env.client.delete(f"/agents/{AGENT}/data")
    assert r.status_code == 200, r.text
    d = r.json()["deleted"]
    assert d["eval_results"] == 96 and d["guard_events"] == 41 and d["guard_rules"] == 2
    assert d["block_feedback"] == 1 and d["agent_orgs"] == 1 and d["held_replies"] == 1
    db = env.session()
    for model in (EvalResult, GuardEvent, GuardRule, AgentOrg):
        assert db.query(model).filter(model.agent_id == AGENT).count() == 0
    db.close()
    assert env.client.get(f"/agents/{AGENT}/impact").status_code == 404  # no longer this org's agent


def test_retention_deletes_old_production_data_but_keeps_rules(env: SimpleNamespace) -> None:  # noqa: F811
    from db.models import Organization
    from db.queries import purge_expired_data

    _seed(env)  # 20 days of sessions and rule checks
    db = env.session()
    db.add(Organization(id="org-1", name="Acme"))
    db.add(Organization(id="org-2", name="Other", retention_days=30))  # no agents: nothing to do
    db.commit()
    db.close()
    assert env.client.put("/account/retention", json={"retention_days": 45}).status_code == 422
    assert env.client.put("/account/retention", json={"retention_days": 30}).json() == {"retention_days": 30}
    db = env.session()
    assert purge_expired_data(db)["eval_results"] == 0  # nothing older than 30 days yet
    db.query(Organization).filter(Organization.id == "org-1").one().retention_days = 30
    db.commit()
    deleted = purge_expired_data(db, now=NOW + timedelta(days=20))  # 20 days later: days 20..11 are now >30 days old
    assert deleted["eval_results"] == 50 and deleted["guard_events"] == 30
    assert db.query(EvalResult).filter(EvalResult.agent_id == AGENT).count() == 96 - 50
    assert db.query(GuardRule).filter(GuardRule.agent_id == AGENT).count() == 2  # rules are kept
    db.close()
    assert env.client.put("/account/retention", json={"retention_days": None}).json() == {"retention_days": None}
