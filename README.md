# Kalytera

Know when your AI agent fails — before your users do.

```bash
pip install kalytera
```

```python
import kalytera

kalytera.configure(api_key="kly_live_...")

kalytera.trace(
    session_id="session-001",
    step_number=1,
    step_name="classify_intent",
    input="I need to cancel my subscription",
    output="I can help with that. What's the reason?",
)
```

That's it. Kalytera scores every step with an LLM judge and surfaces failure patterns — what's breaking, at which workflow step, and why.

→ **[Live demo dashboard](https://kalytera-dashboard.onrender.com)** · **[Get an API key](#get-started)**

---

## Get started

**1. Get a free API key** (no credit card):

```bash
curl -s -X POST https://agentiq-api-z9it.onrender.com/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "name": "my-agent"}' | python3 -m json.tool
```

Copy the `api_key` from the response (looks like `kly_live_...`).

**2. Install and trace:**

```python
import kalytera

kalytera.configure(
    api_key="kly_live_...",
    api_endpoint="https://agentiq-api-z9it.onrender.com",
    agent_id="my-agent",
)

# Call after every step in your agent workflow
kalytera.trace(
    session_id="session-001",   # same ID groups steps of one conversation
    step_number=1,
    step_name="retrieve_policy",
    input="What is the cancellation policy?",
    output="You can cancel anytime. No refunds for partial months.",
    tool_calls=[{"name": "policy_api", "success": True, "latency_ms": 210}],
)
```

`trace()` returns in under 5ms. It never raises. If the server is unreachable, your agent keeps running.

**3. Open the dashboard** — quality scores appear within 30 seconds:

```
https://kalytera-dashboard.onrender.com
```

---

## What Kalytera detects

Every step is scored across four dimensions by an LLM judge (Claude Haiku):

| Dimension | Default weight | What it measures |
|---|---|---|
| Accuracy | 35% | Did the agent get the facts right? |
| Goal alignment | 35% | Did the agent stay on what the user actually needed? |
| Decision quality | 15% | Was the reasoning sound and tool selection appropriate? |
| Completeness | 15% | Was the request fully resolved? |

Steps scoring below 70% are flagged. Seven failure types are detected automatically:

`wrong_answer` · `tool_failure` · `goal_drift` · `hallucination` · `context_loss` · `incomplete` · `loop`

Weights and pass threshold are configurable per agent in the dashboard. You can also add custom metrics (e.g. `helpfulness`, `tone`, `compliance`) with their own weights.

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

API at `http://localhost:8000`, dashboard at `http://localhost:8501`.

---

## License

MIT — [priya@kalytera.ai](mailto:priya@kalytera.ai)
