# AgentIQ Testing Plan
Automated → Manual · June 2026

## HOW TO USE THIS PLAN
Run automated tests first. They are fast, repeatable, and catch regressions immediately. Manual tests follow — they validate the product experience, judge quality, and catch things automation cannot. Every section maps to a component in the codebase. Run in the order shown.

## THE ONE CONSTRAINT THAT OVERRIDES EVERY TEST
The SDK trace call must never block, never raise, and never slow down the agent. Test SDK-level error handling before anything else. If the SDK breaks the agent, nothing else matters.

## Phase 1 — Automated Tests
Run with: `pytest tests/ --cov=. --cov-report=term-missing`
Target: 80% overall coverage. 100% on evaluation/, patterns/. All must pass before any manual testing.

### 1A - SDK — agentiq.trace()
Core constraint: never blocks, never raises, never slows the agent

| ID | Test · Description | Expected Result | Type |
|---|---|---|---|
| SDK-01 | Trace call returns immediately | Returns in < 5ms. Does not block. | AUTOMATED |
| SDK-02 | AgentIQ down — agent keeps running | No exception raised. Agent continues. | AUTOMATED |
| SDK-03 | Invalid inputs — no exception | No exception. Fails silently. Logs locally. | AUTOMATED |
| SDK-04 | Network timeout — no exception | No exception. Returns within 5ms. | AUTOMATED |
| SDK-05 | AgentLog written to DB | AgentLog row exists with correct fields. | AUTOMATED |
| SDK-06 | session_ended flag set correctly | AgentLog row has session_ended=True. | AUTOMATED |
| SDK-07 | Concurrent trace calls | All 100 AgentLog rows written. No deadlocks. | AUTOMATED |
| SDK-08 | Webhook receiver — POST /trace | 201 response. AgentLog row created. | AUTOMATED |

### 1B - Ingestion — Intent Classifier & Session Builder
Classifies intent on ingest. Builds SessionSummary on session end.

| ID | Test · Description | Expected Result | Type |
|---|---|---|---|
| ING-01 | Intent classifier — billing intent | Intent = billing_dispute. Confidence > 0.8. | AUTOMATED |
| ING-02 | Intent classifier — empty input | Intent = unknown. No exception. | AUTOMATED |
| ING-03 | Intent classifier — all 5 types | All 5 correctly classified. | AUTOMATED |
| ING-04 | SessionSummary built on session end | SessionSummary row created with correct fields. | AUTOMATED |
| ING-05 | SessionSummary — drop-off step | drop_off_step = step_3. completed = False. | AUTOMATED |
| ING-06 | SessionSummary — workflow path | workflow_path = 'greet > auth > resolve > close'. | AUTOMATED |
| ING-07 | SessionSummary not duplicated | Only one SessionSummary row. Idempotent. | AUTOMATED |

### 1C - Evaluation — LLM Judge & Quality Score
Core IP. Run calibration tests before and after any change to prompts.py.

**CRITICAL RULE**: Any change to evaluation/prompts.py requires running the full calibration test suite before AND after. If accuracy drops below 85% on the labeled test set, revert immediately. Do not merge.

| ID | Test · Description | Expected Result | Type |
|---|---|---|---|
| EVL-01 | EvalResult created for every AgentLog | 50 EvalResult rows. None skipped. | AUTOMATED |
| EVL-02 | Quality score range | All quality_score values between 0.0 and 1.0. | AUTOMATED |
| EVL-03 | Quality score — known good interaction | quality_score > 0.7. passed = True. | AUTOMATED |
| EVL-04 | Quality score — known bad interaction | quality_score < 0.7. passed = False. | AUTOMATED |
| EVL-05 | Failure type — tool_failure classification | failure_type = tool_failure. failure_step = 3. | AUTOMATED |
| EVL-06 | Failure type — all 7 types | All 7 correctly classified. Accuracy > 85%. | CALIBRATION |
| EVL-07 | Failure type — wrong_answer | failure_type = wrong_answer. | CALIBRATION |
| EVL-08 | Failure type — goal_drift | failure_type = goal_drift. | CALIBRATION |
| EVL-09 | Failure type — context_loss | failure_type = context_loss. | CALIBRATION |
| EVL-10 | Failure type — loop | failure_type = loop. | CALIBRATION |
| EVL-11 | Prior context included | Judge output references prior context. | AUTOMATED |
| EVL-12 | Eval job is idempotent | Same EvalResult rows. No duplicates. | AUTOMATED |
| EVL-13 | Industry weights — healthcare | accuracy_weight = 0.5 in quality score. | AUTOMATED |
| EVL-14 | Industry weights — custom override | Custom weights applied. Scores recalculated. | AUTOMATED |
| EVL-15 | Malformed judge output — retry | Retries once. On second failure: eval_error=True. | AUTOMATED |

### 1D - Loss Pattern Analysis — Pattern Detector
Runs hourly. Must be idempotent. Core IP.

| ID | Test · Description | Expected Result | Type |
|---|---|---|---|
| PAT-01 | Intent pattern detected | LossPattern with pattern_type=intent, pattern_value=billing_dispute. | AUTOMATED |
| PAT-02 | Step pattern detected | LossPattern with pattern_type=workflow_step, pattern_value=step_3. | AUTOMATED |
| PAT-03 | Tool pattern detected | LossPattern with pattern_type=tool_call. | AUTOMATED |
| PAT-04 | pct_of_all_failures correct | billing pattern pct_of_all_failures = 0.47. | AUTOMATED |
| PAT-05 | Root cause generated | root_cause is a non-empty sentence. | AUTOMATED |
| PAT-06 | Pattern below threshold not created | No LossPattern created. | AUTOMATED |
| PAT-07 | is_worsening flag | is_worsening = True. | AUTOMATED |
| PAT-08 | Pattern analyzer idempotent | Same LossPattern rows. No duplicates. | AUTOMATED |
| PAT-09 | Pattern export JSON schema | JSON matches published schema exactly. | AUTOMATED |

### 1E - API Endpoints
Every endpoint has an integration test with a real test database.

| ID | Test · Description | Expected Result | Type |
|---|---|---|---|
| API-01 | POST /trace — valid payload | 201. AgentLog created. | AUTOMATED |
| API-02 | POST /trace — missing required fields | 422 Unprocessable Entity. | AUTOMATED |
| API-03 | GET /agents/{id}/patterns | 200. Array of LossPattern objects. | AUTOMATED |
| API-04 | GET /agents/{id}/patterns — empty | 200. Empty array. Not 404. | AUTOMATED |
| API-05 | Authentication — missing API key | 401 Unauthorized. | AUTOMATED |
| API-06 | Authentication — wrong agent_id | 403 Forbidden. Multi-tenant isolation. | AUTOMATED |
| API-07 | Pagination — cursor-based | Returns correct page. next_cursor present. | AUTOMATED |
| API-08 | raw_judge_output not exposed | No raw_judge_output field in response. | AUTOMATED |

## Phase 2 — Manual Tests
Run after all automated tests pass. These validate product experience, judge quality, and edge cases automation cannot cover.
Estimated time: 2–3 hours. Run before every significant release.

### 2A - End-to-End Flow — Real Agent Connection
The full product experience from a developer's perspective.

**SETUP REQUIRED**: You need a real agent running locally or on Railway. Use the 500-session demo dataset if no real agent is available. This test is about what the developer sees and experiences, not just whether data flows correctly.

**The developer experience test**: Run through this sequence as if you are a developer connecting AgentIQ for the first time. Time each step. If any step takes more than 2 minutes, it is too slow.

1. Add agentiq.trace() to a real agent or demo script. Time to first data: should be under 2 minutes.
2. Open the dashboard. Verify: quality scores appear for new interactions within 30 seconds.
3. Trigger a deliberate failure — use a billing dispute session from the demo dataset.
4. Verify: failure appears in the Failure Feed within 30 seconds. Failure type is correct.
5. Wait for pattern analysis to run (or trigger manually). Verify: billing dispute pattern appears with correct root cause and pct_of_all_failures.
6. Click into a failure from the Failure Feed. Verify: full step-by-step trace visible. Quality score per step visible. Failure reason readable in plain English.
7. Adjust quality dimension weights for the agent. Verify: quality scores update. Pass/fail threshold changes reflect immediately.
8. Disconnect AgentIQ (shut down API). Verify: agent continues running without errors or slowdown.

### 2B - Judge Quality — Manual Calibration Review
Verify the judge is making decisions a developer would agree with.

Pull 20 random EvalResult rows from the database. For each one, read the interaction and ask: does the judge's score and failure classification match what you would say?

**Scoring rubric for manual review**:
- **16 or more out of 20**: Judge is well calibrated. Ship.
- **4 to 7 out of 20**: Review disagreements. Identify pattern. May need prompt adjustment.
- **8 or more out of 20**: Do not ship. Review prompts.py. Run calibration suite.

**Industry-specific quality check**:
1. Run a healthcare agent interaction through AgentIQ. Verify: accuracy and safety weighted higher than other dimensions by default.
2. Run a coding agent interaction. Verify: correctness and completeness weighted higher.
3. Run a retail agent interaction. Verify: task resolution and tone weighted higher.
4. Switch the same agent to a different industry profile. Verify: scores change to reflect new weights.

### 2C - Dashboard — Manual UX Review
What the developer actually sees and experiences.

**Agent Overview view**:
- Quality score trend is visible and updating in real time.
- Active failure count is correct — matches count of failed EvalResults in DB.
- Top failure types are ranked correctly by frequency.
- A developer who has never seen AgentIQ can understand this view in under 30 seconds.

**Failure Feed view**:
- New one-off failures appear within 30 seconds of occurring.
- Repeating patterns are grouped — not shown as individual failures once they repeat 5+ times.
- Each pattern card shows: pattern type, failure rate, pct_of_all_failures, root cause in plain English.
- Root cause sentences are specific and actionable — not vague. 'Payment API times out at step 3' not 'tool error detected'.
- A developer can read a pattern card and know exactly what to fix without opening any other tool.

**Interaction Detail view**:
- Full step-by-step trace visible for any selected interaction.
- Quality score shown per step — not just overall.
- The step where failure originated is clearly indicated.
- Failure reason is one plain English sentence. Not a JSON dump. Not a stack trace.
- Developer can click from a pattern card directly to a sample failed interaction.

### 2D - Critical Failure Scenarios
The real production failures AgentIQ must catch. Test these manually with real sessions.

**WHY THESE ARE MANUAL**: These scenarios require real multi-step agent interactions with deliberate failure injection. Automated tests use synthetic data. These use realistic production-like sessions to verify the judge catches what it must catch.

| Scenario | How to reproduce | AgentIQ must catch |
|---|---|---|
| The $47K loop | Run a session where the agent repeats the same action at steps 3, 4, and 5 with identical outputs. | failure_type = loop detected by step 5. Surfaces in Failure Feed immediately. |
| The Chevy $1 sale | Run a sales agent session where the agent agrees to an off-script request that violates its business purpose. | failure_type = goal_drift detected. Low goal_alignment score. Surfaces as one-off failure immediately. |
| Silent mid-workflow failure | Run a session where the agent makes a wrong decision at step 3 but produces a plausible-looking final output at step 6. | Failure detected at step 3, not step 6. Overall session score low despite plausible final output. |
| Context loss over long session | Run a 7-step session where the agent contradicts something the user said at step 1 at step 6. | failure_type = context_loss at step 6. Prior context referenced in failure reason. |

### 2E - Launch Readiness Checklist
Everything that must be true before posting in Latent Space, Discord, or HackerNews.

**Automated tests**:
- All automated tests pass (pytest tests/)
- Coverage report: overall ≥ 80%. evaluation/ and patterns/ = 100%.
- ruff check . passes with zero errors.
- mypy . --strict passes with zero errors.

**Judge quality**:
- Manual calibration review: 16+ of 20 interactions scored correctly.
- All 4 critical failure scenarios caught correctly (loop, goal_drift, mid-workflow, context_loss).
- Industry defaults work correctly for at least 2 industries.

**Demo dataset**:
- 500 sessions loaded on deployed Railway instance.
- At least 3 active LossPattern rows visible in dashboard.
- Billing dispute pattern shows pct_of_all_failures > 40%.
- Root cause sentences are specific and readable — not 'error detected'.

**SDK**:
- agentiq.trace() verified non-blocking with real agent (time < 5ms).
- Agent keeps running when AgentIQ is shut down.
- One-line integration works with at least one real agent framework.

**Dashboard**:
- A developer who has never seen AgentIQ can understand the Failure Feed in under 30 seconds.
- New failures appear within 30 seconds of occurring.
- Interaction Detail shows step-level quality scores and plain English failure reason.

**Security**:
- No API keys or secrets committed to git.
- Multi-tenant isolation tested: agent A cannot see agent B's data.
- raw_judge_output not exposed in any customer-facing API response.

## Go / No-Go Decision

| Status | Meaning | Action |
|---|---|---|
| All automated pass + launch checklist complete | Product is ready to post publicly. | ✓ GO — post in Latent Space, Discord, HackerNews. |
| Automated pass but 1–2 manual checklist items incomplete | Core works. Polish items outstanding. | Share with 1-2 trusted developers only. Fix outstanding items before public post. |
| Any automated test fails OR judge accuracy < 80% OR SDK blocks agent | Product not ready. Risk of embarrassing public failure. | ✗ NO-GO — fix blocking issues first. Do not post. |

## THE MOST IMPORTANT TEST OF ALL
Connect AgentIQ to a real agent. Open the dashboard. Ask: if my agent had failed overnight, would I have seen it here this morning? If the answer is yes — ship it.