# Kalytera

Real-time quality monitoring and failure detection for production AI agents.

Kalytera sits alongside your agent, scores every interaction with an LLM judge, and surfaces recurring failure patterns with root cause so your team can find and fix problems in minutes — not days.

---

## Get started in 2 minutes

**1. Get an API key** (free, no credit card):

```bash
curl -s -X POST https://agentiq-api-z9it.onrender.com/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "name": "your-agent"}' | python3 -m json.tool
```

You'll get back an `api_key` (looks like `kly_live_...`). Save it.

**2. Install the SDK:**

```bash
pip install kalytera
```

Only dependency: `aiohttp`. Does not require the Kalytera server to be running at import time.

**3. Add one call per agent step:**

```python
import kalytera

kalytera.configure(
    api_key="kly_live_...",   # from signup above
    api_endpoint="https://agentiq-api-z9it.onrender.com",
)

kalytera.trace(
    session_id="session-123",
    step_number=1,
    step_name="classify_intent",
    input="I need to cancel my subscription",
    output="I can help with that. Can I ask why?",
)
```

`trace()` returns immediately. It never raises. If the server is unreachable, your agent keeps running and events are queued locally.

---

---

## Full API reference

### `kalytera.configure()`

Call once at startup before the first trace.

```python
kalytera.configure(
    api_key="your-api-key",              # required in production; omit for local dev
    api_endpoint="http://localhost:8000", # defaults to http://localhost:8000
    agent_id="billing-agent",            # optional; auto-generated if not set
)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `api_key` | str | `""` | Authentication key. Set `KALYTERA_API_KEY` env var as an alternative. |
| `api_endpoint` | str | `http://localhost:8000` | URL of your Kalytera API. Set `KALYTERA_API_ENDPOINT` env var as an alternative. |
| `agent_id` | str | auto | Identifies this agent in the dashboard. Use a stable name like `"billing-agent"`. |

---

### `kalytera.trace()`

Call after every agent step — one call per turn in a multi-step workflow.

```python
kalytera.trace(
    session_id="session-123",         # required — same ID groups all steps of one conversation
    step_number=2,                    # required — position in workflow (1, 2, 3…)
    step_name="check_eligibility",    # required — human label shown in dashboard
    input="Is this order refundable?",
    output="Yes, within the 45-day window.",
    tool_calls=[                      # optional — list of tool invocations at this step
        {"name": "policy_lookup", "input": {"product": "headphones"}, "success": True, "latency_ms": 230}
    ],
    metadata={"intent": "refund"},    # optional — any extra context
)
```

| Parameter | Type | Required | Description |
|---|---|---|---|
| `session_id` | str | yes | Groups all steps of one conversation. |
| `step_number` | int | yes | Step position (1, 2, 3…). |
| `step_name` | str | yes | Short label shown in the Trace Viewer (e.g. `"classify_intent"`). |
| `input` | str | yes | What the user (or prior step) sent to the agent. |
| `output` | str | yes | What the agent responded. |
| `tool_calls` | list | no | List of tool invocations at this step. |
| `metadata` | dict | no | Any additional context. |

---

### `@kalytera.watch` decorator

Zero-config alternative. Wraps a function and captures input, output, and latency automatically.

```python
@kalytera.watch
def handle_request(user_input: str) -> str:
    return your_agent_logic(user_input)
```

---

## Environment variables

All parameters can be set via environment variables instead of in code.

| Variable | Equivalent to |
|---|---|
| `KALYTERA_API_KEY` | `api_key` in `configure()` |
| `KALYTERA_API_ENDPOINT` | `api_endpoint` in `configure()` |

```bash
export KALYTERA_API_KEY=your-api-key
export KALYTERA_API_ENDPOINT=https://your-kalytera-host
```

---

## Multi-step conversation example

```python
import kalytera

kalytera.configure(api_key="your-key", api_endpoint="https://your-kalytera-host")

def handle_refund_request(session_id: str, user_message: str):
    # Step 1 — classify
    intent = classify(user_message)
    kalytera.trace(
        session_id=session_id, step_number=1, step_name="classify_intent",
        input=user_message, output=intent,
    )

    # Step 2 — look up account
    account = fetch_account(session_id)
    kalytera.trace(
        session_id=session_id, step_number=2, step_name="fetch_account",
        input="Retrieve account for session",
        output=str(account),
        tool_calls=[{"name": "account_api", "success": account is not None, "latency_ms": 340}],
    )

    # Step 3 — respond
    response = generate_response(intent, account)
    kalytera.trace(
        session_id=session_id, step_number=3, step_name="generate_response",
        input=intent, output=response,
    )
    return response
```

Kalytera evaluates each step in the background. Quality scores appear in the dashboard within 30 seconds.

---

## Hosting options

### Option 1 — Kalytera Cloud (SaaS)
Sign up via the curl command above. Use `api_endpoint="https://agentiq-api-z9it.onrender.com"`. No infrastructure needed.

### Option 2 — Self-hosted (Docker)
For teams that want data on their own infrastructure:

```bash
git clone https://github.com/priyamathur/kalytera-server
cd kalytera-server
cp .env.example .env        # fill in ANTHROPIC_API_KEY and POSTGRES_PASSWORD
docker compose up           # starts API + dashboard + database
```

Your API endpoint: `http://localhost:8000`

### Option 3 — Enterprise (Kubernetes / VPC)
Helm chart for AWS EKS, GCP GKE, or Azure AKS. Data never leaves your VPC.

```bash
helm install kalytera ./helm/kalytera \
  --set secrets.anthropicApiKey=sk-ant-... \
  --set ingress.enabled=true \
  --set ingress.hosts[0].host=kalytera.internal.company.com
```

Contact [priya@kalytera.ai](mailto:priya@kalytera.ai) for the enterprise deployment guide.

---

## What Kalytera monitors

Every step is scored on four dimensions by an LLM judge (Claude):

| Dimension | Weight | What it measures |
|---|---|---|
| Accuracy | 35% | Did the agent get the facts right? |
| Goal alignment | 35% | Did the agent stay on the user's actual request? |
| Decision quality | 15% | Was the action taken the right one? |
| Completeness | 15% | Did the response fully address the request? |

A step passes when the weighted score is ≥ 70. Failing steps surface in the dashboard within 30 seconds.

**7 failure types detected:**
`wrong_answer` · `tool_failure` · `goal_drift` · `hallucination` · `context_loss` · `incomplete` · `loop`

---

## License

MIT
