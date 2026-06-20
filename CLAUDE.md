# AgentIQ — CLAUDE.md
# Read this fully before every session.

---

## What We Are Building
AgentIQ runs alongside enterprise AI agents in production. It captures every interaction via a lightweight SDK, evaluates every step in real time with an LLM judge, and surfaces failures with root cause so developers can find and fix problems in minutes.

**The one constraint that overrides every other decision:**
`agentiq.trace()` must never block, never raise, and never slow down the agent it is observing. If AgentIQ is down, the agent keeps running.

---

## Module Structure — Exactly This

```
agentiq/
├── __init__.py      # exposes init(), watch(), trace()
├── tracer.py        # Component 1 — interceptor (DONE)
├── prompts.py       # Component 2a — judge prompt, build_prompt() only
├── judge.py         # Component 2b — scorer using Claude Haiku
├── analyzer.py      # Component 3a — loss pattern detection (hourly job)
├── dashboard.py     # Component 3b — Streamlit, 3 views
├── config.py        # env vars and defaults
db/
├── models.py        # four tables only (see below)
├── queries.py       # all SQL here, nowhere else
tests/
├── test_tracer.py   # Component 1 tests
├── test_judge.py    # Component 2 tests
├── test_analyzer.py # Component 3 tests
api/
└── main.py          # FastAPI: POST /trace, GET /agents/{id}/patterns
requirements.txt
CLAUDE.md
```

---

## Commands
```bash
uvicorn api.main:app --reload --port 8000
streamlit run agentiq/dashboard.py --server.port 8501

alembic upgrade head
alembic revision --autogenerate -m "description"

pytest tests/test_tracer.py -v
pytest tests/test_judge.py -v
pytest tests/ -v

ruff check .
mypy . --strict
```

---

## Build Order — One File Per Session

| # | File | Task | Done? |
|---|------|------|-------|
| 1 | `agentiq/tracer.py` | Interceptor — `trace()` + `@watch` | ✓ |
| 2 | `agentiq/prompts.py` | Judge prompt — `build_prompt()` | ✓ |
| 3 | `agentiq/judge.py` | Scorer — Claude Haiku, writes EvalResult | ✓ |
| 4 | `agentiq/analyzer.py` | Pattern detection — hourly job, writes LossPattern | ✓ |
| 5 | `api/main.py` | Two endpoints: POST /trace, GET /agents/{id}/patterns | ✓ |
| 6 | `agentiq/dashboard.py` | Streamlit, 3 views | ✓ |
| 7 | `seed_data.py` | 500 demo sessions, all 7 failure types | ✓ |

**One task per session. Never two.**

---

## The Exact Prompt for Each Session
```
Read CLAUDE.md fully.
Read claude-progress.txt last 10 lines.

TASK: Build agentiq/<filename>

[paste requirements from spec]

When done:
1. Run: pytest tests/test_<name>.py -v
2. All tests must pass
3. Append to claude-progress.txt: DONE: <file> | [what you built] | [test names]
4. git commit -am 'feat: <file> — <one-line description>'
```

---

## Data Model — Four Tables Only

### AgentLog — written by tracer.py only
| Field | Type | Notes |
|-------|------|-------|
| id | UUID | primary key |
| agent_id | str | set by agentiq.init() |
| session_id | str | groups steps of one workflow run |
| step_number | int | position in workflow (1, 2, 3…) |
| step_name | str | human label e.g. 'retrieve_policy' |
| input | str | what was sent to agent at this step |
| output | str | what the agent responded |
| tool_calls | jsonb | [{name, input, output, success, latency_ms}] |
| latency_ms | int | |
| session_ended | bool | True if last step |
| timestamp | timestamptz | |
| metadata | jsonb | developer-provided context |

### EvalResult — written by judge.py only
| Field | Type | Notes |
|-------|------|-------|
| id | UUID | |
| log_id | UUID | FK to AgentLog |
| session_id | str | denormalized |
| agent_id | str | denormalized |
| accuracy | float | 0.0–1.0 |
| goal_alignment | float | 0.0–1.0 |
| decision_quality | float | 0.0–1.0 |
| completeness | float | 0.0–1.0 |
| overall_score | float | weighted average |
| passed | bool | overall_score >= pass_threshold |
| failure_type | str | null if passed |
| failure_step | int | step where failure originated |
| failure_reason | str | one plain English sentence |
| confidence | float | judge's confidence |
| eval_error | bool | True if judge failed twice |
| evaluated_at | timestamptz | |

### LossPattern — written by analyzer.py only
| Field | Type | Notes |
|-------|------|-------|
| id | UUID | |
| agent_id | str | |
| pattern_type | str | intent \| workflow_step \| tool_call |
| pattern_value | str | 'billing_dispute' or 'step_3' |
| failure_count | int | |
| total_count | int | |
| failure_rate | float | |
| pct_of_all_failures | float | KEY metric |
| root_cause | str | one plain English sentence |
| is_worsening | bool | failure rate up vs prior 7 days |
| first_seen | timestamptz | |
| last_seen | timestamptz | |

### AgentQualityConfig — written by dashboard only
| Field | Type | Default |
|-------|------|---------|
| agent_id | str | primary key |
| industry | str | 'default' |
| weight_accuracy | float | 0.35 |
| weight_goal_alignment | float | 0.35 |
| weight_decision | float | 0.15 |
| weight_completeness | float | 0.15 |
| pass_threshold | float | 0.70 |

---

## Judge Scoring Rules
- `overall_score` = weighted average of 4 dimensions
- Default weights: accuracy 0.35, goal_alignment 0.35, decision_quality 0.15, completeness 0.15
- `passed` = true if `overall_score >= 0.7`
- `failure_reason` must be one plain English sentence — never a JSON dump
- On malformed JSON response: retry once with simplified prompt. On second failure: set `eval_error=True`

## Failure Taxonomy — 7 Types (Do Not Add Without Team Discussion)
`wrong_answer` | `tool_failure` | `goal_drift` | `incomplete` | `hallucination` | `context_loss` | `loop`

---

## API — Two Endpoints Only
- `POST /trace` — receives AgentLog payload, writes to DB
- `GET /agents/{agent_id}/patterns` — returns LossPattern rows for agent

Both routes are async. Auth required. Multi-tenant: every query scoped to `agent_id`.

---

## Dashboard — Three Views Only
1. **Agent Overview** — quality score trend 7 days, today's pass rate, active failure count, top 3 failure types
2. **Failure Feed** — real-time feed, auto-refresh 30s, one-off vs repeating patterns
3. **Interaction Detail** — step-by-step trace, per-step score, failure reason in plain English

---

## Architecture Rules

- **tracer.py:** fire and forget. Queue size 500. On failure: log to `~/.agentiq/errors.log`. Never raise.
- **judge.py:** background async job only — never in the trace path. Claude Haiku model.
- **analyzer.py:** hourly job, idempotent, runs after 5+ failures for a pattern.
- **SQL:** all in `db/queries.py`. No inline SQL anywhere else.
- **Routes:** call service functions. No business logic in routes.
- **Types:** type hints everywhere. `mypy --strict` must pass.

## What Not To Do
- ❌ Do not raise in `trace()` or `@watch`
- ❌ Do not evaluate logs in the trace path
- ❌ Do not expose `failure_reason` raw judge JSON to API clients
- ❌ Do not add a new failure type without team discussion
- ❌ Do not write SQL outside `db/queries.py`
- ❌ Do not commit without running tests + ruff + mypy

---

## Stack
Python 3.11 · FastAPI · PostgreSQL + SQLAlchemy (async) · Alembic · Claude Haiku · Streamlit · aiohttp · Pydantic v2 · pytest · ruff · mypy
