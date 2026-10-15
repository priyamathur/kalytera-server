"""Memory beyond one agent: profiles, rules from your other agents, anonymous shared patterns."""
import json
from types import SimpleNamespace
from typing import Any

from test_guard import env  # noqa: F401

from api.memory_api import (
    MIN_COMPANIES,
    action_category,
    known_problems,
    org_hash,
    refresh_shared_facts,
    rule_shape,
)
from db.models import AgentLog, AgentOrg, EvalResult, GlobalFact, GuardRule, LossPattern, Organization

REFUND_RULE = {"id": "refund_cap", "action": "DENY", "reason": "over limit",
               "match": {"tool": "acme_refund_api", "args": [{"field": "amount", "op": ">", "value": 450}]}}


def _agent(db: Any, org: str, agent: str, industry: str = "retail", agent_type: str = "support",
           failure_type: str = "hallucination", failing: int = 6, passing: int = 4) -> None:
    db.add(AgentOrg(agent_id=agent, org_id=org, industry=industry, agent_type=agent_type, system="langfuse"))
    for i in range(failing + passing):
        bad = i < failing
        sid = f"{agent}-s{i}"
        db.add(AgentLog(id=f"{sid}-1", agent_id=agent, session_id=sid, step_number=1, step_name="turn",
                        input="refund please", output="done", session_ended=True,
                        tool_calls=json.dumps([{"name": "acme_refund_api", "input": {"amount": 900 if bad else 40},
                                                "success": not bad}])))
        db.add(EvalResult(log_id=f"{sid}-1", session_id=sid, agent_id=agent, accuracy=.5, goal_alignment=.5,
                          decision_quality=.5, completeness=.5, overall_score=.3 if bad else .9, passed=not bad,
                          failure_type=failure_type if bad else None))
    db.add(LossPattern(agent_id=agent, pattern_type="failure_type", pattern_value=failure_type,
                       failure_count=failing, total_count=failing + passing, failure_rate=.6,
                       pct_of_all_failures=1, root_cause="Claimed a refund went through",
                       first_seen=__import__("datetime").datetime.now(), last_seen=__import__("datetime").datetime.now()))


def _company(db: Any, n: int, share: bool = True, **kw: Any) -> str:
    org = f"org-{n}"
    db.add(Organization(id=org, name=f"Company {n}", share_patterns=share))
    _agent(db, org, f"bot-{n}", **kw)
    db.add(GuardRule(org_id=org, agent_id=f"bot-{n}", rule_id="refund_cap", version=1, mode="enforce",
                     body=json.dumps({**REFUND_RULE, "agent_id": f"bot-{n}"}), is_active=True))
    return org


def test_actions_and_rules_are_reduced_to_categories_and_shapes() -> None:
    assert action_category("acme_refund_api") == "refund" and action_category("issue_payment") == "payment"
    assert action_category("lookup_order_status") == "order" and action_category("frobnicate") == "other"
    assert rule_shape(REFUND_RULE) == "amount_above"
    assert rule_shape({"match": {"tool": "x"}, "session_conditions": [{"repeat": 3}]}) == "repeated"


def test_shared_patterns_appear_only_from_five_companies(env: SimpleNamespace) -> None:  # noqa: F811
    db = env.session()
    for n in range(2, 2 + MIN_COMPANIES - 1):   # 4 other companies
        _company(db, n)
    db.add(Organization(id="org-1", name="Me"))
    _agent(db, "org-1", "my-bot")
    db.commit()
    refresh_shared_facts(db)
    assert known_problems(db, "retail", "support", exclude_org="org-1") == {"problems": [], "rules": []}
    _company(db, 99)                              # the 5th
    db.commit()
    refresh_shared_facts(db)
    known = known_problems(db, "retail", "support", exclude_org="org-1")
    assert known["problems"] == [{"failure_type": "hallucination", "action_category": "refund", "rule_shape": "",
                                  "companies": 5}]
    assert known["rules"] == [{"failure_type": "", "action_category": "refund", "rule_shape": "amount_above",
                               "companies": 5}]
    assert known_problems(db, "fintech", "support", exclude_org="org-1")["problems"] == []  # other segment
    db.close()


def test_nothing_identifying_is_stored(env: SimpleNamespace) -> None:  # noqa: F811
    db = env.session()
    for n in range(2, 8):
        _company(db, n)
    _company(db, 50, failure_type="acme_brand_tone")  # a custom dimension: could identify the company
    db.commit()
    refresh_shared_facts(db)
    stored = json.dumps([{c.name: str(getattr(f, c.name)) for c in GlobalFact.__table__.columns}
                         for f in db.query(GlobalFact).all()])
    for secret in ("acme", "refund_api", "450", "org-", "bot-", "Company", "Claimed"):
        assert secret not in stored, secret
    assert "acme_brand_tone" not in stored
    db.close()


def test_turning_sharing_off_removes_contributions_now(env: SimpleNamespace) -> None:  # noqa: F811
    db = env.session()
    for n in range(2, 8):
        _company(db, n)
    db.add(Organization(id="org-1", name="Me"))
    db.add(AgentOrg(agent_id="x", org_id="org-1"))
    db.commit()
    refresh_shared_facts(db)
    db.close()
    env.org = SimpleNamespace(id="org-2", name="Company 2", tier="free")
    assert env.client.get("/account/sharing").json() == {"share_patterns": True}  # on by default
    assert env.client.put("/account/sharing", json={"share_patterns": False}).json() == {"share_patterns": False}
    db = env.session()
    assert db.query(GlobalFact).filter(GlobalFact.org_hash == org_hash("org-2")).count() == 0
    refresh_shared_facts(db)  # and it stays out
    assert db.query(GlobalFact).filter(GlobalFact.org_hash == org_hash("org-2")).count() == 0
    assert known_problems(db, "retail", "support", exclude_org="org-1")["problems"][0]["companies"] == 5
    db.close()


def test_profile_is_validated_and_private_to_the_account(env: SimpleNamespace) -> None:  # noqa: F811
    db = env.session()
    db.add(AgentOrg(agent_id="my-bot", org_id="org-1"))
    db.commit()
    db.close()
    r = env.client.get("/agents/my-bot/profile").json()
    assert r["industry"] is None and "retail" in r["choices"]["industry"]
    assert env.client.put("/agents/my-bot/profile", json={"industry": "space"}).status_code == 422
    assert env.client.put("/agents/my-bot/profile", json={"industry": "retail", "agent_type": "support"}).json() == \
        {"industry": "retail", "agent_type": "support", "system": None}
    env.org = SimpleNamespace(id="org-2", name="Other", tier="free")
    assert env.client.get("/agents/my-bot/profile").status_code == 404


def test_known_problems_need_a_profile(env: SimpleNamespace) -> None:  # noqa: F811
    db = env.session()
    db.add(AgentOrg(agent_id="my-bot", org_id="org-1"))
    db.commit()
    db.close()
    assert env.client.get("/agents/my-bot/known-problems").json()["profile"] is False


def test_rules_from_your_other_agents_are_checked_on_this_agent_first(env: SimpleNamespace) -> None:  # noqa: F811
    db = env.session()
    _company(db, 1)                       # org-1: bot-1 has the refund rule
    _agent(db, "org-1", "billing-bot")    # org-1's second agent uses the same refund action
    _company(db, 7)                       # another company's rule must never be offered
    db.commit()
    db.close()
    rules = env.client.get("/agents/billing-bot/rules/from-account").json()["rules"]
    assert len(rules) == 1
    r = rules[0]
    assert r["from_agent"] == "bot-1" and r["rule"]["agent_id"] == "billing-bot"
    assert r["coverage"] == {"failing_matched": 6, "failing_total": 6, "passing_matched": 0, "passing_total": 4}
    assert env.client.get("/agents/bot-1/rules/from-account").json()["rules"] == []  # it already has it
