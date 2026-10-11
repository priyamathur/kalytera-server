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
check(list(at.radio[0].options) == ["📊  Overview", "🔴  Failure Feed", "🛡  Rules"],
      "sidebar has Overview, Failure Feed, Rules (no Trace Viewer tab)")
check(any(t.placeholder.startswith("🔍  Search sessions") for t in at.text_input), "search box at the top")

# ── 4. Failure Feed ──────────────────────────────────────────────────────────
print("4. Failure Feed reads in sessions, with a ready rule")
at = dashboard("🔴  Failure Feed")
t = texts(at)
check("<b>10 sessions</b> with a tool failure · 26% of all sessions" in t,
      "refund problem: '10 sessions with a tool failure · 26% of all sessions'")
check("<b>5 sessions</b> with a loop failure · 13% of all sessions" in t,
      "loop problem: '5 sessions with a loop failure · 13% of all sessions'")
check("failures</b>" not in t, "no '... failures' counts left")
check("Rule ready:</b> Block <code>refund_api</code> when amount is more than" in t, "refund rule is ready")
check("<b>10 of 10 sessions</b>" in t and "0 of 23 successful ones" in t,
      "citation: caught 10 of 10 failed sessions, 0 of 23 successful")
check("Rule ready:</b> Flag <code>lookup_order</code> when it's the 3rd call or more" in t, "loop rule is ready")

print("5. See sessions → open a trace → back")
run(button(at, "See 10 sessions").click())
opens = [b for b in at.button if b.key and b.key.startswith("ps_")]
check(len(opens) == 10, "10 sessions listed inline, under the card")
check("<code>sess-27</code>" in texts(at), "newest failed session (sess-27) is listed")
run(opens[0].click())
check("Session trace" in texts(at), "trace opens in place")
check("lookup_order" in texts(at) and "issue_refund" in texts(at), "trace shows the session's steps")
run(button(at, "← Back to Failure Feed").click())
check("What keeps failing" in texts(at), "back on the Failure Feed")

print("6. Make it a rule (one click)")
make = [b for b in at.button if b.label == "⚡ Make it a rule"]
check(len(make) == 2, "both problems offer '⚡ Make it a rule'")
run(make[0].click())
check("✓ Added rule" in texts(at), "confirmation shown on the card")
rules = client.get("/rules", params={"agent_id": AGENT}, headers=H).json()["rules"]
check(len(rules) == 1 and rules[0]["mode"] == "shadow", "rule saved in watch (shadow) mode")
check(rules[0]["match"]["tool"] == "refund_api", "it's the refund rule")
at = dashboard("🔴  Failure Feed")
check("<b>Your rule:</b> Block <code>refund_api</code>" in texts(at)
      and any(b.label == "▶ Test it" for b in at.button), "after reload the card shows the rule, ready to test")
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
check(at.radio[0].value == "📊  Overview", "falls back to Overview")

print("11. A brand-new account: welcome panel → sample agent → rule → test → blocking")
import kalytera.judge as _judge  # noqa: E402


def _stand_in_judge(steps, weights=None, pass_threshold=0.7):  # no LLM key in tests
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
check("Run the sample agent" in texts(at) or any(b.label == "▶ Run the sample agent" for b in at.button),
      "new account sees the welcome panel")
run(button(at, "▶ Run the sample agent").click())  # scores and switches to the sample agent
run(at)
t = texts(at)
check("Kalytera found this on its own" in t, "lands on the sample agent's Failure Feed with a hint")
check("<b>10 sessions</b> with a hallucination failure" in t and "Rule ready:</b> Block <code>refund_api</code>" in t,
      "problem found and a rule is ready")
run(button(at, "⚡ Make it a rule").click())
run(button(at, "▶ Test it").click())
check("would have blocked it" in texts(at), "test while watching: allowed, but would have blocked")
check("amount=900" in texts(at), "the test uses a clearly-too-large refund (900)")
run(button(at, "Start blocking").click())
t = texts(at)
check("Blocked: refund_api(amount=900)" in t and "The tool never ran." in t, "after Start blocking: Blocked")
check("That's the loop" in t, "and it points to connecting your own agent")

print("\nAll dashboard checks passed.")
