"""Connect once: Langfuse/LangSmith conversations are pulled, judged, kept in sync; Slack hears about problems."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from test_guard import env  # noqa: F401
from test_quickstart import _fake_score_session, _start_and_wait

import api.connections_api as conn_api
import api.refresh_api as refresh_api
import kalytera.judge as judge
from db.models import AgentLog, Connection, LossPattern, ProblemAlert
from kalytera import vault


def _conv(i: int, failed: bool) -> Dict[str, Any]:
    action = {"name": "refund_api", "input": {"amount": 900 if failed else 40}, "success": not failed,
              "error": "over limit" if failed else None}
    return {"id": f"tr{i}", "started_at": "2026-10-01T10:00:00+00:00",
            "turns": [{"user": f"Refund order {i}", "assistant": "Your refund was issued.", "actions": [action]}]}


@pytest.fixture()
def cx(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:  # noqa: F811
    monkeypatch.setenv(vault.ENV, Fernet.generate_key().decode())
    env.org = SimpleNamespace(id="org-1", name="Acme", tier="free")
    env.pulls: List[Dict[str, Any]] = []
    env.convs = [_conv(i, failed=i < 5) for i in range(7)]  # 5 failing refunds, 2 fine
    env.slack: List[Dict[str, Any]] = []

    def fake_fetch(kind: str, settings: Dict[str, str], secrets: Dict[str, str],
                   since: Optional[datetime]) -> List[Dict[str, Any]]:
        env.pulls.append({"kind": kind, "settings": settings, "secrets": secrets, "since": since})
        if secrets.get("secret_key") == "wrong":
            raise ValueError("Langfuse rejected these keys.")
        return list(env.convs)

    class _Ok:
        status_code, text = 200, "ok"

    def fake_post(url: str, json: Dict[str, Any], timeout: int) -> Any:
        env.slack.append({"url": url, **json})
        return _Ok()

    with patch.object(refresh_api, "SessionLocal", env.session), \
         patch.object(judge, "score_session", _fake_score_session), \
         patch.object(refresh_api, "SCORING_THREADS", 1), \
         patch.object(refresh_api, "_start", _start_and_wait), \
         patch.object(conn_api, "_fetch", fake_fetch), \
         patch.object(conn_api.requests, "post", fake_post):
        yield env


LANGFUSE = {"kind": "langfuse", "agent_name": "Support bot",
            "settings": {"base_url": "https://cloud.langfuse.com"},
            "secrets": {"public_key": "pk-lf-1", "secret_key": "sk-lf-2"}}


def _connect(cx: SimpleNamespace, body: Dict[str, Any] = LANGFUSE) -> Dict[str, Any]:
    r = cx.client.post("/connections", json=body)
    assert r.status_code == 202, r.text
    return r.json()


def test_connect_pulls_judges_and_finds_problems_without_code(cx: SimpleNamespace) -> None:
    agent = _connect(cx)["agent_id"]
    assert agent == "support-bot-org1"
    status = cx.client.get(f"/agents/{agent}/refresh").json()
    assert status["state"] == "done" and (status["sessions_scored"], status["sessions_failed"]) == (7, 5)
    assert status["patterns"] >= 1  # 5 alike failures make a problem
    assert cx.pulls[0]["since"] is None  # first pull: the last 30 days
    conns = cx.client.get("/connections").json()["connections"]
    assert [(c["kind"], c["agent_id"], c["status"]) for c in conns] == [("langfuse", agent, "ok")]
    assert "secrets" not in conns[0] and "sk-lf-2" not in str(conns[0])
    db = cx.session()
    stored = db.query(Connection).one()
    assert "sk-lf-2" not in stored.secret  # encrypted at rest
    assert vault.decrypt(stored.secret) == {"public_key": "pk-lf-1", "secret_key": "sk-lf-2"}
    db.close()


def test_bad_keys_say_why_and_save_nothing(cx: SimpleNamespace) -> None:
    bad = {**LANGFUSE, "secrets": {"public_key": "pk", "secret_key": "wrong"}}
    agent = _connect(cx, bad)["agent_id"]
    status = cx.client.get(f"/agents/{agent}/refresh").json()
    assert status["state"] == "error" and "rejected these keys" in status["error"]
    assert cx.client.get("/connections").json()["connections"] == []


def test_sync_pulls_only_whats_new(cx: SimpleNamespace) -> None:
    _connect(cx)
    cx.convs += [_conv(7, failed=False), _conv(8, failed=True)]
    db = cx.session()
    assert conn_api.sync_all(db) == {db.query(Connection).one().id: 2}
    since = cx.pulls[-1]["since"]
    assert since is not None and datetime.now(timezone.utc) - since < timedelta(minutes=31)  # overlap, not 30 days
    assert db.query(AgentLog.session_id).distinct().count() == 9  # no duplicates
    db.close()


def test_a_failing_connection_is_marked_and_doesnt_stop_others(cx: SimpleNamespace) -> None:
    _connect(cx)
    db = cx.session()
    conn = db.query(Connection).one()
    conn.secret = vault.encrypt({"public_key": "pk", "secret_key": "wrong"})  # keys rotated in Langfuse
    db.commit()
    assert conn_api.sync_all(db) == {}
    db.refresh(conn)
    assert conn.status == "error" and "rejected" in conn.last_error
    db.close()


def test_without_an_encryption_key_connecting_is_refused_cleanly(cx: SimpleNamespace,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(vault.ENV)
    r = cx.client.post("/connections", json=LANGFUSE)
    assert r.status_code == 503 and "can't store keys safely" in r.json()["detail"]


def test_remove_deletes_the_keys_and_other_accounts_cant_touch_it(cx: SimpleNamespace) -> None:
    _connect(cx)
    cid = cx.client.get("/connections").json()["connections"][0]["id"]
    cx.org = SimpleNamespace(id="org-2", name="Other", tier="free")
    assert cx.client.get("/connections").json()["connections"] == []
    assert cx.client.post(f"/connections/{cid}/sync").status_code == 404
    assert cx.client.delete(f"/connections/{cid}").status_code == 404
    assert cx.client.post("/connections", json=LANGFUSE).json()["agent_id"] == "support-bot-org2"  # own name
    cx.org = SimpleNamespace(id="org-1", name="Acme", tier="free")
    assert cx.client.delete(f"/connections/{cid}").status_code == 200
    db = cx.session()
    assert db.query(Connection).filter(Connection.org_id == "org-1").count() == 0
    db.close()


def test_kind_must_be_supported(cx: SimpleNamespace) -> None:
    assert cx.client.post("/connections", json={**LANGFUSE, "kind": "datadog"}).status_code == 422


def test_slack_hears_about_new_problems_once(cx: SimpleNamespace) -> None:
    assert cx.client.put("/alerts/slack", json={"webhook_url": "https://example.com/x"}).status_code == 422
    url = "https://hooks.slack.com/services/T/B/x"
    assert cx.client.put("/alerts/slack", json={"webhook_url": url}).json() == {"slack": True}
    assert cx.slack[-1]["text"].startswith("Kalytera is connected")
    assert cx.client.get("/alerts").json()["slack"] is True

    agent = _connect(cx)["agent_id"]  # the first pull finds a problem → Slack hears now, not in an hour
    news = [m for m in cx.slack if "new problem" in m["text"]]
    assert len(news) == 1 and news[0]["url"] == url
    button = news[0]["blocks"][1]["accessory"]
    db = cx.session()
    pattern = db.query(LossPattern).filter(LossPattern.agent_id == agent).first()
    assert button["url"] == f"https://app.kalytera.dev/?agent={agent}&problem={pattern.id}"
    assert conn_api.send_alerts(db) == 0  # already told

    pattern.is_worsening = True
    db.commit()
    assert conn_api.send_alerts(db) == 0  # just announced as new: no "getting worse" the same day
    day2 = datetime.now(timezone.utc) + timedelta(days=1, minutes=1)
    assert conn_api.send_alerts(db, now=day2) == 1
    assert "getting worse" in cx.slack[-1]["blocks"][1]["text"]["text"].lower()
    assert conn_api.send_alerts(db, now=day2 + timedelta(hours=5)) == 0  # at most once a day
    assert conn_api.send_alerts(db, now=day2 + timedelta(days=1, minutes=1)) == 1
    db.close()


def test_turning_on_slack_doesnt_replay_old_problems(cx: SimpleNamespace) -> None:
    _connect(cx)  # problems exist before Slack is set up
    cx.client.put("/alerts/slack", json={"webhook_url": "https://hooks.slack.com/services/T/B/x"})
    db = cx.session()
    assert conn_api.send_alerts(db) == 0
    assert db.query(ProblemAlert).count() >= 1
    db.close()
    assert cx.client.delete("/alerts/slack").json() == {"slack": False}
