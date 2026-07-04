# Kalytera Testing Guide

Two personas. Two sets of steps. Start with your role.

---

## Priya (Founder) — Full System Test

You own the whole stack. This covers every layer from database to dashboard.

### Prerequisites

```bash
# All of these must be true before starting:
docker compose ps      # API + database + dashboard should be "Up"
echo $ANTHROPIC_API_KEY # must be set
```

If not running:
```bash
cp .env.example .env   # fill in ANTHROPIC_API_KEY and POSTGRES_PASSWORD
docker compose up -d
```

---

### Step 1 — Automated test suite

```bash
cd /Users/udayshankar/Documents/AgentIQ

# Run all unit tests (no database, no API calls, mocked Claude)
pytest tests/unit/ -v

# Expected: all green. If any fail, fix before continuing.
```

What these tests cover:
- Tracer: fire-and-forget, never raises, queue behavior
- Judge: scoring logic, retry on malformed JSON, eval_error flag
- API endpoints: auth check, trace ingestion, pattern retrieval
- SDK: configure() and trace() signatures
- Pattern analyzer: failure detection, worsening trend logic

---

### Step 2 — API health check

```bash
# Basic health
curl http://localhost:8000/health

# Expected: {"status": "ok"}

# Swagger UI — explore all endpoints
open http://localhost:8000/docs
```

---

### Step 3 — Send a real trace and watch it evaluated

```bash
# Send one trace (requires running API)
curl -X POST http://localhost:8000/trace \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "agent_id": "test-agent",
    "session_id": "priya-test-001",
    "step_number": 1,
    "step_name": "classify_intent",
    "input": "I need to cancel my subscription",
    "output": "I can help with that. Let me look up your account.",
    "latency_ms": 340,
    "session_ended": true
  }'

# Expected: {"status": "ok", "log_id": "..."}
```

Wait 30–60 seconds for the background judge to evaluate it, then check:

```bash
# Check it was evaluated
curl http://localhost:8000/agents/test-agent/patterns \
  -H "X-API-Key: your-api-key"
```

---

### Step 4 — Load demo data and verify dashboard

```bash
# Load 500 demo sessions (runs fast, ~30 seconds)
python3 seed_data.py

# Then open the dashboard
open http://localhost:8501
```

What to verify in the dashboard:

**Agent Overview tab**
- [ ] Quality score trend chart shows 7 days of data
- [ ] Pass rate is between 60–90% (demo data is calibrated)
- [ ] At least 3 failure types appear in the breakdown

**Failure Feed tab**
- [ ] Shows sessions with failed evaluations
- [ ] "Repeating" badge appears for patterns seen 5+ times
- [ ] Auto-refresh every 30 seconds (watch it tick)

**Trace Viewer tab**
- [ ] Click any session in the sidebar
- [ ] All steps appear as collapsible cards
- [ ] Failed steps are auto-expanded
- [ ] Step name is the expander label (not generic "Step 1")
- [ ] Step duration bar chart appears — green for pass, red for fail
- [ ] Root cause alert appears at the top for failed sessions
- [ ] Score bars show per-dimension breakdown

---

### Step 5 — Load 100K sessions (scale test)

```bash
# Takes ~5 minutes. Watch for errors.
python3 load_100k.py

# Then reload the dashboard and check:
# - billing-agent should have worsening trend (is_worsening=True)
# - support-agent should also show worsening
# - Patterns page should show failure_rate > 0.4 for billing disputes
```

---

### Step 6 — Verify pattern detection

```bash
# Check patterns for billing-agent (highest failure volume)
curl "http://localhost:8000/agents/billing-agent/patterns" \
  -H "X-API-Key: your-api-key" | python3 -m json.tool

# What to look for:
# - pattern_type: "intent" with pattern_value: "billing_dispute"
# - failure_rate > 0.4
# - is_worsening: true (if 100K load ran within last 7 days)
# - root_cause: one plain English sentence
```

---

### Step 7 — Auth check (security)

```bash
# No API key — must reject
curl -X POST http://localhost:8000/trace \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "test", "session_id": "x", "step_number": 1, "step_name": "s", "input": "i", "output": "o"}'

# Expected: 401 or 403

# Wrong API key — must reject
curl http://localhost:8000/agents/test-agent/patterns \
  -H "X-API-Key: wrong-key"

# Expected: 401 or 403
```

---

### Step 8 — Multi-tenant isolation check

```bash
# Traces for agent-A should not appear under agent-B
curl -X POST http://localhost:8000/trace \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"agent_id": "agent-A", "session_id": "iso-test", "step_number": 1, "step_name": "test", "input": "x", "output": "y"}'

curl "http://localhost:8000/agents/agent-B/patterns" \
  -H "X-API-Key: your-api-key"

# Expected: empty patterns list for agent-B
```

---

## Developer — Integration Test

You're adding Kalytera to your agent. These are the exact steps a developer follows.

### Step 0 — Prerequisites

- Python 3.11 or 3.12
- A running Kalytera server (either `http://localhost:8000` or a URL from your Kalytera admin)
- Your API key

---

### Step 1 — Install the SDK

```bash
pip install kalytera
# or
pip3 install kalytera

# Verify
python3 -c "import kalytera; print('ok')"
# Expected: ok
```

---

### Step 2 — Configure once at startup

```python
import kalytera

# In production — use env vars:
# export KALYTERA_API_KEY=your-key
# export KALYTERA_API_ENDPOINT=https://kalytera.yourcompany.com

kalytera.configure(
    api_key="your-api-key",
    api_endpoint="http://localhost:8000",  # or your production URL
    agent_id="my-agent",                  # pick a stable name
)

print("configured")
```

---

### Step 3 — Add trace() to your agent

Minimal example (single-step):

```python
import kalytera
import time

kalytera.configure(api_key="your-key", api_endpoint="http://localhost:8000")

def my_agent(user_message: str, session_id: str) -> str:
    start = time.time()

    # ... your agent logic here ...
    response = "Here is my answer."

    latency_ms = int((time.time() - start) * 1000)

    kalytera.trace(
        session_id=session_id,
        step_number=1,
        step_name="respond",
        input=user_message,
        output=response,
    )

    return response

# Test it
result = my_agent("How do I cancel?", "session-dev-001")
print(result)
# trace() already returned — fire and forget
```

Multi-step example:

```python
def handle_billing_issue(session_id: str, user_message: str) -> str:
    # Step 1 — classify
    intent = "billing_dispute"
    kalytera.trace(
        session_id=session_id,
        step_number=1,
        step_name="classify_intent",
        input=user_message,
        output=f"Classified as: {intent}",
    )

    # Step 2 — fetch account (simulate tool call)
    account_data = {"id": "acct_123", "status": "active"}
    kalytera.trace(
        session_id=session_id,
        step_number=2,
        step_name="fetch_account",
        input="Lookup account",
        output=str(account_data),
        tool_calls=[{"name": "account_lookup", "success": True, "latency_ms": 220}],
    )

    # Step 3 — respond
    response = "I see your account is active. Let me check the billing details."
    kalytera.trace(
        session_id=session_id,
        step_number=3,
        step_name="generate_response",
        input=intent,
        output=response,
    )
    return response
```

---

### Step 4 — Verify traces are arriving

Go to the Kalytera dashboard and look for your session under the agent name you set in `configure()`.

Or check via API:
```bash
curl "http://localhost:8000/agents/my-agent/patterns" \
  -H "X-API-Key: your-key"
```

Evaluation happens in the background within 30–60 seconds of the trace arriving.

---

### Step 5 — Verify trace() never raises

```python
import kalytera

# Intentionally wrong endpoint — should NOT raise
kalytera.configure(api_key="test", api_endpoint="http://localhost:9999")

try:
    kalytera.trace(
        session_id="test",
        step_number=1,
        step_name="test",
        input="x",
        output="y",
    )
    print("trace() returned without raising — correct")
except Exception as e:
    print(f"BUG: trace() raised {e}")
```

Expected output: `trace() returned without raising — correct`

---

### Step 6 — Environment variable config (recommended for production)

```bash
export KALYTERA_API_KEY=your-production-key
export KALYTERA_API_ENDPOINT=https://kalytera.yourcompany.com
```

```python
import kalytera

# No configure() call needed — reads from env
kalytera.trace(
    session_id="session-prod-001",
    step_number=1,
    step_name="respond",
    input="How do I upgrade?",
    output="You can upgrade at kalytera.ai/pricing.",
)
```

---

### Step 7 — @watch decorator (zero-code-change option)

If you want to monitor a function without changing its internals:

```python
import kalytera

@kalytera.watch
def handle_request(user_input: str) -> str:
    return "response"

# Kalytera captures input, output, and latency automatically.
# session_id is auto-generated per call.
```

---

## What Each Test Confirms

| Test | What passes means |
|------|------------------|
| `pytest tests/unit/ -v` | Core logic works — scoring, tracing, patterns |
| `curl /health` | API is reachable and DB connection is live |
| Send trace + wait 30s | End-to-end pipeline: ingest → evaluate → store |
| Dashboard shows real data | DB → Streamlit query path is correct |
| `trace()` with wrong endpoint | SDK fails silently — agent is never blocked |
| Auth rejection test | Multi-tenant isolation is enforced |
| 100K load + patterns | Pattern detection works at real scale |
