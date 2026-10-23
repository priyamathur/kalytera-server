"""`kalytera quickstart` end to end: traces → refresh (score + patterns) → suggested rule → guard() blocks."""
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

import pytest

from test_guard import env  # noqa: F401  (fixture: in-memory DB, SDK HTTP routed to the API)

import api.refresh_api as refresh_api
import kalytera.judge as judge
from kalytera import quickstart, tracer


def _fake_score_session(steps: List[Any], weights: Optional[Dict[str, float]] = None,
                        pass_threshold: float = 0.7, custom_metrics: Any = None) -> Dict[str, Any]:
    """Stand-in for the LLM judge: a session fails if any tool call failed."""
    bad = next((s for s in steps if any(c.get("success") is False for c in (s.tool_calls or []))), None)
    base = dict(accuracy=0.9, goal_alignment=0.9, decision_quality=0.9, completeness=0.9, helpfulness=0.9,
                factuality=0.9, custom_scores={}, confidence=0.9, eval_error=False)
    if bad is None:
        return {**base, "overall_score": 0.9, "passed": True, "failure_type": None,
                "failure_step": None, "failure_reason": None}
    return {**base, "overall_score": 0.3, "passed": False, "failure_type": "hallucination",
            "failure_step": str(bad.step_number), "failure_reason": "Claimed the refund went through"}


def _start_and_wait(job: Dict[str, Any], agent_id: str) -> None:
    """Run the refresh job before the request returns, so status polls never share the
    in-memory database's single connection with it."""
    refresh_api._run(job, agent_id)


@pytest.fixture()
def qs(env: SimpleNamespace) -> SimpleNamespace:  # noqa: F811
    routed = tracer._http
    env.org = SimpleNamespace(id="org-1", name="Test org", tier="free")  # /trace checks the plan's limit

    def http(method: str, path: str, body: Optional[Dict[str, Any]] = None,
             timeout: Optional[float] = None) -> Tuple[Optional[int], Any, Optional[str]]:
        if path == "/billing/usage":
            return 200, {"org_name": "Test org"}, None
        return routed(method, path, body, timeout)

    with patch.object(tracer, "_http", http), \
         patch.object(refresh_api, "SessionLocal", env.session), \
         patch.object(judge, "score_session", _fake_score_session), \
         patch.object(quickstart.time, "sleep", lambda s: None), \
         patch.object(quickstart, "SEND_THREADS", 1), \
         patch.object(refresh_api, "SCORING_THREADS", 1), \
         patch.object(refresh_api, "_start", _start_and_wait):  # in-memory SQLite: one shared connection
        yield env


def test_sample_data_has_failures_the_rule_can_separate() -> None:
    sessions = quickstart.sample_sessions("t")
    assert len(sessions) == len(quickstart.FAILING_AMOUNTS) + len(quickstart.PASSING_AMOUNTS)
    assert max(quickstart.PASSING_AMOUNTS) < quickstart.REFUND_LIMIT < min(quickstart.FAILING_AMOUNTS)
    assert len(quickstart.FAILING_AMOUNTS) >= 5  # the analyzer needs 5 failures for a pattern
    assert all(s[-1]["session_ended"] for s in sessions)


def test_quickstart_finds_the_pattern_and_blocks(qs: SimpleNamespace, capsys: pytest.CaptureFixture) -> None:
    quickstart.run("kly_live_test", assume_yes=True)
    out = capsys.readouterr().out
    assert "✓ 48 steps recorded" in out
    assert "10 of 24 conversations failed" in out, out
    assert "Block refund_api when amount is more than 450" in out
    assert "Would have caught 10 of 10 failed conversations · 0 of 14 good ones" in out
    assert "guard() → ALLOW   (watching: the rule would have blocked it)" in out
    assert "guard() → DENY" in out
    assert "guard() for a $120 refund → ALLOW" in out

    rules = qs.client.get("/rules", params={"agent_id": quickstart.agent_name(quickstart.AGENT_PREFIX, "kly_live_test")}).json()["rules"]
    assert len(rules) == 1 and rules[0]["mode"] == "enforce"


def test_quickstart_can_run_twice(qs: SimpleNamespace, capsys: pytest.CaptureFixture) -> None:
    quickstart.run("kly_live_test", assume_yes=True)
    quickstart.run("kly_live_test", assume_yes=True)
    out = capsys.readouterr().out
    assert out.count("guard() → DENY") == 2
    agent = quickstart.agent_name(quickstart.AGENT_PREFIX, "kly_live_test")
    assert len(qs.client.get("/rules", params={"agent_id": agent}).json()["rules"]) == 1


def test_refresh_is_scoped_to_the_org(qs: SimpleNamespace) -> None:
    qs.client.post("/trace", json={"id": "x1", "agent_id": "mine", "session_id": "s", "step_number": 1,
                                   "step_name": "a", "input": "", "output": "", "session_ended": True,
                                   "timestamp": "2026-01-01T00:00:00+00:00"})
    assert qs.client.post("/agents/mine/refresh").status_code == 202
    qs.org = SimpleNamespace(id="org-2", name="Other", tier="free")
    assert qs.client.post("/agents/mine/refresh").status_code == 404
    assert qs.client.get("/agents/mine/refresh").status_code == 404


def test_session_is_scored_once(qs: SimpleNamespace) -> None:
    from db.models import EvalResult
    qs.client.post("/trace", json={"id": "y1", "agent_id": "mine", "session_id": "once", "step_number": 1,
                                   "step_name": "a", "input": "", "output": "", "session_ended": True,
                                   "timestamp": "2026-01-01T00:00:00+00:00"})
    assert refresh_api.score_session_once("once", "mine") is True
    assert refresh_api.score_session_once("once", "mine") is False   # already scored
    db = qs.session()
    assert db.query(EvalResult).filter(EvalResult.session_id == "once").count() == 1
    db.close()


def test_no_key_says_how_to_get_one(capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit):
        quickstart.run("")
    assert "kalytera.dev" in capsys.readouterr().out


def test_each_key_gets_its_own_quickstart_agent() -> None:
    a = quickstart.agent_name(quickstart.AGENT_PREFIX, "kly_live_a")
    assert a.startswith("quickstart-refund-bot-") and a == quickstart.agent_name(quickstart.AGENT_PREFIX, "kly_live_a")
    assert a != quickstart.agent_name(quickstart.AGENT_PREFIX, "kly_live_b")


def test_an_agent_id_cannot_be_taken_over_by_another_account(qs: SimpleNamespace) -> None:
    step = {"agent_id": "support-bot", "session_id": "s", "step_number": 1, "step_name": "a",
            "input": "secret", "output": "", "timestamp": "2026-01-01T00:00:00+00:00"}
    assert qs.client.post("/trace", json={**step, "id": "t1"}).status_code == 201
    qs.org = SimpleNamespace(id="org-2", name="Other", tier="free")
    resp = qs.client.post("/trace", json={**step, "id": "t2"})
    assert resp.status_code == 409 and "another Kalytera account" in resp.json()["detail"]
    assert qs.client.get("/agents/support-bot/refresh").status_code == 404  # still not theirs
    qs.org = SimpleNamespace(id="org-1", name="Test org", tier="free")
    assert qs.client.post("/trace", json={**step, "id": "t3"}).status_code == 201  # owner unaffected


def test_demo_agent_cannot_be_claimed(qs: SimpleNamespace) -> None:
    resp = qs.client.post("/trace", json={"id": "d1", "agent_id": "demo-agent", "session_id": "s", "step_number": 1,
                                          "step_name": "a", "input": "", "output": "",
                                          "timestamp": "2026-01-01T00:00:00+00:00"})
    assert resp.status_code == 409


def test_sending_retries_a_restarting_server(qs: SimpleNamespace, capsys: pytest.CaptureFixture) -> None:
    routed = tracer._http
    failures = {"left": 3}

    def flaky(method: str, path: str, body: Optional[Dict[str, Any]] = None,
              timeout: Optional[float] = None) -> Tuple[Optional[int], Any, Optional[str]]:
        if path == "/trace" and failures["left"]:
            failures["left"] -= 1
            return 502, None, None
        return routed(method, path, body, timeout)

    with patch.object(tracer, "_http", flaky):
        quickstart.run("kly_live_test", assume_yes=True)
    assert "✓ 48 steps recorded" in capsys.readouterr().out


def test_sample_agent_is_created_once_per_account(qs: SimpleNamespace) -> None:
    from db.models import AgentLog, EvalResult
    first = qs.client.post("/agents/sample")
    assert first.status_code == 202, first.text
    agent = first.json()["agent_id"]
    assert agent == refresh_api.sample_agent_id("org-1")
    status = qs.client.get(f"/agents/{agent}/refresh").json()
    assert status["state"] == "done" and status["sessions_scored"] == 24 and status["sessions_failed"] == 10
    assert qs.client.post("/agents/sample").status_code == 202      # again: no new data
    db = qs.session()
    assert db.query(AgentLog).filter(AgentLog.agent_id == agent).count() == 48
    assert db.query(EvalResult).filter(EvalResult.agent_id == agent).count() == 24
    db.close()
    sugg = qs.client.get("/rules/suggestions", params={"agent_id": agent}).json()["suggestions"]
    assert sugg[0]["rule"]["match"]["args"] == [{"field": "amount", "op": ">", "value": 450}]
    assert agent in qs.client.get("/agents").json()
    qs.org = SimpleNamespace(id="org-2", name="Other", tier="free")
    assert agent not in qs.client.get("/agents").json()                # not visible to other accounts
    assert qs.client.post("/agents/sample").json()["agent_id"] != agent


def test_two_accounts_with_the_same_session_id_are_judged_apart(qs: SimpleNamespace) -> None:
    """Session IDs are the customer's own (a ticket number): two accounts can both send '1001'.
    Each is judged on its own steps only, and judging one never counts as judging the other."""
    from db.models import EvalResult
    seen: List[List[str]] = []

    def judge_sees(steps: List[Any], **kw: Any) -> Dict[str, Any]:
        seen.append([s.input for s in steps])
        return _fake_score_session(steps, **kw)

    def send(agent: str, text: str) -> None:
        r = qs.client.post("/trace", json={"id": f"{agent}-1", "agent_id": agent, "session_id": "1001",
                                           "step_number": 1, "step_name": "a", "input": text, "output": "",
                                           "session_ended": True, "timestamp": "2026-01-01T00:00:00+00:00"})
        assert r.status_code == 201, r.text

    send("acme-bot", "Acme's private question")
    qs.org = SimpleNamespace(id="org-2", name="Other", tier="free")
    send("globex-bot", "Globex's private question")
    with patch.object(judge, "score_session", judge_sees):
        assert refresh_api.score_session_once("1001", "acme-bot") is True
        assert refresh_api.score_session_once("1001", "globex-bot") is True  # not "already scored"
    assert seen == [["Acme's private question"], ["Globex's private question"]]
    db = qs.session()
    assert sorted(a for (a,) in db.query(EvalResult.agent_id).filter(EvalResult.session_id == "1001")) == \
        ["acme-bot", "globex-bot"]
    db.close()
