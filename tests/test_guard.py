"""Tests for guard rules: the /rules + /guard API (api/guard_api.py) and kalytera.guard()."""
import time
from types import SimpleNamespace
from typing import Any, Dict, Generator, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

with patch("api.database.initialize_database", return_value=True), \
     patch("api.database.engine", MagicMock()), \
     patch("api.database.SessionLocal", MagicMock()):
    from api.main import _resolve_org, app

import kalytera
from api.database import get_db
from db.models import Base, EvalResult
import importlib
guard_mod = importlib.import_module("kalytera.guard")
from kalytera import tracer

AGENT = "billing-agent"

REFUND_CAP: Dict[str, Any] = {
    "id": "refund_cap",
    "agent_id": AGENT,
    "match": {"tool": "refund_api", "args": [{"field": "amount", "op": ">", "value": 500}]},
    "action": "DENY",
    "reason": "Refunds over 500 need review",
}


@pytest.fixture()
def env() -> Generator[SimpleNamespace, None, None]:
    """In-memory SQLite + a switchable org; the SDK's HTTP calls are routed to the TestClient."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    state = SimpleNamespace(org=SimpleNamespace(id="org-1"), api_up=True, session=Session)

    def _db() -> Generator[Any, None, None]:
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[_resolve_org] = lambda: state.org
    client = TestClient(app)
    state.client = client

    def fake_http(method: str, path: str, body: Optional[Dict[str, Any]] = None,
                  timeout: Optional[float] = None) -> Tuple[Optional[int], Any, Optional[str]]:
        if not state.api_up:
            return None, None, "Connection refused"
        resp = client.request(method, path, json=body)
        return resp.status_code, resp.json(), None

    guard_mod._reset()
    with patch.object(tracer, "_http", fake_http), patch.object(tracer, "_agent_id", AGENT), \
         patch.object(guard_mod, "_send", lambda batch: fake_http("POST", "/guard/events", {"events": batch})[0] == 202):
        yield state
    guard_mod.flush()
    guard_mod._reset()
    app.dependency_overrides.clear()


def _create(env: SimpleNamespace, rule: Dict[str, Any] = REFUND_CAP) -> Dict[str, Any]:
    resp = env.client.post("/rules", json=rule)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _stats(env: SimpleNamespace, rule_id: str = "refund_cap") -> Dict[str, Any]:
    guard_mod.flush()
    return env.client.get(f"/rules/{rule_id}/stats", params={"agent_id": AGENT}).json()


# ---------------------------------------------------------------------------
# Rules API
# ---------------------------------------------------------------------------

def test_new_rule_starts_in_shadow_even_if_enforce_requested(env: SimpleNamespace) -> None:
    rule = _create(env, {**REFUND_CAP, "mode": "enforce", "version": 7})
    assert rule["mode"] == "shadow" and rule["version"] == 1


def test_invalid_rule_rejected_with_reason(env: SimpleNamespace) -> None:
    bad = {**REFUND_CAP, "match": {"tool": "t", "args": [{"field": "a", "op": "~", "value": 1}]}}
    resp = env.client.post("/rules", json=bad)
    assert resp.status_code == 422
    assert "op must be one of" in resp.json()["detail"]


def test_duplicate_rule_conflicts(env: SimpleNamespace) -> None:
    _create(env)
    assert env.client.post("/rules", json=REFUND_CAP).status_code == 409


def test_promote_demote_and_edit_create_versions(env: SimpleNamespace) -> None:
    _create(env)
    promoted = env.client.post("/rules/refund_cap/promote", params={"agent_id": AGENT}).json()
    assert promoted["rule"]["mode"] == "enforce" and promoted["rule"]["version"] == 2
    assert "would_block" in promoted["shadow_summary"]
    assert env.client.post("/rules/refund_cap/promote", params={"agent_id": AGENT}).status_code == 409

    edited = env.client.put("/rules/refund_cap", json={
        **REFUND_CAP, "mode": "shadow", "reason": "new reason",
    }).json()
    assert edited["version"] == 3 and edited["mode"] == "enforce"  # edit never changes mode
    assert edited["reason"] == "new reason"

    demoted = env.client.post("/rules/refund_cap/demote", params={"agent_id": AGENT}).json()
    assert demoted["rule"]["mode"] == "shadow" and demoted["rule"]["version"] == 4

    shown = env.client.get("/rules/refund_cap", params={"agent_id": AGENT}).json()
    assert [v["version"] for v in shown["versions"]] == [4, 3, 2, 1]
    listed = env.client.get("/rules", params={"agent_id": AGENT}).json()["rules"]
    assert [(r["id"], r["version"]) for r in listed] == [("refund_cap", 4)]


def test_delete_removes_rule(env: SimpleNamespace) -> None:
    _create(env)
    assert env.client.delete("/rules/refund_cap", params={"agent_id": AGENT}).status_code == 200
    assert env.client.get("/rules", params={"agent_id": AGENT}).json()["rules"] == []
    assert env.client.get("/rules/refund_cap/stats", params={"agent_id": AGENT}).status_code == 404


def test_deleted_rule_can_be_created_again(env: SimpleNamespace) -> None:
    _create(env)
    env.client.post("/rules/refund_cap/promote", params={"agent_id": AGENT})
    env.client.delete("/rules/refund_cap", params={"agent_id": AGENT})
    again = _create(env)
    assert again["version"] == 3 and again["mode"] == "shadow"
    shown = env.client.get("/rules/refund_cap", params={"agent_id": AGENT}).json()
    assert [v["version"] for v in shown["versions"]] == [3]


def test_rules_are_scoped_to_org(env: SimpleNamespace) -> None:
    _create(env)
    env.org = SimpleNamespace(id="org-2")
    assert env.client.get("/rules", params={"agent_id": AGENT}).json()["rules"] == []
    assert env.client.post("/rules/refund_cap/promote", params={"agent_id": AGENT}).status_code == 404
    _create(env)  # same id is free in another org


def test_post_guard_enforce_and_count_in_window(env: SimpleNamespace) -> None:
    _create(env, {
        "id": "refund_loop", "agent_id": AGENT, "match": {"tool": "refund_api"},
        "session_conditions": [{"type": "count_in_window", "tool": "refund_api",
                                "op": ">=", "value": 3, "window_seconds": 600}],
        "action": "ESCALATE", "reason": "3+ refunds",
    })
    env.client.post("/rules/refund_loop/promote", params={"agent_id": AGENT})
    call = {"agent_id": AGENT, "tool": "refund_api", "args": {"amount": 1}, "session_id": "s1"}
    decisions = [env.client.post("/guard", json=call).json()["decision"] for _ in range(3)]
    assert decisions == ["ALLOW", "ALLOW", "ESCALATE"]
    assert env.client.post("/guard", json={**call, "session_id": "s2"}).json()["decision"] == "ALLOW"


# ---------------------------------------------------------------------------
# SDK guard()
# ---------------------------------------------------------------------------

def test_enforce_mode_denies_matching_call(env: SimpleNamespace) -> None:
    _create(env)
    env.client.post("/rules/refund_cap/promote", params={"agent_id": AGENT})
    d = kalytera.guard("refund_api", {"amount": 900}, session_id="s1")
    assert d.decision == "DENY" and not d.allowed
    assert d.rule_id == "refund_cap" and d.rule_version == 2
    assert kalytera.guard("refund_api", {"amount": 100}, session_id="s1").allowed
    assert _stats(env)["denied"] == 1


def test_shadow_mode_never_changes_return_value(env: SimpleNamespace) -> None:
    _create(env)
    d = kalytera.guard("refund_api", {"amount": 900}, session_id="s1")
    assert d.decision == "ALLOW" and d.allowed and d.rule_id == ""
    assert [h.rule_id for h in d.shadow_hits] == ["refund_cap"]
    kalytera.guard("refund_api", {"amount": 800}, session_id="s2")
    kalytera.guard("refund_api", {"amount": 10}, session_id="s3")
    stats = _stats(env)
    assert stats["would_block"] == 2 and stats["would_block_sessions"] == 2 and stats["denied"] == 0


def test_shadow_stats_count_sessions_that_failed(env: SimpleNamespace) -> None:
    _create(env)
    kalytera.guard("refund_api", {"amount": 900}, session_id="bad-session")
    kalytera.guard("refund_api", {"amount": 900}, session_id="good-session")
    db = env.session()
    for sid, passed in [("bad-session", False), ("good-session", True)]:
        db.add(EvalResult(log_id=sid, session_id=sid, agent_id=AGENT, accuracy=0.5, goal_alignment=0.5,
                          decision_quality=0.5, completeness=0.5, overall_score=0.5, passed=passed))
    db.commit()
    db.close()
    assert _stats(env)["would_block_sessions_that_failed"] == 1


def test_api_unreachable_before_rules_load_fails_open(env: SimpleNamespace) -> None:
    env.api_up = False
    d = kalytera.guard("refund_api", {"amount": 900}, session_id="s1")
    assert d.decision == "ALLOW"
    assert "rules unavailable" in d.error


def test_api_unreachable_after_load_uses_cached_rules(env: SimpleNamespace) -> None:
    _create(env)
    env.client.post("/rules/refund_cap/promote", params={"agent_id": AGENT})
    assert kalytera.guard("refund_api", {"amount": 900}).decision == "DENY"
    env.api_up = False
    guard_mod._refresh(AGENT)  # the refresh fails…
    with patch.object(guard_mod, "_refresh_in_background", lambda agent_id: None):
        d = kalytera.guard("refund_api", {"amount": 900})
    assert d.decision == "DENY"  # …but the cached rule still applies
    assert "using 1 cached rule" in d.error


def test_evaluation_error_respects_fail_closed(env: SimpleNamespace) -> None:
    _create(env, {**REFUND_CAP, "fail_closed": True})
    kalytera.guard("refund_api", {"amount": 1})  # load rules
    with patch.object(guard_mod, "evaluate", side_effect=RuntimeError("boom")):
        assert kalytera.guard("refund_api", {"amount": 1}).decision == "DENY"
        assert kalytera.guard("other_tool", {}).decision == "ALLOW"


def test_guard_never_raises_on_bad_input(env: SimpleNamespace) -> None:
    d = kalytera.guard("refund_api", "not a dict", session_id=None)  # type: ignore[arg-type]
    assert d.decision == "ALLOW"


def test_every_call_produces_an_event_including_errors(env: SimpleNamespace) -> None:
    env.api_up = False
    kalytera.guard("refund_api", {"amount": 1}, session_id="s1")
    guard_mod.flush()  # the send fails; the decision is kept for resending
    env.api_up = True
    _create(env)
    guard_mod._refresh(AGENT)  # the SDK retries a failed fetch after RETRY_S; don't wait for it
    with patch.object(guard_mod, "EVENT_RETRY_S", 0.0):
        kalytera.guard("refund_api", {"amount": 900}, session_id="s1")
        guard_mod.flush()
        time.sleep(0.2)
    from db.models import GuardEvent
    db = env.session()
    events = db.query(GuardEvent).order_by(GuardEvent.timestamp).all()
    db.close()
    assert len(events) == 2  # the decision made while the API was down was resent
    assert events[0].error and "rules unavailable" in events[0].error
    assert events[1].shadow_hits and "refund_cap" in events[1].shadow_hits
    assert events[1].args_hash and "900" not in events[1].args_hash  # args are hashed, not stored


def test_cached_guard_p99_under_5ms(env: SimpleNamespace) -> None:
    _create(env)
    kalytera.guard("refund_api", {"amount": 1})  # load rules
    timings = []
    for i in range(500):
        start = time.perf_counter()
        kalytera.guard("refund_api", {"amount": i}, session_id="perf")
        timings.append(time.perf_counter() - start)
    timings.sort()
    assert timings[int(len(timings) * 0.99)] < 0.005


# ---------------------------------------------------------------------------
# POST /rules/draft
# ---------------------------------------------------------------------------

def _seed_pattern(env: SimpleNamespace) -> str:
    import json as _json
    from datetime import datetime, timezone
    from db.models import AgentLog, AgentOrg, LossPattern

    db = env.session()
    db.add(AgentOrg(agent_id=AGENT, org_id="org-1"))
    now = datetime.now(timezone.utc)
    for i, (amount, passed) in enumerate([(900, False), (750, False), (100, True), (300, True)]):
        sid = f"s{i}"
        db.add(AgentLog(id=f"log{i}", agent_id=AGENT, session_id=sid, step_number=1, step_name="refund",
                        input="", output="", tool_calls=_json.dumps([
                            {"name": "refund_api", "input": {"amount": amount}, "success": passed}])))
        db.add(EvalResult(log_id=f"log{i}", session_id=sid, agent_id=AGENT, accuracy=0.5, goal_alignment=0.5,
                          decision_quality=0.5, completeness=0.5, overall_score=0.5, passed=passed,
                          failure_type=None if passed else "tool_failure"))
    db.add(LossPattern(id="pat-1", agent_id=AGENT, pattern_type="failure_type", pattern_value="tool_failure",
                       failure_count=2, total_count=4, failure_rate=0.5, pct_of_all_failures=1.0,
                       root_cause="Refunds above the limit fail", first_seen=now, last_seen=now))
    db.commit()
    db.close()
    return "pat-1"


def test_draft_from_pattern_is_valid_and_not_saved(env: SimpleNamespace) -> None:
    pid = _seed_pattern(env)
    resp = env.client.post("/rules/draft", json={"pattern_id": pid})
    assert resp.status_code == 200, resp.text
    rule = resp.json()["rule"]
    assert rule["match"] == {"tool": "refund_api", "args": [{"field": "amount", "op": ">", "value": 300}]}
    assert rule["reason"] == "Refunds above the limit fail"
    assert env.client.get("/rules", params={"agent_id": AGENT}).json()["rules"] == []  # nothing saved
    assert env.client.post("/rules", json=rule).status_code == 201  # and it can be created as-is


def test_draft_unknown_pattern_404(env: SimpleNamespace) -> None:
    assert env.client.post("/rules/draft", json={"pattern_id": "nope"}).status_code == 404


def test_draft_for_another_orgs_agent_404(env: SimpleNamespace) -> None:
    pid = _seed_pattern(env)
    env.org = SimpleNamespace(id="org-2")
    assert env.client.post("/rules/draft", json={"pattern_id": pid}).status_code == 404


def test_suggestions_are_merged_cited_and_skip_existing_rules(env: SimpleNamespace) -> None:
    from datetime import datetime, timezone
    from db.models import LossPattern
    _seed_pattern(env)
    db = env.session()
    now = datetime.now(timezone.utc)
    # a second pattern over the same failing sessions drafts the same rule -> merged
    db.add(LossPattern(id="pat-2", agent_id=AGENT, pattern_type="workflow_step", pattern_value="refund",
                       failure_count=2, total_count=4, failure_rate=0.5, pct_of_all_failures=1.0,
                       root_cause="Refunds above the limit fail", first_seen=now, last_seen=now))
    db.commit()
    db.close()
    resp = env.client.get("/rules/suggestions", params={"agent_id": AGENT})
    assert resp.status_code == 200, resp.text
    sugg = resp.json()["suggestions"]
    assert len(sugg) == 1
    s0 = sugg[0]
    assert s0["rule"]["match"]["args"] == [{"field": "amount", "op": ">", "value": 300}]
    assert s0["coverage"] == {"failing_matched": 2, "failing_total": 2, "passing_matched": 0, "passing_total": 2}
    assert len(s0["patterns"]) == 1 or {p["pattern_id"] for p in s0["patterns"]} == {"pat-1", "pat-2"}

    by_pattern = resp.json()["by_pattern"]
    assert by_pattern["pat-1"]["status"] == "suggested"
    assert by_pattern["pat-1"]["coverage"]["failing_matched"] == 2

    assert env.client.post("/rules", json=s0["rule"]).status_code == 201
    after = env.client.get("/rules/suggestions", params={"agent_id": AGENT}).json()
    assert after["suggestions"] == []
    assert after["by_pattern"]["pat-1"]["status"] == "exists"
    assert after["by_pattern"]["pat-1"]["rule_id"] == s0["rule"]["id"]


def test_suggestions_explain_patterns_without_a_rule(env: SimpleNamespace) -> None:
    from datetime import datetime, timezone
    from db.models import AgentLog, LossPattern
    _seed_pattern(env)
    db = env.session()
    now = datetime.now(timezone.utc)
    # failures with no tool calls at all -> nothing to draft from
    for i in range(2):
        db.add(AgentLog(id=f"nt{i}", agent_id=AGENT, session_id=f"nt{i}", step_number=1, step_name="chat",
                        input="", output=""))
        db.add(EvalResult(log_id=f"nt{i}", session_id=f"nt{i}", agent_id=AGENT, accuracy=0.5, goal_alignment=0.5,
                          decision_quality=0.5, completeness=0.5, overall_score=0.5, passed=False,
                          failure_type="goal_drift", failure_step="chat"))
    db.add(LossPattern(id="pat-drift", agent_id=AGENT, pattern_type="failure_type", pattern_value="goal_drift",
                       failure_count=2, total_count=6, failure_rate=0.33, pct_of_all_failures=0.5,
                       root_cause="Wandered off topic", first_seen=now, last_seen=now))
    db.commit()
    db.close()
    by_pattern = env.client.get("/rules/suggestions", params={"agent_id": AGENT}).json()["by_pattern"]
    assert by_pattern["pat-drift"]["status"] == "none"
    assert "tool_calls" in by_pattern["pat-drift"]["reason"]
    assert by_pattern["pat-1"]["status"] == "suggested"


def test_suggestions_for_another_orgs_agent_404(env: SimpleNamespace) -> None:
    _seed_pattern(env)
    env.org = SimpleNamespace(id="org-2")
    assert env.client.get("/rules/suggestions", params={"agent_id": AGENT}).status_code == 404


def test_rule_history_lists_every_change(env: SimpleNamespace) -> None:  # noqa: F811
    from kalytera.dashboard_rules import describe_versions

    _create(env)
    env.client.post("/rules/refund_cap/promote", params={"agent_id": AGENT})
    env.client.put("/rules/refund_cap", json={**REFUND_CAP, "match": {"tool": "refund_api", "args": [
        {"field": "amount", "op": ">", "value": 800}]}})
    env.client.post("/rules/refund_cap/demote", params={"agent_id": AGENT})
    versions = env.client.get("/rules/refund_cap", params={"agent_id": AGENT}).json()["versions"]
    assert [v["rule"]["match"]["args"][0]["value"] for v in versions] == [800, 800, 500, 500]
    what = [w for _, w in describe_versions(versions)]
    assert what[0] == "Created — watching" and what[1] == "Started blocking"
    assert what[2].startswith("Edited: ") and "800" in what[2]
    assert what[3] == "Stopped blocking (watching again)"
