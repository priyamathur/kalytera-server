# Kalytera — Internal Architecture

> **Audience:** Priya and engineering collaborators. Full implementation detail.
> Edit this file freely — it is a Mermaid diagram in plain Markdown.

```mermaid
flowchart TD
    subgraph DEV["Developer's Agent Code"]
        A1["kalytera.trace() or @watch decorator\n(kalytera/tracer.py + sdk/client.py)"]
    end

    subgraph SDK["Kalytera SDK — Fire and Forget"]
        B1["trace()\nReturns immediately. Never raises. Never blocks."]
        B2["Thread-safe Queue\nmax 500 events — drops silently if full"]
        B3["Background Worker Thread\n(daemon — dies with process)"]
        B4["_write_trace_to_db()\nDirect SQLAlchemy write to AgentLog"]
        B5["_send_trace_async()\naiohttp POST to /trace endpoint"]
        B6["Local fallback log\nkalytera_traces.log — written on every event"]
    end

    subgraph API["FastAPI — api/main.py — Render"]
        C1["POST /trace\nWrites AgentLog, returns 201 immediately"]
        C2["GET /agents/{agent_id}/patterns\nReturns LossPattern rows for one agent"]
        C3["GET /analytics/* (ingest_endpoints.py app)\nSession volume, intent performance, quality trend"]
        C4["POST /patterns/analyze (ingest_endpoints.py app)\nTriggers pattern detection immediately"]
        C5["Eval Loop\nasync background task, fires every 30s\nScores up to 20 unevaluated logs per agent"]
        C6["Analysis Loop\nasync background task, fires every 60 min\nRuns run_all(db)"]
        C7["Auth: KALYTERA_API_KEY header\nOptional — dev mode allows all if env var not set"]
    end

    subgraph DB["PostgreSQL — Render\n(SQLite for local dev — auto-detected via DATABASE_URL)"]
        D1["AgentLog\nid · agent_id · session_id · step_number\ninput · output · tool_calls · latency_ms\nsession_ended · timestamp · metadata"]
        D2["EvalResult\nlog_id FK · session_id · agent_id\naccuracy · goal_alignment · decision_quality · completeness\noverall_score · passed · failure_type · failure_step\nfailure_reason · confidence · eval_error · evaluated_at"]
        D3["LossPattern\nagent_id · pattern_type · pattern_value\nfailure_count · total_count · failure_rate\npct_of_all_failures · root_cause · is_worsening\nfirst_seen · last_seen"]
        D4["AgentQualityConfig\nagent_id PK · industry · pass_threshold\nweight_accuracy · weight_goal_alignment\nweight_decision · weight_completeness"]
    end

    subgraph JUDGE["LLM Judge — kalytera/judge.py"]
        E1["evaluate_log(log_id, db)\nFetches AgentLog + prior steps, calls score_step()"]
        E2["score_step()\nBuilds prompt via kalytera/prompts.py\nCalls _call_claude()"]
        E3["_call_claude()\nClaude Haiku — claude-haiku-4-5-20251001\nMax 512 tokens"]
        E4["Retry logic\nOn malformed JSON: retry once with simplified prompt\nOn 2nd failure: eval_error=True, no EvalResult written"]
        E5["Failure taxonomy\nwrong_answer · tool_failure · goal_drift\nincomplete · hallucination · context_loss · loop"]
    end

    subgraph ANALYZER["Pattern Analyzer — kalytera/analyzer.py"]
        F1["run_all(db)\nGets all agent_ids from EvalResult\nCalls run_analysis() per agent"]
        F2["run_analysis(agent_id, db)\n_fetch_failures() — passed=False, eval_error=False\n_group_failures() — by failure_step and failure_type"]
        F3["Pattern threshold\n≥ 5 failures required (MIN_FAILURE_COUNT)\nLooks back 7 days (ANALYSIS_WINDOW_DAYS)"]
        F4["Worsening detection\nCurrent 7-day failure rate vs prior 7-day window\nis_worsening=True if current > prior"]
        F5["root_cause\nMost common failure_reason string in the group\n(plain English sentence — never raw JSON)"]
        F6["_upsert_pattern()\nCreates or updates LossPattern row\npct_of_all_failures = key demo metric"]
    end

    subgraph DASH["Streamlit Dashboard — kalytera/dashboard.py"]
        G1["View 1: Agent Overview\nQuality score trend (7 days)\nToday pass rate · active failure count\nTop 3 failure types · latency percentiles"]
        G2["View 2: Failure Feed\nAuto-refresh every 30s\nOne-off catastrophic failures (immediate)\nRepeating patterns grouped with root_cause"]
        G3["View 3: Trace Viewer\nStep-by-step waterfall with latency bars\nPer-step: accuracy, goal_alignment, decision_quality, completeness\nFailure reason in plain English"]
        G4["Config Panel\nAdjust dimension weights per agent\nSet pass_threshold\nWrites to AgentQualityConfig"]
    end

    A1 -->|"fire-and-forget\nnever blocks"| B1
    B1 --> B2
    B2 --> B3
    B3 --> B4
    B3 --> B5
    B3 --> B6
    B4 -->|"SQLAlchemy\ndirect write"| D1
    B5 -->|"aiohttp\nHTTP POST"| C1
    C1 -->|"insert_agent_log()\ndb/queries.py"| D1
    C5 -->|"every 30s\nunevaluated AgentLog rows"| E1
    E1 --> E2 --> E3
    E3 -->|"raw JSON response"| E4
    E4 -->|"parsed result"| E2
    E2 -->|"writes"| D2
    C6 -->|"every 60 min"| F1
    F1 --> F2 --> F3 --> F4 & F5 --> F6
    F6 -->|"upsert"| D3
    C4 -->|"on-demand trigger"| F1
    C2 -->|"get_patterns_for_agent()\ndb/queries.py"| D3
    D1 & D2 & D3 & D4 --> G1 & G2 & G3
    G4 -->|"writes"| D4
    D4 -->|"weights used by"| E2
    C7 -.->|"guards"| C1 & C2
```

## Key constraints (do not violate)

| Constraint | Where enforced |
|-----------|---------------|
| `trace()` never raises, never blocks | `sdk/client.py:trace()` — entire body in try/except |
| Queue drops silently if full | `Queue(maxsize=500)` + `put_nowait()` |
| Eval never runs in trace path | Background loop only — eval runs 30s after trace |
| `failure_reason` is one plain English sentence | Judge prompt explicitly requires it |
| Raw judge JSON never exposed to API clients | Route returns `PatternOut` / `TraceResponse` only |
| All SQL in `db/queries.py` | No inline SQL in routes or service functions |
| Multi-tenant isolation | Every query filtered by `agent_id` |

## Background loop timing

```
t=0s     Developer calls trace() → queue → DB write (< 1ms)
t=30s    Eval loop fires → judge scores new AgentLog rows → EvalResult written
t=3600s  Analysis loop fires → run_all(db) → LossPattern rows written
```

Dashboard auto-refreshes every 30s — patterns appear within ~1 hour of failures starting.
