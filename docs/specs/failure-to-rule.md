# Kalytera: Failure-to-Rule Loop (v0 build spec)

## Decisions (confirmed 2026-10-10)

- Default failure mode: **fail open**. A rule may opt into `fail_closed: true`.
- Who can promote a rule: **any admin on the account**.
- Shadow-mode events do **not** count against the session limit (provisional; revisit with pricing).

## Goal

A failure pattern that Kalytera detects in production becomes a reviewed rule that blocks the same kind of action before it runs. Rules start in shadow mode, where they log what they would have blocked and never change agent behavior. A human promotes a rule to enforce mode.

## Non-goals for v0

- No LLM call on the hot path. The judge stays asynchronous and scores after the fact.
- No auto-generated rules that take effect without human review.
- No security or compliance claims in code, docs, or copy.
- No multi-agent delegation rules.
- No stateful rules beyond simple count-in-window conditions.

## Current state (what exists today)

- `trace()` sends steps to the server in the background and never blocks. It returns `None`.
- Scoring runs after the session ends. Results are written to `EvalResult` and grouped into `LossPattern` by `analyzer.py`, which runs hourly.
- There is no check that runs before a tool call. The dashboard is the only place failures surface.

## The loop

1. **Detect.** `LossPattern` already groups failures by `pattern_type` (intent, workflow_step, or tool_call) and `pattern_value`. Example: `tool_call = refund_api`, failing at step 3.

2. **Propose.** The dashboard shows each pattern with a draft rule built from the arguments of the failing calls. For example, if failures cluster on `amount > 500`, the draft proposes that predicate. The user edits the draft. Nothing is saved without a human action.

3. **Rule format.** Declarative JSON:

```json
{
  "id": "rule_refund_cap",
  "agent_id": "billing-agent",
  "version": 1,
  "match": {
    "tool": "refund_api",
    "args": [{"field": "amount", "op": ">", "value": 500}]
  },
  "session_conditions": [{"type": "count_in_window", "tool": "refund_api", "op": ">=", "value": 3, "window_seconds": 600}],
  "action": "DENY",
  "mode": "shadow",
  "reason": "Refunds over 500 need review"
}
```

   Allowed predicate operators in v0: `==`, `!=`, `>`, `>=`, `<`, `<=`, `in`. Allowed session conditions in v0: `count_in_window`. Nothing else.

4. **Enforce.** Two entry points:
   - `kalytera.guard(tool, args, session_id) -> Decision` in the Python SDK, where `Decision` is `ALLOW`, `DENY`, or `ESCALATE`, with `rule_id` and `reason`.
   - `POST /guard` on the API, for non-Python callers.

   Rules are evaluated in-process from a cache per `agent_id`, refreshed every 30 seconds. Evaluation is local and does not call the API on each check.

5. **Shadow.** In shadow mode, `guard()` returns `ALLOW` and logs a `would_block` event with `rule_id`, `rule_version`, args hash, and session id. The agent proceeds unchanged. The dashboard shows a count of `would_block` events per rule. After the outcome judge labels those sessions, the dashboard also shows how many of the would-blocks were on sessions that actually failed.

6. **Promote.** A rule moves from shadow to enforce only when a human clicks Promote. The promote screen shows the shadow summary. Promotion creates a new rule version. Demotion works the same way.

7. **Audit.** Every decision is traced with `rule_id`, `rule_version`, `mode`, decision, and timestamp. The existing `AgentLog` remains the record of what happened.

## Behavior that must hold

- `guard()` adds under 5 ms at p99 when rules are cached, measured locally.
- A rule in enforce mode returns `DENY` for a matching call. A test covers this.
- A rule in shadow mode never changes the return value seen by the agent. A test covers this.
- If the Kalytera API is unreachable, `guard()` falls back to the cached rules and the default decision. A test kills the API and checks this.
- Every `guard()` call, including on error, produces a trace event.

## Build order

1. Rule schema, in-process evaluator, and unit tests for each operator and for `count_in_window`.
2. `guard()` in the SDK with shadow logging and fail-open fallback.
3. `POST /guard` on the API, reusing the same evaluator.
4. Rules view on the dashboard: list, create, edit, shadow counts.
5. Pattern-to-draft-rule on the existing Failure Feed.
6. Promote and demote flow with versioning.

## Known risk

Shadow mode produces the data that decides whether a rule is safe to enforce, but it only works with real installs. Nobody can run shadow mode if nobody installs Kalytera. Build the loop and the install path together, and treat the first ten installs as the test of the whole product.
