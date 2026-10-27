"""check_reply(): a reply that says something was done when it wasn't never reaches the customer."""
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from test_guard import env  # noqa: F401  (fixture: in-memory DB, SDK HTTP routed to the API)

import api.connections_api as conn_api
import api.replies_api as replies_api
import kalytera
import kalytera.judge as judge
from db.models import HeldReply
from kalytera import replies, tracer, vault


@pytest.fixture()
def rx(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:  # noqa: F811
    monkeypatch.setenv(vault.ENV, Fernet.generate_key().decode())
    env.org = SimpleNamespace(id="org-1", name="Acme", tier="free")
    env.slack: List[Dict[str, Any]] = []

    class _Ok:
        status_code, text = 200, "ok"

    def fake_post(url: str, json: Dict[str, Any], timeout: int) -> Any:
        env.slack.append(json)
        return _Ok()

    with patch.object(replies, "_in_background", lambda fn: fn()), patch.object(conn_api.requests, "post", fake_post), \
         patch.object(tracer, "trace", lambda *a, **k: None):  # the conversation itself isn't what's tested
        env.client.put("/alerts/slack", json={"webhook_url": "https://hooks.slack.com/services/T/B/x"})
        yield env


def _held(rx: SimpleNamespace) -> List[HeldReply]:
    db = rx.session()
    try:
        return db.query(HeldReply).all()
    finally:
        db.close()


def test_a_false_done_is_held_and_slack_hears_now(rx: SimpleNamespace) -> None:
    @kalytera.tool(on_block=lambda d: "blocked")
    def refund_api(order_id: str, amount: float) -> str:
        raise RuntimeError("payment provider down")

    with kalytera.session("conv-1", input="Refund order A1 please") as s:
        try:
            refund_api("A1", 40)
        except RuntimeError:
            pass
        kalytera.flush_guard()  # the test database is one connection: let the rule check's report finish first
        check = kalytera.check_reply("All set! Your refund of $40 has been processed.")
        s.output = check.reply
    assert check.held and check.checked_by == "code"
    assert check.reply == replies.SAFE_REPLY
    assert check.original == "All set! Your refund of $40 has been processed."
    assert check.reason == 'The reply says "Your refund of $40 has been processed.", but refund_api failed.'
    rows = _held(rx)
    assert len(rows) == 1, kalytera.tracer._notified
    [row] = rows
    assert (row.agent_id, row.session_id, row.checked_by, row.org_id) == (kalytera.tracer._agent_id, "conv-1",
                                                                         "code", "org-1")
    alert = rx.slack[-1]
    assert "stopped a reply" in alert["text"] and check.reason in alert["text"]
    assert alert["blocks"][1]["accessory"]["url"].endswith("&session=conv-1")


def test_a_true_done_goes_out_unchanged(rx: SimpleNamespace) -> None:
    @kalytera.tool
    def refund_api(order_id: str, amount: float) -> str:
        return "refund r_1 ok"

    with kalytera.session("conv-2", input="Refund order A1") as s:
        refund_api("A1", 40)
        kalytera.flush_guard()
        check = kalytera.check_reply("Your refund of $40 has been processed.", safe_reply="One moment…")
        s.output = check.reply
    assert not check.held and check.reply == "Your refund of $40 has been processed."
    assert _held(rx) == []


def test_without_tracked_actions_a_claim_is_not_guessed_at(rx: SimpleNamespace) -> None:
    check = kalytera.check_reply("Your refund has been processed.")  # no session, no actions given
    assert not check.held


def test_the_ai_reviewer_holds_an_invented_promise(rx: SimpleNamespace) -> None:
    seen: List[str] = []

    def fake_judge(messages: List[Dict[str, str]], system: Any = None) -> str:
        seen.append(messages[0]["content"])
        return '{"hold": true, "reason": "Promises a bereavement refund the policy does not offer."}'

    with patch.object(judge, "_call_judge", fake_judge):
        check = kalytera.check_reply("You can claim a bereavement refund within 90 days.", review=True,
                                     message="My grandmother died, can I get a discount?",
                                     policy="Bereavement fares must be requested before travel.",
                                     actions=[], session_id="conv-3")
    assert check.held and check.checked_by == "ai"
    assert check.reason == "Promises a bereavement refund the policy does not offer."
    assert "Bereavement fares must be requested before travel." in seen[0]
    assert [r.checked_by for r in _held(rx)] == ["ai"]
    assert "AI reviewer" in rx.slack[-1]["blocks"][1]["text"]["text"]


def test_the_ai_reviewer_only_reads_high_stakes_replies(rx: SimpleNamespace) -> None:
    calls: List[Any] = []
    with patch.object(judge, "_call_judge", lambda m, system=None: calls.append(m) or '{"hold": false}'):
        assert not kalytera.check_reply("Your package arrives Monday.", review=True, actions=[]).held
        assert calls == []
        assert not kalytera.check_reply("Your package arrives Monday.", review="always", actions=[]).held
        assert len(calls) == 1
        assert not kalytera.check_reply("The fee is $25.", review=True, actions=[]).held
        assert len(calls) == 2


def test_if_the_reviewer_is_unavailable_the_reply_still_goes_out(rx: SimpleNamespace) -> None:
    with patch.object(judge, "_call_judge", lambda m, system=None: "not json"):
        check = kalytera.check_reply("Refunds take $10 off.", review=True, actions=[])
    assert not check.held and check.reply == "Refunds take $10 off." and "unavailable" in check.error
    rx.api_up = False
    check = kalytera.check_reply("Refunds take $10 off.", review=True, actions=[])
    assert not check.held and check.error


def test_another_accounts_agent_cant_be_written_to(rx: SimpleNamespace) -> None:
    rx.client.post("/trace", json={"id": "t1", "agent_id": "their-bot", "session_id": "s", "step_number": 1,
                                   "step_name": "a", "input": "", "output": "",
                                   "timestamp": "2026-10-01T00:00:00+00:00"})
    rx.org = SimpleNamespace(id="org-2", name="Other", tier="free")
    r = rx.client.post("/replies/held", json={"agent_id": "their-bot", "reply": "x", "reason": "y"})
    assert r.status_code == 404


def test_reviews_are_capped_per_account_per_day(rx: SimpleNamespace) -> None:
    with patch.object(replies_api, "REVIEW_DAILY_LIMIT", 1), patch.dict(replies_api._reviews_today, clear=True), \
         patch.object(judge, "_call_judge", lambda m, system=None: '{"hold": false}'):
        body = {"agent_id": "bot", "reply": "The fee is $25."}
        assert rx.client.post("/replies/review", json=body).status_code == 200
        assert rx.client.post("/replies/review", json=body).status_code == 429


def test_verdicts_are_read_strictly() -> None:
    assert replies_api.parse_verdict('{"hold": true, "reason": "x"}') == {"hold": True, "reason": "x"}
    assert replies_api.parse_verdict('```json\n{"hold": false, "reason": "x"}\n```') == {"hold": False, "reason": ""}
    assert replies_api.parse_verdict('{"hold": "yes"}') is None
    assert replies_api.parse_verdict("") is None
