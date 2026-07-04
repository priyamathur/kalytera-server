# Kalytera Quickstart

---

## Option 1 — Kalytera Cloud (SaaS) — Recommended for most teams

This is the standard path. Kalytera hosts the API and database. You add the SDK to your agent in 3 minutes.

**Step 1 — Install the SDK**

```bash
pip install kalytera
```

> Until the PyPI package is published, install from source:
> ```bash
> git clone https://github.com/your-org/kalytera && cd kalytera && pip install -e .
> ```

**Step 2 — Get your API key**

Sign in at [app.kalytera.ai](https://app.kalytera.ai) → Settings → API Keys → Create key.

Or if Priya gave you one directly: `aq_live_xxxxxxxxxxxxxxxxxx`

**Step 3 — Add to your agent**

```python
import kalytera

kalytera.configure(api_key="aq_live_xxxxxxxxxxxxxxxxxx")  # or set KALYTERA_API_KEY env var

# Call this after every agent response — fire-and-forget, never blocks
kalytera.trace(
    session_id=session_id,          # same ID groups all steps of one conversation
    user_input=user_message,
    agent_response=agent_reply,
    response_time_ms=latency_ms,
    workflow_step=step_number,      # 1, 2, 3... position in workflow
    session_ended=True,             # True on the last step only
)
```

Or use the decorator — zero config, auto-captures input, output, and latency:

```python
@kalytera.watch
def handle_request(user_input: str) -> str:
    return your_agent_logic(user_input)
```

**That's it.** Quality scores appear in the dashboard within 30 seconds. Loss patterns surface after 5+ failures.

---

## Option 2 — Self-Hosted: Docker (small teams, data stays on your infra)

Use this when your team wants data on your own servers without enterprise Kubernetes overhead. Takes about 5 minutes.

**Prerequisites:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed.

```bash
# 1. Clone and configure
git clone https://github.com/your-org/kalytera && cd kalytera
cp .env.example .env
# Open .env and set ANTHROPIC_API_KEY and POSTGRES_PASSWORD

# 2. Start everything (API + dashboard + database)
docker compose up

# 3. Load demo data (first time only, in a second terminal)
docker compose exec api python3 seed_data.py
```

Open:
- **Dashboard** → `http://localhost:8501`
- **API docs** → `http://localhost:8000/docs`

Then point your SDK at your server instead of Kalytera Cloud:

```python
kalytera.configure(
    api_key="your-chosen-key",
    api_endpoint="http://your-server:8000",  # your Docker host
)
```

**To stop:** `Ctrl+C`. **To restart:** `docker compose up` — data persists in the `pgdata` volume.

---

## Option 3 — Enterprise: VPC Deployment (Kubernetes)

For enterprises with compliance requirements, data residency mandates, or SOC 2 obligations. Kalytera deploys into **your** AWS, GCP, or Azure Kubernetes cluster. Data never leaves your VPC.

**Architecture:** Data plane (API + PostgreSQL + trace storage) runs in your VPC. You optionally keep the control plane (dashboard, auth) in-house too.

**What you get:**
- All trace data stays within your network — no data crosses to Kalytera infrastructure
- Connect to internal LLMs and private APIs unreachable from the public internet
- Your own IAM policies, KMS encryption keys, and audit trails
- SAML/OIDC SSO (Okta, Azure AD, Google Workspace)
- RBAC — developer, admin, read-only roles
- Signed BAA for HIPAA, SOC 2 Type II coverage
- Dedicated support SLA

**Deployment:** Helm chart + Terraform modules for AWS EKS, GCP GKE, and Azure AKS. Typical setup time: 1–2 hours with your platform team.

**Minimum infrastructure:** 8 vCPU, 32 GB RAM, managed PostgreSQL, object storage (S3 or equivalent).

Contact [priya@kalytera.ai](mailto:priya@kalytera.ai) for the Helm chart, Terraform modules, and deployment walkthrough.

---

## For Priya — Local Development

When working on Kalytera's own code (not deploying to customers):

```bash
# Terminal 1 — API with hot reload
uvicorn api.main:app --reload --port 8000

# Terminal 2 — Seed demo data (first time)
python3 seed_data.py

# Terminal 3 — Dashboard
streamlit run kalytera/dashboard.py --server.port 8501
```

Or point the dashboard at the live Render deployment:

```bash
KALYTERA_API_ENDPOINT=https://kalytera-api-z9it.onrender.com \
streamlit run kalytera/dashboard.py --server.port 8501
```

---

## Verify the SDK is working

```bash
# Health check
curl https://api.kalytera.ai/health          # SaaS
curl http://localhost:8000/health            # self-hosted

# Send a test trace
curl -X POST https://api.kalytera.ai/trace \
  -H "Authorization: Bearer aq_live_xxx" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"my-agent","session_id":"s1","step_number":1,
       "step_name":"test","input":"help me cancel","output":"I can help",
       "timestamp":"2026-07-03T10:00:00"}'

# Quality scores appear in dashboard within 30s
# Loss patterns appear after 5+ failures of the same type (pattern loop: every 60 min)
```

---

## Run tests (for contributors)

```bash
pytest tests/unit/ -v                           # all 64 tests, ~10 seconds
pytest tests/unit/test_sdk.py -v               # SDK fire-and-forget constraints
pytest tests/unit/test_evaluation.py -v        # LLM judge scoring
pytest tests/unit/test_pattern_analysis.py -v  # loss pattern detection
pytest tests/unit/test_api_endpoints.py -v     # API endpoints
```
