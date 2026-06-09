# AgentIQ — CLAUDE.md
# Read this fully before every session. Keep it open while working.

---

## What We Are Building
AgentIQ runs alongside enterprise AI agents in production. It captures every interaction via a lightweight SDK, evaluates every step in real time with LLM judges, gives every interaction a quality score, surfaces one-off and repeating failures with root cause, and provides a fleet view so enterprises can monitor quality across all their agents at once.

**The problem we solve:** Enterprise AI agents run complex multi-step workflows. Unlike traditional software, agents think and act differently in every interaction — standard quality checks aren't built for that. Existing eval and observability tools use sampled data and after-the-fact analysis. They miss failures that happen mid-workflow, including one-off catastrophic failures.

**The product constraint that overrides every other decision:**
The SDK trace call must never block, never raise, and never slow down the agent it is observing. If AgentIQ is down, the agent keeps running.

See @docs/ARCHITECTURE.md for full system design.

---

## Commands
```bash
# Development
uvicorn api.main:app --reload --port 8000
streamlit run dashboard/app.py --server.port 8501

# Database
alembic upgrade head          # Apply migrations
alembic revision --autogenerate -m "description"  # New migration

# Testing
pytest tests/unit/            # Unit tests — run after every change
pytest tests/integration/     # Integration tests — run before every PR
pytest tests/calibration/     # Judge calibration — run before touching prompts.py
pytest --cov=. --cov-report=term-missing  # Coverage report — target 80% minimum

# Linting and type checking — run before every commit
ruff check .
mypy . --strict
```

---

## Workflow — Follow This Every Time

### Before writing any code
1. **Use plan mode** (Shift+Tab twice) for any task touching more than two files, any schema change, or any refactor. Review and approve the plan before execution. A wrong plan costs hours. A plan review costs 30 seconds.
2. **Read the relevant spec** before touching protected files — see the table at the bottom.
3. **Create a branch** — never work directly on main.

### While writing code
4. **One task per session.** Multi-task prompts produce partially broken output across all tasks. Do one thing completely, verify it works, then move to the next.
5. **Run tests after every meaningful change** — not just at the end.
6. **Clear context** (`/clear`) when switching to a different part of the codebase. Context degradation is the primary failure mode.

### Before committing
7. **Run the full lint + typecheck + unit test sequence.** All must pass.
8. **Review every file you changed.** Unreviewed AI-generated code is technical debt with a short fuse.
9. **Never commit secrets, keys, or credentials** under any circumstances.

---

## Code Quality — Non-Negotiable

### No spaghetti code
- **Single responsibility.** Every function does one thing. If you need to use "and" to describe what a function does, split it.
- **No functions longer than 40 lines.** If it's longer, it's doing too much.
- **No files longer than 300 lines.** If it's longer, it needs to be split into modules.
- **No deeply nested logic.** Maximum 3 levels of nesting. Use early returns to flatten conditionals.
- **No magic numbers or strings.** Every constant lives in `config.py` with a descriptive name.
- **No business logic in API routes.** Routes call service functions. Service functions contain logic.
- **No raw SQL outside `db/queries.py`.** Every database operation is a named function there.
- **No direct model imports in routes.** Routes talk to services. Services talk to the database layer.

### Type safety
- **Type hints on every function signature and every class attribute.** No exceptions.
- **Pydantic models for all API request and response schemas.** Validate at the boundary.
- **mypy --strict must pass** before any commit. Fix type errors — do not suppress them with `# type: ignore` without a comment explaining why.

### Error handling
- **Never silently swallow exceptions.** Log with context. Either handle it or re-raise it.
- **Exception in the SDK trace path:** log locally and continue. Never raise to the agent.
- **Exception in background jobs:** log with full context, increment error counter, continue to next item.
- **Exception in API routes:** return structured error response `{"error": "message", "code": "ERROR_CODE"}`. Never expose stack traces to clients.

---

## Testing — Required, Not Optional

### Unit tests
- **Every function with business logic gets a unit test.** Mock all dependencies.
- **Test the unhappy path** — null inputs, empty lists, wrong types, boundary values.
- **Test file lives next to the source file** or mirrors the path in `tests/unit/`.
- **Naming:** `test_{function_name}_{scenario}` — e.g. `test_classify_intent_empty_input`.

### Integration tests
- **Every API endpoint gets an integration test** with a real test database.
- **Every background job gets an integration test** verifying idempotency.
- **Every database query function gets an integration test** with realistic data volumes.

### Calibration tests — only for `evaluation/`
- Run before AND after any change to `evaluation/prompts.py`.
- Target: >85% accuracy on failure type classification against labeled test set.
- If accuracy drops below 85%, revert the change immediately.

### Coverage
- **Minimum 80% line coverage overall.** Check with `pytest --cov`.
- **100% coverage on `evaluation/`, `patterns/`, `causal/`** — these are the core IP.

---

## Architecture Rules

### The four tables — understand before touching any component
| Table | Written by | Never written by |
|---|---|---|
| AgentLog | SDK trace call only | Anything else |
| SessionSummary | session_builder.py on session end | External code |
| EvalResult | judge.py background job — includes quality_score 0–100 and dimension scores | Synchronous paths |
| LossPattern | analyzer.py hourly job | External code |

**Quality score:** Every EvalResult has a `quality_score` (0–100) computed as a weighted average of four dimensions: accuracy, goal_alignment, decision_quality, completeness. Weights are configurable per agent via `AgentQualityConfig` table. Default weights are equal (0.25 each). Developers adjust weights through the dashboard or API. Custom criteria can be added as additional judge prompt rules per agent.

## Scoring Architecture — V1 and V2

**V1 — Fast frontier model:** Use Claude Haiku as the judge. Latency under 2 seconds per interaction. Cheap enough to run on every interaction. Good enough to collect confirmed failure labels from developers.

**V2 — Distilled proprietary judge:** Every failure a developer confirms in the dashboard is a training example. Once enough labeled examples exist (target: 5,000+ confirmed failures across industries), distill a 3B parameter AgentIQ judge from those examples. Fine-tuned on the seven failure taxonomy, four quality dimensions, and industry-specific standards. This model runs in milliseconds, costs a fraction of an API call, and is more accurate on agent failures than any general-purpose model. It is AgentIQ's proprietary asset — impossible to replicate without the dataset.

**Do not train a classifier.** Classifiers work for narrow, fixed-label tasks. AgentIQ needs multi-dimensional quality scoring with explanations across different agent types. That requires generative reasoning capability, not a classifier.

Full schemas: @docs/ARCHITECTURE.md

### Background jobs — two only
- **Evaluation job:** every 30 minutes, processes unevaluated AgentLog rows in batches of 50.
- **Pattern job:** every hour, analyzes agents with new EvalResult rows since last run.
- Both must be idempotent. Running twice = same result as running once.
- Both must log start time, end time, and row counts.

### API conventions
- Async routes everywhere: `async def`.
- Cursor-based pagination only — no offset pagination on large tables.
- All SQL in `db/queries.py`. Never inline SQL in routes or services.
- Multi-tenant from day one — every query scoped to authenticated agent_id.
- Full API spec: @docs/ARCHITECTURE.md

---

## Three Protected Files — Read the Spec Before Touching

| File | Why protected | Read before touching |
|---|---|---|
| `evaluation/prompts.py` | Core IP. Changes affect every eval result. | @docs/JUDGE.md |
| Failure taxonomy (7 types) | Published research. Public interface. | @docs/TAXONOMY.md |
| Pattern export schema | Public interface. Breaking change = versioning required. | @docs/PATTERNS.md |

---

## What Not To Do

- ❌ Do not add synchronous calls to the SDK trace path
- ❌ Do not evaluate logs synchronously during the trace call
- ❌ Do not run pattern analysis per eval result — it runs on a schedule
- ❌ Do not use offset pagination — use cursor-based
- ❌ Do not put logic in API routes — routes call services
- ❌ Do not write SQL outside `db/queries.py`
- ❌ Do not expose `raw_judge_output` in customer-facing API responses
- ❌ Do not add a new failure type without a team discussion and research review
- ❌ Do not commit without running lint + typecheck + unit tests
- ❌ Do not suppress mypy errors without a documented reason

---

## Stack Quick Reference
Python 3.11 · FastAPI · PostgreSQL + SQLAlchemy (async) · Alembic · Claude Sonnet 4.6 · Streamlit · asyncio · Pydantic v2 · pytest · ruff · mypy · Railway
