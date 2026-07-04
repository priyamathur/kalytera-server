# Kalytera — How It Works

> **Audience:** Investors, developers evaluating Kalytera, design partners.
> This diagram deliberately omits implementation details — model names, table schemas,
> queue mechanics, retry logic, and all internal code. The moat lives below this layer.
> Edit this file freely — it is a Mermaid diagram in plain Markdown.

```mermaid
flowchart LR
    subgraph AGENT["Your AI Agent"]
        A["Any framework\nLangChain · CrewAI · Custom build\nNo rebuilding required"]
    end

    subgraph KALYTERA["Kalytera — The Quality Layer"]
        B["Step 1 — Connect\nOne line of code.\nKalytera starts observing immediately.\nIf Kalytera goes down, your agent keeps running."]
        C["Step 2 — Score\nEvery interaction evaluated in real time.\nQuality defined by your industry, refined by you.\nNothing sampled. Nothing missed."]
        D["Step 3 — Surface\nLoss patterns appear as they form.\nRoot cause in plain English.\nFeedback loop closes automatically."]
    end

    subgraph INSIGHTS["What You See"]
        E["Quality score per interaction\n0–100, calibrated to your industry\nHealthcare · Retail · Coding · Marketing"]
        F["Loss patterns with root cause\n'Billing disputes failing 47% of the time\nbecause payment API times out at step 3'\nNot 'your error rate is 23%'"]
        G["Feedback loop\nEvery confirmed failure feeds\nthe next improvement cycle.\nAgents get better without a code push."]
    end

    AGENT -->|"kalytera.trace()\nfire and forget"| B
    B --> C --> D
    D --> E & F & G
```

## Three things no existing tool does together

| | LangSmith | Braintrust | Maxim | **Kalytera** |
|--|-----------|------------|-------|-------------|
| 100% coverage — nothing sampled | Samples | Samples | Samples | **Yes** |
| Loss patterns surface automatically | No | No | Partial | **Yes** |
| Feedback loop — same failures don't repeat | No | No | No | **Yes** |
| Industry quality standards out of the box | No | No | No | **Yes** |

## The three-step developer experience

```
# Step 1 — one line of code
kalytera.trace(session_id=..., user_input=..., agent_response=..., response_time_ms=...)

# Step 2 — quality scores appear in the dashboard within 30 seconds

# Step 3 — loss patterns surface with root cause as they form
# "Billing disputes fail 47% of the time because payment API times out at step 3"
# Happening since last Tuesday. 23 sessions affected.
```

## What developers fix in minutes, not hours

Before Kalytera: "The agent has a 23% failure rate."
After Kalytera: "Billing disputes fail because the payment API times out at step 3. Happening since last Tuesday. Here's the fix."
