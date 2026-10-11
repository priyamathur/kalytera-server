"""
`kalytera quickstart` — the whole loop on your own account in about two minutes:

  1. sends 24 sessions from a sample refund agent (some go wrong)
  2. the AI judge scores them
  3. Kalytera finds the failure pattern and drafts a rule from the tool calls
  4. you add the rule, turn on blocking, and guard() stops the next bad call

Everything goes to a separate agent ("quickstart-refund-bot-<6 chars>") so
your real agents' data is untouched.
"""
import hashlib
import random
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

from . import tracer

AGENT_PREFIX = "quickstart-refund-bot"
REFUND_LIMIT = 500
# The agent's refund tool rejects anything over the limit, but the agent tells
# the customer the refund went through anyway.
FAILING_AMOUNTS = [620, 750, 890, 940, 1200, 1350, 980, 1500, 700, 1100]
PASSING_AMOUNTS = [25, 40, 60, 75, 89, 120, 150, 199, 240, 310, 380, 450, 95, 275]
SCORE_TIMEOUT_S = 240
SEND_THREADS = 4
SEND_ATTEMPTS = 5
RETRY_STATUSES = (None, 429, 500, 502, 503, 504)
WAKE_TIMEOUT_S = 90


def agent_name(prefix: str, api_key: str) -> str:
    """'quickstart-refund-bot-3f9a1c': an agent_id is owned by one account, so built-in
    commands use a name derived from the key instead of one name shared by everyone."""
    return f"{prefix}-{hashlib.sha256(api_key.encode()).hexdigest()[:6]}"


def sample_sessions(run_id: str) -> List[List[Dict[str, Any]]]:
    """Two steps per session: look up the order, then issue the refund."""
    amounts = [(a, False) for a in FAILING_AMOUNTS] + [(a, True) for a in PASSING_AMOUNTS]
    random.Random(7).shuffle(amounts)
    sessions = []
    for i, (amount, ok) in enumerate(amounts):
        sid, order = f"qs-{run_id}-{i:02d}", f"A{4100 + i}"
        refund_call: Dict[str, Any] = {"name": "refund_api", "input": {"order_id": order, "amount": amount},
                                       "success": ok}
        if not ok:
            refund_call["error"] = f"amount exceeds auto-approval limit ({REFUND_LIMIT})"
        sessions.append([
            {"session_id": sid, "step_number": 1, "step_name": "lookup_order",
             "input": f"Hi, I'd like a refund of ${amount} for order {order}. The item arrived broken.",
             "output": f"Found order {order}: ${amount}, delivered 3 days ago, eligible for refund.",
             "tool_calls": [{"name": "lookup_order", "input": {"order_id": order}, "success": True}]},
            {"session_id": sid, "step_number": 2, "step_name": "issue_refund",
             "input": f"Issue a refund of ${amount} for order {order}.",
             "output": f"Done! Your refund of ${amount} has been issued and will reach your card in 3–5 days.",
             "tool_calls": [refund_call], "session_ended": True},
        ])
    return sessions


def _say(msg: str = "") -> None:
    print(msg, flush=True)


def _fail(msg: str) -> None:
    _say(f"\n  ✗ {msg}")
    sys.exit(1)


def _call(method: str, path: str, body: Optional[Dict[str, Any]] = None,
          timeout: Optional[float] = None) -> Tuple[Optional[int], Any]:
    status, data, err = tracer._http(method, path, body, timeout=timeout)
    if status is None or status >= 400 and status not in (404, 409):
        problem = tracer._connection_problem(status, err)
        _fail(tracer._detail(data) or (problem[1].replace("✗ Kalytera: ", "") if problem else f"HTTP {status}"))
    return status, data


def _ask(question: str, assume_yes: bool) -> bool:
    if assume_yes or not sys.stdin.isatty():
        _say(f"  {question} [Y/n] y")
        return True
    try:  # drop keys pressed while waiting, so they can't answer this question
        import termios
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:
        pass
    answer = input(f"  {question} [Y/n] ").strip().lower()
    return answer in ("", "y", "yes")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _sentence(rule: Dict[str, Any]) -> str:
    ops = {">": "is more than", ">=": "is at least", "<": "is less than", "<=": "is at most",
           "==": "is", "!=": "is not", "in": "is one of"}
    parts = [f"{p['field']} {ops.get(p['op'], p['op'])} {p['value']}" for p in rule["match"].get("args", [])]
    for c in rule.get("session_conditions", []):
        parts.append(f"it's called {c['value']}+ times in {c['window_seconds'] // 60} min")
    verb = {"DENY": "Block", "ESCALATE": "Flag"}.get(rule.get("action"), rule.get("action"))
    return f"{verb} {rule['match']['tool']} when {' and '.join(parts)}" if parts else f"{verb} every {rule['match']['tool']} call"


def _wait(label: str, poll: Callable[[], Tuple[bool, str]], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        done, progress = poll()
        if progress != last:
            if sys.stdout.isatty():
                sys.stdout.write(f"\r  {label} {progress}\033[K")
            else:
                sys.stdout.write(f"  {label} {progress}\n")
            sys.stdout.flush()
            last = progress
        if done:
            if sys.stdout.isatty():
                sys.stdout.write("\n")
            return
        time.sleep(2)
    _fail(f"Timed out after {int(timeout)}s. Check https://app.kalytera.dev in a minute — scoring may still finish.")


def run(api_key: str, endpoint: str = "", assume_yes: bool = False) -> None:
    import contextlib
    import io

    import importlib

    import kalytera
    guard_mod = importlib.import_module("kalytera.guard")  # `from . import guard` is the function

    started = time.monotonic()
    agent_id = agent_name(AGENT_PREFIX, api_key)
    if not api_key:
        _fail("No API key. Get a free one at https://kalytera.dev, then:\n"
              "      export KALYTERA_API_KEY=kly_live_...\n      kalytera quickstart")
    with contextlib.redirect_stdout(io.StringIO()):
        kalytera.configure(api_key=api_key, agent_id=agent_id, api_endpoint=endpoint, verify=False)

    _say("Kalytera quickstart — find how an agent fails, and stop it\n")
    _say("  Connecting… (a server that has been idle can take up to a minute to wake up)")
    for attempt in range(SEND_ATTEMPTS):  # a restarting server answers 502 for a few seconds
        status, usage, _err = tracer._http("GET", "/billing/usage", timeout=WAKE_TIMEOUT_S)
        if status not in RETRY_STATUSES:
            break
        time.sleep(3 * (attempt + 1))
    if status is None or status >= 500:
        _fail("Can't reach Kalytera right now. Try again in a minute.")
    if status != 200:
        _fail(f"API key rejected (HTTP {status}).")
    org = (usage or {}).get("org_name") or "your account"
    _say(f"  ✓ Signed in to {org}\n")

    # ── 1. Traces ────────────────────────────────────────────────────────────
    run_id = uuid.uuid4().hex[:6]
    sessions = sample_sessions(run_id)
    steps = [s for session in sessions for s in session]
    _say(f"1/4  Sending {len(sessions)} conversations from a sample refund agent (agent: {agent_id})")
    _say(f"     Its refund tool rejects refunds over ${REFUND_LIMIT}, and the agent tells the customer")
    _say("     it worked anyway. Kalytera hasn't been told any of this.")

    def send(step: Dict[str, Any]) -> Optional[int]:
        payload = tracer._build_payload(step["session_id"], step["step_number"], step["step_name"],
                                        step["input"], step["output"], step["tool_calls"], {},
                                        agent_id, step.get("session_ended", False))
        status = None
        for attempt in range(SEND_ATTEMPTS):  # ride out a server restart or a busy moment
            status = tracer._http("POST", "/trace", payload, timeout=30)[0]
            if status not in RETRY_STATUSES:
                break
            time.sleep(2 * (attempt + 1))
        return status

    with ThreadPoolExecutor(SEND_THREADS) as pool:
        codes = list(pool.map(send, steps))
    bad = [c for c in codes if c != 201]
    if bad:
        _fail(f"{len(bad)} of {len(steps)} steps weren't recorded (HTTP {bad[0]}).")
    _say(f"     ✓ {len(steps)} steps recorded\n")

    # ── 2. Scoring + 3. patterns ─────────────────────────────────────────────
    _say("2/4  The AI judge reads each conversation and scores it")
    path = f"/agents/{quote(agent_id)}/refresh"
    _, job = _call("POST", path, timeout=30)
    if job is None or "state" not in job:
        _fail("This server can't score on demand yet. Your sessions will be scored within a minute "
              "at https://app.kalytera.dev")
    state: Dict[str, Any] = dict(job)

    def poll() -> Tuple[bool, str]:
        _, s = _call("GET", path, timeout=30)
        state.update(s)
        if s["state"] == "error":
            _fail(f"Scoring failed: {s.get('error')}")
        # Sessions the background scorer already handled count as scored.
        total = len(sessions)
        n = min(total, total - s.get("to_score", 0) + s.get("scored", 0)) if s.get("to_score") else 0
        if s["state"] in ("analyzing", "done"):
            return s["state"] == "done", f"{total}/{total} scored · looking for patterns…"
        return False, f"{n}/{total} scored"

    _wait("   ", poll, SCORE_TIMEOUT_S)
    if state.get("judge_errors"):
        _say(f"     ⚠ The judge couldn't score {_plural(state['judge_errors'], 'conversation')}.")
    failed, scored = state.get("sessions_failed", 0), state.get("sessions_scored", 0)
    earlier = " (including earlier quickstart runs)" if scored > len(sessions) else ""
    _say(f"     ✓ {failed} of {scored} conversations failed{earlier}\n")

    # ── 3. Pattern + drafted rule ────────────────────────────────────────────
    _say("3/4  Kalytera looked for what the failures have in common")
    _, data = _call("GET", f"/rules/suggestions?agent_id={quote(agent_id)}", timeout=60)
    by_pattern = (data or {}).get("by_pattern", {})
    suggestion = next(iter((data or {}).get("suggestions", [])), None)
    existing = next((v for v in by_pattern.values() if v.get("status") == "exists"), None)
    if suggestion:
        rule, cov = suggestion["rule"], suggestion["coverage"]
        cause = next((p.get("root_cause") for p in suggestion.get("patterns", []) if p.get("root_cause")), None)
    elif existing:
        rule, cov, cause = existing["rule"], existing["coverage"], None
        rule = {**rule, "id": existing["rule_id"]}
    else:
        reasons = {v.get("reason") for v in by_pattern.values() if v.get("reason")}
        _fail("No pattern to draft a rule from yet"
              + (f": {next(iter(reasons))}" if reasons else " (the judge may have scored differently).")
              + " See https://app.kalytera.dev → Failure Feed.")
    failing_total = cov["failing_total"]
    if cause:
        _say(f"     Found: {_plural(failing_total, 'conversation')} failed the same way — “{cause}”")
    _say("     It compared their tool calls with the ones that went fine, and drafted a rule:\n")
    _say(f"       🛡  {_sentence(rule)}")
    _say(f"          Would have caught {cov['failing_matched']} of {failing_total} failed conversations"
         f" · {cov['passing_matched']} of {cov['passing_total']} good ones\n")

    # ── 4. Rule → guard() ────────────────────────────────────────────────────
    _say("4/4  Your agent is about to call refund_api(amount=900)")
    q = f"?agent_id={quote(agent_id)}"
    if suggestion:
        if not _ask("Add this rule? It starts in watch mode: it only reports what it would block.", assume_yes):
            _say("\n  OK — you can add it any time from https://app.kalytera.dev → Rules.")
            return
        status, body = _call("POST", "/rules", {**rule, "agent_id": agent_id})
        if status == 409:
            _fail(tracer._detail(body) or "A rule with this name already exists.")
    rid = rule["id"]
    _call("POST", f"/rules/{quote(rid)}/demote{q}")  # rerun-safe: start from watch mode
    guard_mod._refresh(agent_id)
    d = kalytera.guard("refund_api", {"order_id": "A9999", "amount": 900}, session_id=f"qs-{run_id}-live")
    would = next((h for h in d.shadow_hits if h.rule_id == rid), None)
    past = {"DENY": "blocked", "ESCALATE": "flagged"}
    _say(f"       guard() → {d.decision}" + (f"   (watching: the rule would have {past.get(would.action, 'blocked')} it)"
                                         if would else ""))

    if not _ask("Turn on blocking for this sample agent?", assume_yes):
        _say("\n  OK — turn it on any time in https://app.kalytera.dev → Rules → Start blocking.")
        return
    _call("POST", f"/rules/{quote(rid)}/promote{q}")
    guard_mod._refresh(agent_id)
    d = kalytera.guard("refund_api", {"order_id": "A9999", "amount": 900}, session_id=f"qs-{run_id}-live")
    _say(f"       guard() → {d.decision}   reason: {d.reason}")
    ok = kalytera.guard("refund_api", {"order_id": "A9998", "amount": 120}, session_id=f"qs-{run_id}-live")
    _say(f"       guard() for a $120 refund → {ok.decision}")
    kalytera.flush_guard()

    _say(f"\n  Done in {int(time.monotonic() - started)}s. Kalytera found how this agent fails, wrote the rule, "
         "and it now stops the bad refund before it happens.\n")
    _say("  Next — the same for your own agent (two changes):")
    _say("    @kalytera.tool                                   # checks rules before each call")
    _say("    def refund_api(order_id, amount): ...")
    _say("")
    _say("    with kalytera.session(conversation_id, input=message) as s:")
    _say("        s.output = run_my_agent(message)             # recorded and scored")
    _say("")
    _say(f"  See this run: https://app.kalytera.dev → agent “{agent_id}”")
    _say("  Guide: https://github.com/priyamathur/kalytera-server#add-kalytera-to-an-agent-in-production")
