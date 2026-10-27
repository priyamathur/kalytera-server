# Kalytera

Know when your AI agent fails — before your users do.

```bash
pip install kalytera
```

```python
import kalytera

kalytera.configure(
    api_key="kly_live_...",
    agent_id="my-agent",
)

kalytera.trace(
    session_id="session-001",
    step_number=1,
    step_name="classify_intent",
    input="I need to cancel my subscription",
    output="I can help with that. What's the reason?",
)
```

That's it. Kalytera scores every step with an LLM judge and surfaces failure patterns — what's breaking, at which workflow step, and why.

![Kalytera dashboard — quality scores, failure patterns, and trace viewer](https://raw.githubusercontent.com/priyamathur/kalytera-server/main/site/dashboard-overview.png)

→ **[Live demo dashboard](https://app.kalytera.dev)** · **[Get an API key](#get-started)**

---

## Get started

**See the whole loop in about two minutes** (free key, no credit card, at **[kalytera.dev](https://kalytera.dev)** → *Get API key*):

```bash
pip install kalytera
export KALYTERA_API_KEY=kly_live_...
kalytera quickstart
```

A sample refund agent sends 24 conversations to your account. Its refund tool rejects refunds over $500, but the agent tells the customer the refund went through. Kalytera hasn't been told any of that:

```
2/4  The AI judge reads each conversation and scores it
     ✓ 10 of 24 conversations failed
3/4  Kalytera looked for what the failures have in common
     It compared their tool calls with the ones that went fine, and drafted a rule:
       🛡  Block refund_api when amount is more than 450
          Would have caught 10 of 10 failed conversations · 0 of 14 good ones
4/4  Your agent is about to call refund_api(amount=900)
       guard() → ALLOW   (watching: the rule would have blocked it)
       guard() → DENY    (after you turn on blocking)
       guard() for a $120 refund → ALLOW
```

Everything goes to a separate agent, `quickstart-refund-bot`, so your own agents' data is untouched. Open **[app.kalytera.dev](https://app.kalytera.dev)** to see it in **Failure Feed** and **Rules**.

No key yet? `kalytera demo` runs a bundled session through Kalytera's checks locally.

<details>
<summary>Get a key from the terminal</summary>

```bash
curl -s -X POST https://api.kalytera.dev/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "name": "my-agent"}' | python3 -m json.tool
```

</details>

**Then, with your own agent — confirm your key works end-to-end:**

```bash
KALYTERA_API_KEY=kly_live_... kalytera check
```

`check` verifies the key, records a test step, and waits for the server to score it:

```
Kalytera check
  ✓ API key accepted
  ✓ Test step recorded  (agent_id='kalytera-check-3f9a1c', session_id='kalytera-check-…')
  … waiting for the server to score it (up to 90s)
  ✓ Scored by the LLM judge: overall 0.88  (passed)
```

If something is wrong you get a specific reason — a rejected key, the monthly limit, or an unreachable server — instead of an empty dashboard. The same check is available in Python as `kalytera.check()`.

## Connect once — no code

Already sending your agent's conversations to **Langfuse** or **LangSmith**? Open **[app.kalytera.dev](https://app.kalytera.dev)** → **Connect**, paste that project's keys, and Kalytera reads the last 30 days of production conversations while you watch, then keeps reading new ones every 15 minutes. Minutes later the Failure Feed shows what your agent keeps getting wrong.

Add a Slack incoming webhook on the same page and Kalytera tells you when a new problem appears or one gets worse, with a link straight to it.

Keys are stored encrypted and only used to read conversations. To **stop** mistakes as well as catch them, add one line to the agent (below).

## Add Kalytera to an agent in production

```bash
pip install kalytera
export KALYTERA_API_KEY=kly_live_...
```

```python
import kalytera
kalytera.init()          # first thing, before your agents run
```

That's all for the **OpenAI Agents SDK** and **LangChain / LangGraph** (including `create_agent`, `create_react_agent` and your own graphs). `init()` finds the frameworks you have installed and hooks into them:

- **Every run is one session**, recorded with its tool calls and scored when it ends. Each agent shows up in the dashboard under its own name (`Agent(name="Refund bot")`, `create_agent(..., name="Refund bot")`), so several agents need nothing extra. Sub-agents, handoffs and subgraphs stay in the session of the run that started them.
- **Every tool call is checked against your rules first**, using the framework's own hook (a tool input guardrail in the OpenAI Agents SDK, the tool runner in LangChain). MCP tools included.
- **When a rule blocks a call**, the tool doesn't run and the model gets the reason as the tool result ("…blocked (rule refund_cap: Refunds over 500 need review). Do not retry it. Tell the user…"), so your agent explains instead of crashing or retrying.

Want everything under one name? `kalytera.init(agent_id="support-system")`. Names Kalytera picks get a short suffix from your key (`refund-bot-3fa2c1`), so they never clash with another account's agent.

**Your own agent loop, no framework?** Two changes: wrap each conversation in a `session`, and mark the tools that can do damage with `@kalytera.tool`.

```python
@kalytera.tool                          # checks your rules before every call, records it
def refund_api(order_id: str, amount: float) -> str:
    ...

def handle(message: str, conversation_id: str) -> str:
    with kalytera.session(conversation_id, input=message) as s:     # one conversation = one session
        s.output = run_my_agent(message)                            # however your agent works today
        return s.output
```

Here a blocked call raises `kalytera.Blocked` (with `.decision.reason`). To let the agent tell the user instead, return a message:

```python
@kalytera.tool(on_block=lambda d: f"I can't do that automatically: {d.reason}. A person will follow up.")
def refund_api(order_id: str, amount: float) -> str: ...
```

**Works with your stack.**
- Async: `async def` tools and `async with kalytera.session(...)` work the same way.
- Already have `@kalytera.tool` on framework tools? Keep it; with `init()` each call is still checked and recorded once.
- Many steps? Call `s.step("plan", input=..., output=...)` inside the session; tool calls attach to the step they happened in.
- Not Python? Send steps to `POST /trace` and check calls with `POST /guard` ([below](#guard-rules--block-a-known-failure-before-it-happens)).

**Safe to put in front of production.** Recording never blocks or raises: it happens on a background thread, and if your key is rejected or Kalytera is unreachable you get one warning on stderr while your agent keeps running. Rule checks run in your process from a cache (no network or LLM call per check), and if Kalytera is unreachable, tools run — guard fails open. Only rules you promoted can stop a call.

<details>
<summary>Lower level: <code>kalytera.trace()</code> for full control</summary>

```python
kalytera.trace(
    session_id="session-001",   # same ID groups steps of one conversation
    step_number=1,
    step_name="retrieve_policy",
    input="What is the cancellation policy?",
    output="You can cancel anytime. No refunds for partial months.",
    tool_calls=[{"name": "policy_api", "input": {"topic": "cancel"}, "success": True}],
    session_ended=True,         # mark the last step so the session is scored
)
```

</details>

**Open the dashboard** at **[app.kalytera.dev](https://app.kalytera.dev)** — scores appear within a minute of a session ending.

Requires Python 3.9+ (the default `python3` on macOS works).

---

## What Kalytera detects

Each session is scored across six dimensions by an LLM judge (Claude Haiku) — or every individual step when per-step scoring is enabled:

| Dimension | Default weight | What it measures |
|---|---|---|
| Accuracy | 25% | Contextually correct answer for the situation |
| Goal alignment | 25% | Agent stayed on what the user actually needed |
| Decision quality | 15% | Reasoning was sound, right tools were chosen |
| Completeness | 15% | Request fully resolved end-to-end |
| Helpfulness | 10% | Response had practical value the user could act on |
| Factuality | 10% | All claims grounded and true — no hallucinations |

Steps scoring below 70% are flagged. Seven failure types are detected automatically:

`wrong_answer` · `tool_failure` · `goal_drift` · `hallucination` · `context_loss` · `incomplete` · `loop`

Weights and pass threshold are configurable per agent in the dashboard. You can also add custom metrics (e.g. `helpfulness`, `tone`, `compliance`) with their own weights.

---

## Guard rules — block a known failure before it happens

`trace()` tells you what went wrong. `guard()` stops the next one. Check a tool call against your rules before it runs:

```python
d = kalytera.guard("refund_api", {"amount": 900}, session_id=session_id)
if not d.allowed:               # DENY or ESCALATE
    return f"Needs review: {d.reason}"
refund_api(amount=900)
```

**No code needed to try it:** open **[app.kalytera.dev](https://app.kalytera.dev)** → **🛡 Rules** → **＋ New rule**, and write it as a sentence: *when the agent calls* `refund_api` *with* `amount` *is more than* `500`, *block it*. New rules only **watch** (shadow mode) — use **Try it** to see what one would do, then **Start blocking** when its numbers look right. Or let Kalytera write it: on **Failure Feed**, each problem that keeps happening shows a ready rule and how many of its failed sessions it would have caught, compared from the tool calls of failing and successful sessions. Click **⚡ Make it a rule** to add it (watching only). The same suggestions are listed at the top of **Rules**.

Rules are JSON. Every rule starts in **shadow mode**: it records what it *would* have blocked and never changes `guard()`'s answer. Promote it once the shadow numbers look right.

```bash
cat > refund_cap.json <<'JSON'
{"id": "refund_cap",
 "match": {"tool": "refund_api", "args": [{"field": "amount", "op": ">", "value": 500}]},
 "action": "DENY",
 "reason": "Refunds over 500 need review"}
JSON

export KALYTERA_API_KEY=kly_live_... KALYTERA_AGENT_ID=my-agent
kalytera rules add refund_cap.json          # created in shadow mode
kalytera guard refund_api --args '{"amount": 900}'   # ALLOW, shadow: refund_cap would DENY
kalytera rules stats refund_cap             # would-blocks so far
kalytera rules promote refund_cap           # now enforced
kalytera guard refund_api --args '{"amount": 900}'   # DENY
```

- **Operators:** `==` `!=` `>` `>=` `<` `<=` `in` `not in` (an allow-list: anything not listed matches) `contains` (text, or a list where any one matches; ignores case and extra spaces: `{"field": "command", "op": "contains", "value": ["rm -rf", "drop table"]}`). Fields can be nested: `"customer.tier"`. All conditions in a rule must hold. `not in` and `contains` need SDK 0.4.0 or later.
- **Repeated calls:** `"session_conditions": [{"type": "count_in_window", "tool": "refund_api", "op": ">=", "value": 3, "window_seconds": 600}]` matches the 3rd call in 10 minutes within one session.
- **Actions:** `DENY` or `ESCALATE` (a person must approve it; the action doesn't run, and your code decides how the person is asked).
- **Starter rules, before anything goes wrong:** **Rules** lists the risky actions your agent already takes — commands that can wipe files or databases, turning off monitoring or security, deleting things, moving money, changing accounts — each with a ready "a person approves it first" rule (`GET /rules/starter?agent_id=…`).
- **Fast:** rules are cached in your process and refreshed every 30 s — a check makes no network call and no LLM call.
- **Fail-open:** if Kalytera is unreachable, `guard()` uses the last rules it loaded, or returns `ALLOW` if it never loaded any, and says why in `d.error`. Add `"fail_closed": true` to a rule to deny instead when evaluation fails. `guard()` never raises.
- **Private:** decisions are recorded with a hash of the arguments, never the arguments themselves.
- **Every change is a new version:** `kalytera rules show refund_cap` lists them. Also: `list`, `demote`, `delete`.
- **Not using Python?** `POST /guard` with `{"agent_id", "tool", "args", "session_id"}` returns the same decision:

```bash
curl -s -X POST https://api.kalytera.dev/guard \
  -H "Authorization: Bearer $KALYTERA_API_KEY" -H "Content-Type: application/json" \
  -d '{"agent_id": "my-agent", "tool": "refund_api", "args": {"amount": 900}, "session_id": "s1"}'
```

  Rules can be managed over HTTP too: `GET/POST /rules`, `PUT /rules/{id}`, `POST /rules/{id}/promote|demote`, `DELETE /rules/{id}`, `GET /rules/{id}/stats` — see [api.kalytera.dev/docs](https://api.kalytera.dev/docs).

## Check replies before the customer sees them

An agent that says "your refund has been processed" when the refund failed does as much damage as a wrong refund. `check_reply()` stops that reply and gives the customer a safe message instead:

```python
with kalytera.session(conversation_id, input=message) as s:
    reply = run_agent(message)                      # actions made through @kalytera.tool are recorded
    check = kalytera.check_reply(reply)             # held if it claims something the actions don't back up
    s.output = check.reply                          # the original, or a safe message if it was held
send_to_customer(check.reply)
```

- **In code, always:** a reply that says something was done (refunded, cancelled, deleted, sent, processed…) is held when that action failed, was blocked by a rule, or never ran in this conversation. No AI and no network call before the answer, so it adds no delay. Outside a session, pass `actions=[{"name": "refund_api", "success": False}]`.
- **AI review, if you turn it on:** `check_reply(reply, review=True, policy=YOUR_POLICY)` also has Kalytera's AI reviewer read replies about money, policy, accounts or legal matters before they're sent — for example a promise your policy doesn't make. It adds about 1–3 seconds to those replies only (`review="always"`: every reply). If the reviewer doesn't answer within 8 seconds, the reply goes out and `check.error` says why. Up to 2,000 reviews a day per account.
- **You hear about it:** every held reply goes to Slack right away and shows in the Failure Feed with what the agent wanted to send. `safe_reply="…"` sets what the customer gets instead.

## Serious mistakes reach you after one

Most mistakes are reported once they repeat (5 times), so Slack stays quiet. A mistake the judge rates **serious** — money moved wrongly, data or an account deleted or changed, saying something was done when it wasn't, a promise the business may be held to, personal data shown to the wrong person, harmful content — goes to Slack right away, after one conversation, with a link to it.

---

## Calibrate the judge

Every judge has bias. Calibration measures whether Kalytera's LLM judge agrees with your own judgement.

In the Trace Viewer, label any session with **👍 passed** or **👎 failed**. The dashboard shows judge accuracy against your labels and flags when weights need adjustment:

| Agreement | Status |
|---|---|
| ≥ 90% | Calibrated ✓ |
| 80–89% | Good |
| < 80% | Review your scoring weights |

Label 10–20 sessions to get a reliable calibration reading. The more you label, the more precisely Kalytera can tell you if the judge is drifting.

---

## `@watch` decorator

Zero-config alternative — wraps a function and captures input, output, and latency:

```python
@kalytera.watch
def handle_request(user_input: str) -> str:
    return your_agent_logic(user_input)
```

---

## Self-host

For teams that want data on their own infrastructure:

```bash
git clone https://github.com/priyamathur/kalytera-server
cd kalytera-server
cp .env.example .env        # add ANTHROPIC_API_KEY and DATABASE_URL
docker compose up
```

API at `http://localhost:8000`, dashboard at `http://localhost:8501`. Point the SDK at it with `kalytera.configure(api_key=..., api_endpoint="http://localhost:8000")`.

To develop or run the tests without Docker, use **Python 3.11** (pinned in `.python-version`; the server dependencies don't build on 3.13 yet):

```bash
pip install -e ".[server,dev]"
pytest
```

---

## Roadmap

**Shipped — monitoring**

- [x] LLM-as-judge scoring (6 built-in dimensions)
- [x] Custom metrics (helpfulness, tone, compliance, …)
- [x] Golden set calibration — label sessions, measure judge accuracy
- [x] Loss pattern detection — failures grouped by tool and workflow step

**Now — from failure pattern to blocking rule**

- [x] Shadow mode — rules log what they *would* have blocked, without changing agent behavior
- [x] Enforce mode — `kalytera.guard()` checks cached rules in-process (no LLM call) before an action runs
- [x] Versioned rules — every edit, promote and demote is a new version; every decision is recorded
- [x] Rules view in the dashboard — create, test a call, shadow counts, promote, demote, delete
- [x] Draft rules — turn a detected failure pattern into an editable rule, with the evidence

Tracing stays fire-and-forget: `trace()` never blocks. Only `guard()` can block, and only rules you promoted.

**Later**

- [ ] Real-time alerts when a session scores badly or a loop is detected
- [ ] Cross-model agreement — flag low-confidence evals by comparing two judges
- [ ] Auto-calibration — suggest weight adjustments when agreement drops below threshold
- [ ] Team review queue — route low-confidence evals to a human reviewer

---

## License

MIT — [info@kalytera.dev](mailto:info@kalytera.dev)
