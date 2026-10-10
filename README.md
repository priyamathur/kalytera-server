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

**0. See it work first — no account needed:**

```bash
pip install kalytera
kalytera demo
```

This runs a bundled billing-agent session through Kalytera's checks on your machine and shows the step where it broke.

**1. Get a free API key** (no credit card) at **[kalytera.dev](https://kalytera.dev)** → *Get API key*. Your key looks like `kly_live_...`.

<details>
<summary>Prefer the terminal?</summary>

```bash
curl -s -X POST https://api.kalytera.dev/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "name": "my-agent"}' | python3 -m json.tool
```

</details>

**2. Confirm your key works end-to-end:**

```bash
KALYTERA_API_KEY=kly_live_... kalytera check
```

`check` verifies the key, records a test step, and waits for the server to score it:

```
Kalytera check
  ✓ API key accepted
  ✓ Test step recorded  (agent_id='kalytera-check', session_id='kalytera-check-…')
  … waiting for the server to score it (up to 90s)
  ✓ Scored by the LLM judge: overall 0.88  (passed)
```

If something is wrong you get a specific reason — a rejected key, the monthly limit, or an unreachable server — instead of an empty dashboard. The same check is available in Python as `kalytera.check()`.

**3. Add to your agent:**

```python
import kalytera

kalytera.configure(api_key="kly_live_...", agent_id="my-agent")

# Call after every step in your agent workflow
kalytera.trace(
    session_id="session-001",   # same ID groups steps of one conversation
    step_number=1,
    step_name="retrieve_policy",
    input="What is the cancellation policy?",
    output="You can cancel anytime. No refunds for partial months.",
    tool_calls=[{"name": "policy_api", "success": True, "latency_ms": 210}],
)

# Mark the last step so the session is scored
kalytera.trace(
    session_id="session-001",
    step_number=2,
    step_name="respond",
    input="Draft reply",
    output="You can cancel anytime from Settings → Billing.",
    session_ended=True,
)
```

`trace()` returns in under 5ms and never raises — sending happens on a background thread. If your key is rejected or the server is unreachable, Kalytera prints one clear warning to stderr instead of failing silently; your agent keeps running either way.

**4. Open the dashboard** at **[app.kalytera.dev](https://app.kalytera.dev)** — scores appear within a minute of a session ending.

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

**Next — from failure pattern to blocking rule**

- [ ] Draft rules — turn a detected failure pattern into an editable rule
- [ ] Shadow mode — rules log what they *would* have blocked, without changing agent behavior
- [ ] Enforce mode — `kalytera.guard()` checks cached rules in-process (no LLM call) before an action runs
- [ ] Audit trail — every block, allow and rule change recorded

Tracing stays fire-and-forget: `trace()` will never block, even after `guard()` ships.

**Later**

- [ ] Real-time alerts when a session scores badly or a loop is detected
- [ ] Cross-model agreement — flag low-confidence evals by comparing two judges
- [ ] Auto-calibration — suggest weight adjustments when agreement drops below threshold
- [ ] Team review queue — route low-confidence evals to a human reviewer

---

## License

MIT — [priya@kalytera.ai](mailto:priya@kalytera.ai)
