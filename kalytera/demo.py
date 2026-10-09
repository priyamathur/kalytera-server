"""
`kalytera demo` — runs a bundled billing-agent session through Kalytera's
deterministic checks locally. No API key, no network.
"""
from typing import Any, Dict, List

from kalytera.checks import run_checks, tool_failure_reason

DEMO_SESSION: List[Dict[str, Any]] = [
    {
        "step_number": 1, "step_name": "classify_intent",
        "input": "I was charged twice for my March invoice. Can I get a refund?",
        "output": "intent=billing_dispute", "tool_calls": [],
    },
    {
        "step_number": 2, "step_name": "lookup_customer",
        "input": "customer_id=4821",
        "output": "Pro plan · 2 charges of $49 on 2026-03-03",
        "tool_calls": [{"name": "crm.get_customer", "status": "ok"}],
    },
    *[
        {
            "step_number": n, "step_name": "check_refund_policy",
            "input": "policy for duplicate charge, Pro plan",
            "output": "No response from payment_policy_api — retrying",
            "tool_calls": [{"name": "payment_policy_api", "status": "timeout", "error": "timed out after 10s"}],
        }
        for n in (3, 4, 5)
    ],
    {
        "step_number": 6, "step_name": "respond",
        "input": "draft reply to customer",
        "output": "Good news — your duplicate charge has been refunded. You'll see it in 3–5 days.",
        "tool_calls": [],
    },
]


def run() -> None:
    findings = run_checks(DEMO_SESSION)
    flagged = {
        n for f in findings for n in range(f.step_number, max(f.last_step, f.step_number) + 1)
    } | {
        s["step_number"] for s in DEMO_SESSION
        if any(tool_failure_reason(c) for c in s["tool_calls"])
    }

    print("Kalytera demo — billing-agent session (bundled, runs locally, no API key)\n")
    for step in DEMO_SESSION:
        mark = "✗" if step["step_number"] in flagged else "·"
        print(f"  {mark} step {step['step_number']}  {step['step_name']:<20} {step['output'][:60]}")

    print("  (✗ = flagged by deterministic checks · = not flagged; correctness needs the LLM judge)")
    print("\nFindings (deterministic checks):")
    for f in findings:
        print(f"  • step {f.step_number} [{f.check}] {f.message}")

    if findings:
        first = findings[0]
        print(f"\nWhere it broke: step {first.step_number} ({first.step_name}). "
              "The policy API timed out and the agent retried it with no fallback.")
        print("Step 6 then told the customer the refund went through, although the policy check never succeeded.")
        print("Catching that false claim needs the LLM judge, which scores every step on six dimensions\n"
              "on the Kalytera server once you add an API key.")

    print("\nNext:")
    print("  1. Get a free API key at https://kalytera.dev")
    print("  2. kalytera.configure(api_key='kly_live_...', agent_id='my-agent')")
    print("  3. kalytera.check()   # confirms your first step is recorded and scored")
