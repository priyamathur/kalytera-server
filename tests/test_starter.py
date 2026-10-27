"""Starter rules: risky actions get 'a person approves it first' before anything has gone wrong."""
from types import SimpleNamespace

from test_guard import env  # noqa: F401  (fixture: in-memory DB, SDK HTTP routed to the API)

from kalytera.starter import kind_of, nice_limit, starter_rules


def test_risky_actions_are_recognised_by_name() -> None:
    assert kind_of("refund_api") == "money"
    assert kind_of("issueRefund") == "money"
    assert kind_of("transfer-funds") == "money"
    assert kind_of("delete_user") == "delete"
    assert kind_of("purgeDatabase") == "delete"
    assert kind_of("reset_password") == "account"
    assert kind_of("update_account_email") == "account"
    assert kind_of("grant_admin_role") == "account"
    for harmless in ("lookup_order", "get_refund_status", "search_docs", "list_payments", "send_reply",
                     "track_order", "check_balance"):
        assert kind_of(harmless) is None, harmless


def test_money_limits_let_everyday_amounts_through() -> None:
    assert nice_limit([20, 35, 40, 60, 80, 90, 110, 120, 140, 900]) == 200
    assert nice_limit([5000]) == 5000
    assert nice_limit([]) == 500
    rules = starter_rules("bot", [("refund_api", {"order_id": "A1", "amount": a}) for a in (20, 40, 60, 90)]
                          + [("delete_user", {"user_id": "u1"}), ("lookup_order", {"order_id": "A1"})])
    assert [r["rule"]["match"]["tool"] for r in rules] == ["delete_user", "refund_api"]  # most dangerous first
    delete, refund = rules
    assert refund["rule"]["match"]["args"] == [{"field": "amount", "op": ">", "value": 100}]
    assert refund["rule"]["action"] == "ESCALATE" and refund["calls"] == 4
    assert refund["rule"]["reason"] == "refund_api over 100 needs a person to approve it, because it moves money."
    assert delete["rule"]["match"]["args"] == []  # every deletion


def test_starter_rules_from_the_agents_actions(env: SimpleNamespace) -> None:  # noqa: F811
    env.org = SimpleNamespace(id="org-1", name="Acme", tier="free")
    step = {"agent_id": "bot", "session_id": "s1", "step_number": 1, "step_name": "a", "input": "",
            "output": "", "timestamp": "2026-10-01T00:00:00+00:00",
            "tool_calls": [{"name": "refund_api", "input": {"amount": 40}, "success": True},
                           {"name": "close_account", "input": {"user": "u1"}, "success": True}]}
    assert env.client.post("/trace", json={**step, "id": "t1"}).status_code == 201
    got = env.client.get("/rules/starter", params={"agent_id": "bot"}).json()["starter"]
    assert [g["rule"]["match"]["tool"] for g in got] == ["refund_api", "close_account"]  # money, then accounts

    created = env.client.post("/rules", json=got[1]["rule"])
    assert created.status_code == 201 and created.json()["mode"] == "shadow"  # watches until you say so
    got = env.client.get("/rules/starter", params={"agent_id": "bot"}).json()["starter"]
    assert [g["rule"]["match"]["tool"] for g in got] == ["refund_api"]  # not suggested twice

    env.org = SimpleNamespace(id="org-2", name="Other", tier="free")
    assert env.client.get("/rules/starter", params={"agent_id": "bot"}).status_code == 404


def test_commands_that_wipe_things_need_a_person() -> None:
    """The PocketOS database (9 seconds), a whole drive, a home folder: all one destructive command away."""
    from kalytera.rules import evaluate, parse_rule

    got = starter_rules("bot", [("run_command", {"command": "ls", "cwd": "/app"}),
                                ("execute_sql", {"query": "select 1"})])
    rules = {g["rule"]["match"]["tool"]: parse_rule({**g["rule"], "mode": "enforce"}) for g in got}
    assert [g["kind"] for g in got] == ["command", "command"]
    run, sql = [rules["run_command"]], [rules["execute_sql"]]
    assert evaluate(run, "run_command", {"command": "rm  -RF ~/"}).decision == "ESCALATE"
    assert evaluate(run, "run_command", {"command": "cd /srv && rm -rf data"}).decision == "ESCALATE"
    assert evaluate(run, "run_command", {"command": "git status"}).decision == "ALLOW"
    assert evaluate(sql, "execute_sql", {"query": "DROP TABLE customers;"}).decision == "ESCALATE"
    assert evaluate(sql, "execute_sql", {"query": "select * from orders"}).decision == "ALLOW"


def test_turning_off_monitoring_or_security_needs_a_person() -> None:
    for name in ("disable_monitoring", "update_alert_settings", "delete_backup", "turnOffAuditLog"):
        assert kind_of(name) == "safety", name
    assert kind_of("get_logs") is None
    [rule] = starter_rules("bot", [("disable_monitoring", {"service": "api"})])
    assert rule["rule"]["match"]["args"] == [] and rule["rule"]["action"] == "ESCALATE"
