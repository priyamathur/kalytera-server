"""
End-to-end check of the dashboard against the real API and a real database.

    python tests/system/dashboard_e2e.py

Signs up, sends traces through POST /trace, scores them (stand-in for the LLM
judge), runs the real pattern analyzer, then drives the Streamlit dashboard the
way a user would: Failure Feed → See sessions → open a trace → back → Make it a
rule → Rules page → session search → Overview. HTTP calls from the dashboard
are routed to the API in-process, so nothing listens on a port.

Run by tests/test_dashboard_e2e.py; needs the dashboard dependencies
(requirements.txt), which is why it runs as its own process.
"""
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="kalytera-e2e-")
os.environ["DATABASE_URL"] = f"sqlite:///{TMP}/e2e.db"
os.environ["KALYTERA_API_ENDPOINT"] = "http://kalytera.test"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import requests  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

from api.main import app  # noqa: E402

AGENT = "support-bot"
client = TestClient(app)
_real_request = requests.api.request


class _Resp:
    def __init__(self, r: object) -> None:
        self.status_code = r.status_code
        self.text = r.text
        self._r = r

    def json(self) -> object:
        return self._r.json()


def _route(method: str, url: str, **kw: object) -> object:
    if not url.startswith("http://kalytera.test"):
        return _real_request(method, url, **kw)
    path = url[len("http://kalytera.test"):]
    kw.pop("timeout", None)
    return _Resp(client.request(method.upper(), path, json=kw.get("json"), params=kw.get("params"),
                                headers=kw.get("headers")))


requests.api.request = _route
requests.request = _route
requests.get = lambda url, **kw: _route("GET", url, **kw)
requests.post = lambda url, **kw: _route("POST", url, **kw)


def check(cond: bool, what: str) -> None:
    print(("  ✓ " if cond else "  ✗ ") + what)
    if not cond:
        raise SystemExit(f"FAILED: {what}")


def texts(at: AppTest) -> str:
    out = []
    for kind in ("markdown", "success", "error", "warning", "info", "caption"):
        out += [str(getattr(e, "value", "")) for e in getattr(at, kind)]
    return "\n".join(out)


def button(at: AppTest, label: str) -> object:
    for b in at.button:
        if b.label == label:
            return b
    raise SystemExit(f"FAILED: no button {label!r}; have {[b.label for b in at.button]}")


def run(target: object) -> AppTest:
    """Run the app (target: the AppTest, or a widget just clicked / typed into)."""
    at = target.run()
    if at.exception:
        raise SystemExit(f"FAILED: dashboard raised {at.exception}")
    return at


# ── 1. Sign up and send traces ───────────────────────────────────────────────
print("1. Sign up, send traces through the API")
r = client.post("/signup", json={"email": f"e2e-{uuid.uuid4().hex[:6]}@example.com", "name": AGENT})
check(r.status_code in (200, 201), f"signup works (HTTP {r.status_code})")
KEY = r.json()["api_key"]
H = {"Authorization": f"Bearer {KEY}"}


def trace(sid: str, n: int, step: str, tool_calls: list, ended: bool = False) -> str:
    tid = str(uuid.uuid4())
    resp = client.post("/trace", headers=H, json={
        "id": tid, "agent_id": AGENT, "session_id": sid, "step_number": n, "step_name": step,
        "input": f"{step} input", "output": f"{step} output", "tool_calls": tool_calls,
        "session_ended": ended, "timestamp": datetime.now(timezone.utc).isoformat()})
    assert resp.status_code == 201, resp.text
    return tid


scores = []  # (log_id, session_id, passed, failure_type, step, reason)
for i in range(30):
    sid, big = f"sess-{i:02d}", i % 3 == 0
    amount = 900 + i * 10 if big else 50 + i * 10
    trace(sid, 1, "lookup_order", [{"name": "lookup_order", "input": {"order_id": f"o{i}"}, "success": True}])
    tid = trace(sid, 2, "issue_refund", [{"name": "refund_api", "input": {"amount": amount},
                                          "success": not big}], ended=True)
    scores.append((tid, sid, not big, "tool_failure", "issue_refund", "refund_api rejected the refund amount"))
for i in range(8):
    sid, loops = f"loop-{i}", i < 5
    calls = [{"name": "lookup_order", "input": {"order_id": f"L{i}"}, "success": True}] * (6 if loops else 2)
    tid = trace(sid, 1, "find_order", calls, ended=True)
    scores.append((tid, sid, not loops, "loop", "find_order", "Agent kept looking up the same order"))
check(AGENT in client.get("/agents", headers=H).json(), "agent appears for this key")

# ── 2. Score (stand-in for the judge) and detect patterns ────────────────────
print("2. Score sessions and run the real pattern analyzer")
from api.database import SessionLocal  # noqa: E402
from db.models import EvalResult  # noqa: E402
from kalytera.analyzer import run_analysis  # noqa: E402

db = SessionLocal()
for tid, sid, passed, ftype, step, reason in scores:
    db.add(EvalResult(log_id=tid, session_id=sid, agent_id=AGENT, accuracy=0.8, goal_alignment=0.8,
                      decision_quality=0.8, completeness=0.8, overall_score=0.85 if passed else 0.35,
                      passed=passed, failure_type=None if passed else ftype,
                      failure_step=None if passed else step, failure_reason=None if passed else reason))
db.commit()
check(run_analysis(AGENT, db) >= 2, "analyzer found the refund and loop patterns")
db.close()


def dashboard(view: str) -> AppTest:
    at = AppTest.from_file("kalytera/dashboard.py", default_timeout=60)
    at.session_state["authenticated"] = True
    at.session_state["api_key"] = KEY
    at.session_state["view"] = view
    return run(at)


# ── 3. Login ─────────────────────────────────────────────────────────────────
print("3. Log in with the API key")
at = AppTest.from_file("kalytera/dashboard.py", default_timeout=60)
run(at)
at.text_input[0].input(KEY)
run(at.button[0].click())
check(at.session_state["authenticated"] is True, "key accepted")
check(list(at.radio[0].options) == ["🔴  Failure Feed", "📊  Overview", "🛡  Rules"],
      "sidebar: Failure Feed first, then Overview, Rules (no Trace Viewer tab)")
check(at.radio[0].value == "🔴  Failure Feed", "lands on the Failure Feed: what needs fixing")
check(any(t.placeholder.startswith("🔍  Search sessions") for t in at.text_input), "search box at the top")

# ── 4. Failure Feed ──────────────────────────────────────────────────────────
print("4. Failure Feed reads in sessions, with a ready rule")
at = dashboard("🔴  Failure Feed")
t = texts(at)
check("2 problems keep happening</b> — 15 of 38 sessions failed (39%)" in t, "headline: 2 problems, 15 of 38 sessions (39%)")
check('<div class="n">10</div><div class="l">sessions · 26%</div>' in t, "refund problem: 10 sessions · 26%")
check('<div class="n">5</div><div class="l">sessions · 13%</div>' in t, "loop problem: 5 sessions · 13%")
check('<span class="ff-chip">tool failure</span>' in t and '<span class="ff-chip">at issue_refund</span>' in t,
      "type and step shown as chips")
check("Suggested rule</span>Block <code>refund_api</code> when amount is more than" in t, "refund rule is suggested")
check("Would have caught 10 of 10 failed sessions · touches 0 of 23 good ones" in t,
      "citation: caught 10 of 10 failed sessions, 0 of 23 good")
check("Suggested rule</span>Flag <code>lookup_order</code> when it's the 3rd call or more" in t, "loop rule is suggested")
check(sum(b.label == "⚡ Make it a rule" and b.proto.type == "primary" for b in at.button) == 2,
      "one highlighted next step per card")

print("5. See sessions → open a trace → back")
run(button(at, "▸ 10 sessions").click())
opens = [b for b in at.button if b.key and b.key.startswith("ps_")]
check(len(opens) == 10, "10 sessions listed inline, under the card")
check('<span class="ff-mono">sess-27</span>' in texts(at), "newest failed session (sess-27) is listed")
run(opens[0].click())
check("Session trace" in texts(at), "trace opens in place")
check("lookup_order" in texts(at) and "issue_refund" in texts(at), "trace shows the session's steps")
run(button(at, "← Back to Failure Feed").click())
check("problems keep happening" in texts(at), "back on the Failure Feed")

print("6. Make it a rule (one click)")
make = [b for b in at.button if b.label == "⚡ Make it a rule"]
check(len(make) == 2, "both problems offer '⚡ Make it a rule'")
run(make[0].click())
check('ff-pill watch">Watching</span>Block <code>refund_api</code>' in texts(at), "card now shows the rule as Watching")
rules = client.get("/rules", params={"agent_id": AGENT}, headers=H).json()["rules"]
check(len(rules) == 1 and rules[0]["mode"] == "shadow", "rule saved in watch (shadow) mode")
check(rules[0]["match"]["tool"] == "refund_api", "it's the refund rule")
check((rules[0].get("source") or {}).get("pattern_value") is not None, "the rule remembers the problem it came from")
LOOP_RULE_ID = rules[0]["id"]
at = dashboard("🔴  Failure Feed")
check('Watching</span>Block <code>refund_api</code>' in texts(at)
      and any(b.label == "Start blocking" for b in at.button), "after reload the card shows the rule, ready to block")
check(not any(b.label == "▶ Test it" for b in at.button), "no separate test step")
check(len([b for b in at.button if b.label == "⚡ Make it a rule"]) == 1, "only the loop rule is still offered")

print("7. Rules page")
at = dashboard("🛡  Rules")
t = texts(at)
check("Watching" in t and "refund_api" in t, "the new rule is listed as Watching")
check("Flag <code>lookup_order</code>" in t, "the loop rule is still suggested there")
check(t.count("Block <code>refund_api</code>") == 1, "the added rule isn't suggested again")

print("8. Search sessions (top right)")
at = dashboard("📊  Overview")
search = next(x for x in at.text_input if x.key == "session_search")
run(search.input("loop-3"))
check("Session trace" in texts(at) and "find_order" in texts(at), "exact ID opens the trace directly")
run(button(at, "← Back to Overview").click())
check("Agent Overview" in texts(at), "back to Overview")
search = next(x for x in at.text_input if x.key == "session_search")
run(search.input("loop"))
check("8 sessions</b>" in texts(at) or "**8 sessions**" in texts(at), "partial ID lists all 8 loop sessions")
run(button(at, "Close").click())
search = next(x for x in at.text_input if x.key == "session_search")
run(search.input("same order"))
check("**5 sessions**" in texts(at), "error text finds the 5 looping sessions")
run([b for b in at.button if b.key and b.key.startswith("sr_")][0].click())
check("Session trace" in texts(at), "opening a result shows its trace")
search = next(x for x in at.text_input if x.key == "session_search")
run(search.input("no-such-session"))
check("No sessions match" in texts(at), "no match says so")

print("9. Overview counts sessions")
at = dashboard("📊  Overview")
t = texts(at)
check("FAILED SESSIONS" in t.upper() and ">15<" in t, "15 failed sessions (10 refund + 5 loop)")
check("39% of sessions" in t, "shown as 39% of 38 sessions")

print("10. An old bookmark to the Trace Viewer tab doesn't break")
at = dashboard("🔍  Trace Viewer")
check(at.radio[0].value == "🔴  Failure Feed", "falls back to the Failure Feed")

print("10b. Blocks are counted and can be marked wrong (Rules page)")
assert client.post(f"/rules/{LOOP_RULE_ID}/promote", params={"agent_id": AGENT}, headers=H).status_code == 200
for i in (3, 6):  # the agent hits the rule twice in real sessions
    r = client.post("/guard", headers=H, json={"agent_id": AGENT, "tool": "refund_api", "args": {"amount": 2000},
                                               "session_id": f"sess-{i:02d}"})
    assert r.json()["decision"] == "DENY", r.text
import streamlit as _st  # noqa: E402
_st.cache_data.clear()  # promoted through the API, not the dashboard: what a refresh after 30s would show
at = dashboard("🛡  Rules")
t = texts(at)
check("Blocked 2 calls so far" in t, "the rule card counts 2 blocked calls")
check("too early to compare" in t, "honest: too early to compare before/after")
check(any("Review blocks — 0 marked wrong, 2 not reviewed" in e.label for e in at.expander), "blocks can be reviewed")
wrong = [b for b in at.button if b.label == "✗ Wrong"]
check(len(wrong) == 2, "both blocks listed")
run(wrong[0].click())
rep = client.get(f"/agents/{AGENT}/impact", headers=H).json()
check(rep["rules"][0]["marked_wrong"] == 1, "marking one wrong is saved")
check("marked wrong" in texts(at), "and shows next to the block")
at = dashboard("📊  Overview")
check("Agent Overview" in texts(at), "Overview still renders with blocking dates on the trend")
retention = next(x for x in at.selectbox if x.key == "retention_choice")
check(retention.value == "Until I delete it", "retention defaults to keeping data")
run(retention.select("90 days"))
check(client.get("/account/retention", headers=H).json()["retention_days"] == 90, "choosing 90 days is saved")
delete = next(b for b in at.button if b.label == "Delete all data")
check(delete.disabled, "deleting needs the agent's name typed first")

at = dashboard("🛡  Rules")
run(next(b for b in at.button if b.label == "History").click())
check("Started blocking" in texts(at) and "Created — watching" in texts(at), "rule history shows each change")

print("10c. A person's verdict replaces the judge's")
at = dashboard("🔴  Failure Feed")
check("15 of 38 sessions failed" in texts(at), "before: 15 of 38 sessions failed")
at.session_state["open_session"] = "sess-27"
run(at)
run(button(at, "👍 Not a failure").click())
check("You marked: passed" in texts(at), "the trace shows the verdict")
at = dashboard("🔴  Failure Feed")
check("14 of 38 sessions failed" in texts(at), "after: 14 of 38 — the feed follows the person's verdict")
labels = [b.label for b in at.button]
check("▸ 9 sessions" in labels, f"and the refund problem now has 9 sessions, regrouped at once ({[l for l in labels if 'sessions' in l]})")

print("10d. Billing: upgrade from the dashboard, then manage billing")
import hashlib as _hl, hmac as _hm, json as _json, time as _time  # noqa: E401,E402
import stripe as _stripe  # noqa: E402
from api import billing as _billing  # noqa: E402

os.environ["STRIPE_SECRET_KEY"], os.environ["STRIPE_WEBHOOK_SECRET"] = "sk_test_e2e", "whsec_e2e"
_billing.TIERS["starter"]["stripe_price_id"], _billing.TIERS["growth"]["stripe_price_id"] = "price_s", "price_g"
_checkouts: list = []
_stripe.checkout.Session.create = staticmethod(lambda **p: _checkouts.append(p) or _stripe.StripeObject.construct_from(
    {"url": "https://checkout.stripe.com/c/e2e"}, "k"))
_stripe.billing_portal.Session.create = staticmethod(lambda **p: _stripe.StripeObject.construct_from(
    {"url": "https://billing.stripe.com/p/e2e"}, "k"))
_stripe.Subscription.retrieve = staticmethod(lambda sid, *a, **k: _stripe.StripeObject.construct_from(
    {"id": sid, "items": {"data": [{"price": {"id": "price_g"}}]}}, "k"))
_st.cache_data.clear()
at = dashboard("📊  Overview")
plans = [b.label for b in at.button if b.label.startswith(("Starter —", "Growth —"))]
check(plans == ["Starter — $49/mo · 25,000 sessions", "Growth — $149/mo · 100,000 sessions"],
      f"free account: Upgrade offers both plans with prices ({plans})")
run(button(at, "Growth — $149/mo · 100,000 sessions").click())
check(_checkouts and _checkouts[-1]["line_items"] == [{"price": "price_g", "quantity": 1}],
      "choosing Growth starts a Stripe checkout for Growth")
org_id = client.get("/billing/usage", headers=H).json()["org_id"]
payload = _json.dumps({"id": "evt", "object": "event", "type": "checkout.session.completed", "data": {"object": {
    "id": "cs", "client_reference_id": org_id, "customer": "cus_e2e", "subscription": "sub_e2e",
    "payment_status": "paid"}}})
_t = int(_time.time())
_sig = _hm.new(b"whsec_e2e", f"{_t}.{payload}".encode(), _hl.sha256).hexdigest()
r = client.post("/billing/webhook", content=payload, headers={"stripe-signature": f"t={_t},v1={_sig}"})
check(r.status_code == 200, "Stripe's confirmation is accepted")
_st.cache_data.clear()  # the plan box refreshes every minute; don't wait in a test
at = dashboard("📊  Overview")
check("growth" in texts(at) and any(b.label == "Manage billing" for b in at.button),
      "after paying: plan shows growth, and Manage billing replaces Upgrade")

print("11. A brand-new account: welcome panel → sample agent → rule → blocking")
import kalytera.judge as _judge  # noqa: E402


def _stand_in_judge(steps, weights=None, pass_threshold=0.7, custom_metrics=None):  # no LLM key in tests
    bad = next((s for s in steps if any(c.get("success") is False for c in (s.tool_calls or []))), None)
    base = dict(accuracy=0.9, goal_alignment=0.9, decision_quality=0.9, completeness=0.9, helpfulness=0.9,
                factuality=0.9, custom_scores={}, confidence=0.9, eval_error=False)
    if bad is None:
        return {**base, "overall_score": 0.9, "passed": True, "failure_type": None, "failure_step": None,
                "failure_reason": None}
    return {**base, "overall_score": 0.3, "passed": False, "failure_type": "hallucination",
            "failure_step": str(bad.step_number), "failure_reason": "Said the refund went through; refund_api refused."}


_judge.score_session = _stand_in_judge
r = client.post("/signup", json={"email": f"new-{uuid.uuid4().hex[:6]}@example.com", "name": "Newcomer"})
NEW_KEY = r.json()["api_key"]
at = AppTest.from_file("kalytera/dashboard.py", default_timeout=120)
at.session_state["authenticated"] = True
at.session_state["api_key"] = NEW_KEY
run(at)
t = texts(at)
check("Kalytera catches every mistake your AI agents make in production" in t, "new account lands on the welcome page")
check(not at.radio and not at.selectbox, "nothing to pick or navigate yet: no agent picker, no nav")
check(button(at, "Connect").proto.type == "primary", "the main action is Connect (Langfuse / LangSmith, no code)")
check(any(b.label == "▶ Run the sample agent" for b in at.button), "the sample agent is the other option")
check("Waiting for your agent" in t, "and it waits for an agent that uses kalytera.init()")
run(button(at, "▶ Run the sample agent").click())  # scores and switches to the sample agent
run(at)
t = texts(at)
check(at.radio[0].value == "🔴  Failure Feed", "lands on the sample agent's Failure Feed")
check('ob-step done"><span class="n">✓</span><span class="t">Find the problem' in t
      and 'ob-step now"><span class="n">2</span><span class="t">Make it a rule' in t, "stepper: found ✓, now make a rule")
check('<span class="ff-chip">refund api</span>' in t and "Suggested rule</span>Block <code>refund_api</code>" in t,
      "problem found and a rule is suggested")
run(button(at, "⚡ Make it a rule").click())
t = texts(at)
check('ob-step now"><span class="n">3</span><span class="t">Stop it' in t, "stepper moves to: stop it")
check("Would have caught 10 of 10 failed sessions" in t, "watching shows the evidence for the rule")
run(button(at, "Start blocking").click())
t = texts(at)
check("Blocked: refund_api(amount=900)" in t and "The action never ran." in t, "after Start blocking: a live check shows it blocked")
check("Live check" in t and "amount=900" in t, "the check uses a clearly-too-large refund (900)")
check(any("That's the loop" in str(x.value) for x in at.toast), "a toast celebrates the loop")
check("now point it at your agent" in t and any(b.label == "Connect your agent" for b in at.button),
      "finish card: connect your own agent")
check("ob-step now" not in t and t.count('ob-step done') >= 3, "stepper: all three steps done")

print("12. Connect page: Langfuse with no code → its mistakes, live")
import api.connections_api as _conn_api  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402

os.environ["KALYTERA_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
_pulls: list = []


def _fake_fetch(kind, settings, secrets, since):  # Langfuse's API, as converted by kalytera.importers
    _pulls.append((kind, settings, since))
    if secrets.get("secret_key") == "wrong":
        raise ValueError("Langfuse rejected these keys. Use the project's public key (pk-lf-…) and secret key.")
    return [{"id": f"tr{i}", "started_at": None, "turns": [{
        "user": f"Refund ${'950' if i < 6 else '30'} for order {i}", "assistant": "Your refund was issued.",
        "actions": [{"name": "refund_api", "input": {"amount": 950 if i < 6 else 30}, "success": i >= 6,
                     "error": None if i >= 6 else "over limit"}]}]} for i in range(9)]


_conn_api._fetch = _fake_fetch
_slack_posts: list = []
_conn_api.requests.post = lambda url, json, timeout: (_slack_posts.append(json) or
                                                     type("R", (), {"status_code": 200, "text": "ok"})())
run(button(at, "＋ Connect an agent").click())
t = texts(at)
check("Point Kalytera at where your agent" in t, "connect page opens")
check(any(NEW_KEY in c.value for c in at.code), "its 'add to your code' tab has the key filled in")


def _fill_langfuse(secret: str) -> None:
    form_inputs = [x for x in at.text_input if x.label in ("Agent name", "Public key", "Secret key")][:3]
    form_inputs[0].input("Billing bot")
    form_inputs[1].input("pk-lf-1")
    form_inputs[2].input(secret)


_fill_langfuse("wrong")
run(next(b for b in at.button if b.label == "Connect and read my conversations").click())
check("rejected these keys" in texts(at), "wrong keys: says why")
check(client.get("/connections", headers={"Authorization": f"Bearer {NEW_KEY}"}).json()["connections"] == [],
      "and saves nothing")
_fill_langfuse("sk-lf-2")
run(next(b for b in at.button if b.label == "Connect and read my conversations").click())  # reruns into the feed


def reopen(old: AppTest) -> AppTest:
    """A fresh page load with the same session (AppTest keeps the previous page's elements after st.rerun)."""
    new = AppTest.from_file("kalytera/dashboard.py", default_timeout=120)
    for k in ("authenticated", "api_key", "agent_id", "view"):
        if k in old.session_state:
            new.session_state[k] = old.session_state[k]
    return run(new)


at = reopen(at)
t = texts(at)
agent_picker = next(x for x in at.selectbox if x.key == "agent_id")
check(at.radio[0].value == "🔴  Failure Feed" and "billing-bot" in str(agent_picker.value)
      and "Point Kalytera at where your agent" not in t, "after reading: lands on the new agent's Failure Feed")
check("6 of 9 sessions failed" in t, "its real mistakes are there: 6 of 9 conversations failed")
conns = client.get("/connections", headers={"Authorization": f"Bearer {NEW_KEY}"}).json()["connections"]
check(len(conns) == 1 and conns[0]["kind"] == "langfuse" and conns[0]["status"] == "ok", "the connection is saved")
NEW_AGENT = conns[0]["agent_id"]
prof = client.get(f"/agents/{NEW_AGENT}/profile", headers={"Authorization": f"Bearer {NEW_KEY}"}).json()
check((prof["industry"], prof["agent_type"], prof["system"]) == ("retail", "support", "langfuse"),
      "the profile was saved (industry and type from the form, system from the connection)")

print("12b. Rules from your other agents")
at.session_state["view"] = "🛡  Rules"
run(at)
check("From your other agents" in texts(at) and "here it would have caught 6 of 6 failed sessions" in texts(at),
      "the sample agent's refund rule is offered, checked on this agent's conversations")

print("12c. Slack: set up, a new problem arrives, the link opens it")
at.session_state["_page"] = "connect"
run(at)
next(x for x in at.text_input if x.label == "Slack incoming webhook URL").input("https://hooks.slack.com/services/T/B/x")
run(next(b for b in at.button if b.label == "Send a test message and turn on").click())
check(_slack_posts and _slack_posts[0]["text"].startswith("Kalytera is connected"), "test message sent")
check("check the channel" in texts(at), "and the page says so")
db = SessionLocal()
from db.models import LossPattern as _LP  # noqa: E402
pattern = db.query(_LP).filter(_LP.agent_id == NEW_AGENT).first()
db.close()
at2 = AppTest.from_file("kalytera/dashboard.py", default_timeout=120)
at2.session_state["authenticated"], at2.session_state["api_key"] = True, NEW_KEY
at2.query_params["agent"], at2.query_params["problem"] = NEW_AGENT, pattern.id
run(at2)
check(at2.radio[0].value == "🔴  Failure Feed"
      and NEW_AGENT in str(next(x for x in at2.selectbox if x.key == "agent_id").value),
      "a Slack link opens that agent's Failure Feed")
check(any(b.label == "▾ Hide sessions" for b in at2.button), "with that problem's conversations already open")

print("12d. Sharing is on by default and can be turned off")
at2.session_state["view"] = "📊  Overview"
run(at2)
toggle = next(x for x in at2.toggle if x.key == "share_toggle")
check(toggle.value is True and "never conversations" in toggle.help, "on, with the explanation on hover")
run(toggle.set_value(False))
check(client.get("/account/sharing", headers={"Authorization": f"Bearer {NEW_KEY}"}).json()["share_patterns"] is False,
      "turning it off is saved")

print("12e. An agent added with kalytera.init(): asks what it does; empty agent says what's happening")
resp = client.post("/trace", headers={"Authorization": f"Bearer {NEW_KEY}"}, json={
    "id": str(uuid.uuid4()), "agent_id": "fresh-bot", "session_id": "fresh-1", "step_number": 1,
    "step_name": "agent", "input": "hi", "output": "hello", "tool_calls": [], "session_ended": True,
    "timestamp": datetime.now(timezone.utc).isoformat()})
assert resp.status_code == 201, resp.text
at.session_state["_switch_to"] = ("fresh-bot", "🔴  Failure Feed")
run(at)
check("No sessions scored yet" in texts(at), "a just-connected agent: 'no sessions scored yet', not 'all good'")
check("What does this agent do?" in texts(at), "it asks what the agent does (to compare with similar agents)")
run(button(at, "↻ Score my sessions now").click())
run(at)
check("Its one session passed" in texts(at), "Score now → its one session is scored")

print("\nAll dashboard checks passed.")
