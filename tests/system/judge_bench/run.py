"""Compare judge models on the labelled cases.

usage: python tests/system/judge_bench/run.py 5.5-low [4.5 5.5-nothink]  (~$0.05 a run)   (reads ANTHROPIC_API_KEY from env or kalytera-server/.env; never prints it)
"""
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SERVER = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(Path(__file__).parent))

if not os.getenv("ANTHROPIC_API_KEY"):
    env = SERVER / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
if not os.getenv("ANTHROPIC_API_KEY"):
    sys.exit("No ANTHROPIC_API_KEY in env or kalytera-server/.env")

import anthropic  # noqa: E402

import kalytera.judge as judge  # noqa: E402
from kalytera.prompts import StepContext, system_prompt  # noqa: E402
from cases import CASES  # noqa: E402

RUNS = int(os.getenv("RUNS", "2"))
PRICES = {"4.5": (1.0, 5.0), "5.5-nothink": (0.10, 0.50), "5.5-low": (0.10, 0.50)}  # $/M in, out
_local = threading.local()
usage = {"in": 0, "out": 0, "cache_read": 0, "calls": 0}
lock = threading.Lock()


CONFIGS = {
    "4.5": ("claude-haiku-4-5-20251001", {}, 512),
    "5.5-nothink": ("claude-haiku-5-5", {"thinking": {"type": "disabled"}}, 512),
    "5.5-low": ("claude-haiku-5-5", {"thinking": {"type": "adaptive"}, "output_config": {"effort": "low"}}, 1500),
}


def _call(messages):
    client = anthropic.Anthropic()
    model, extra, max_tokens = CONFIGS[_local.model]
    r = client.messages.create(model=model, max_tokens=max_tokens,
                               system=[{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}],
                               messages=messages, **extra)
    with lock:
        u = r.usage
        usage["in"] += u.input_tokens + (u.cache_creation_input_tokens or 0)
        usage["cache_read"] += u.cache_read_input_tokens or 0
        usage["out"] += u.output_tokens
        usage["calls"] += 1
    return "".join(b.text for b in r.content if b.type == "text")


judge._call_judge = _call


def steps_for(case):
    return [StepContext(step_number=i + 1, step_name=f"turn {i + 1}", input=t["user"], output=t["assistant"],
                        tool_calls=t["actions"]) for i, t in enumerate(case["turns"])]


def one(model, case):
    _local.model = model
    r = judge.score_session(steps_for(case))
    return {"id": case["id"], "label": case["label"], "types": case.get("types", []),
            "passed": r.get("passed"), "failure_type": r.get("failure_type"), "score": r.get("overall_score"),
            "reason": (r.get("failure_reason") or "")[:160]}


def bench(model):
    for k in usage:
        usage[k] = 0
    jobs = [(model, c) for c in CASES for _ in range(RUNS)]
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda j: one(*j), jobs))
    n = len(res)
    correct = sum((r["passed"] is True) == (r["label"] == "pass") for r in res)
    fails = [r for r in res if r["label"] == "fail"]
    passes = [r for r in res if r["label"] == "pass"]
    caught = sum(r["passed"] is False for r in fails)
    false_alarm = sum(r["passed"] is False for r in passes)
    type_ok = sum(r["passed"] is False and r["failure_type"] in r["types"] for r in fails)
    errors = sum(r["passed"] is None for r in res)
    # stability: same verdict in every run of a case
    by = {}
    for r in res:
        by.setdefault(r["id"], set()).add(r["passed"])
    unstable = [k for k, v in by.items() if len(v) > 1]
    pin, pout = PRICES.get(model, (0, 0))
    cost = (usage["in"] * pin + usage["cache_read"] * pin * 0.1 + usage["out"] * pout) / 1e6
    summary = {
        "model": model, "verdicts": n, "accuracy": round(correct / n, 3),
        "mistakes_caught": f"{caught}/{len(fails)}", "false_alarms": f"{false_alarm}/{len(passes)}",
        "right_failure_type": f"{type_ok}/{len(fails)}", "errors": errors, "unstable_cases": unstable,
        "cost_per_conversation_usd": round(cost / max(usage['calls'], 1), 6),
        "avg_tokens_in": usage["in"] // max(usage["calls"], 1) + usage["cache_read"] // max(usage["calls"], 1),
        "avg_tokens_out": usage["out"] // max(usage["calls"], 1),
    }
    wrong = [r for r in res if (r["passed"] is True) != (r["label"] == "pass")]
    return summary, wrong


if __name__ == "__main__":
    out = {}
    for m in sys.argv[1:]:
        s, wrong = bench(m)
        out[m] = {"summary": s, "wrong": wrong}
        print(json.dumps(s, indent=1))
        for w in wrong:
            print("  WRONG", w["id"], "label", w["label"], "-> passed", w["passed"], w["failure_type"], "|", w["reason"])
    (Path(__file__).parent / "results.json").write_text(json.dumps(out, indent=1))
