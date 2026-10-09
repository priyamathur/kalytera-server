"""Tests for kalytera/checks.py and the `kalytera demo` bundled session."""
from kalytera.checks import find_loops, find_tool_failures, run_checks, tool_failure_reason
from kalytera.demo import DEMO_SESSION, run


def _step(n, name="s", output="o", tools=None):
    return {"step_number": n, "step_name": name, "output": output, "tool_calls": tools or []}


def test_tool_failure_reason_variants() -> None:
    assert tool_failure_reason({"name": "t", "error": "boom"}) == "boom"
    assert tool_failure_reason({"name": "t", "status": "TIMEOUT"}) == "timeout"
    assert tool_failure_reason({"name": "t", "status_code": 503}) == "HTTP 503"
    assert tool_failure_reason({"name": "t", "success": False}) == "success=False"
    assert tool_failure_reason({"name": "t", "success": True}) is None
    assert tool_failure_reason({"name": "t", "status": "ok"}) is None
    assert tool_failure_reason("not a dict") is None


def test_tool_failures_reported_once_per_tool_at_first_step() -> None:
    steps = [_step(1), _step(2, tools=[{"name": "api", "error": "x"}]), _step(3, tools=[{"name": "api", "error": "x"}])]
    findings = find_tool_failures(steps)
    assert len(findings) == 1
    assert findings[0].step_number == 2
    assert "2 failed calls" in findings[0].message


def test_loop_needs_three_identical_steps() -> None:
    assert find_loops([_step(1, "a"), _step(2, "a")]) == []
    findings = find_loops([_step(1, "a"), _step(2, "a"), _step(3, "a"), _step(4, "b")])
    assert len(findings) == 1 and "steps 1–3" in findings[0].message


def test_different_outputs_are_not_a_loop() -> None:
    assert find_loops([_step(1, "a", "x"), _step(2, "a", "y"), _step(3, "a", "z")]) == []


def test_demo_session_flags_step_3() -> None:
    findings = run_checks(DEMO_SESSION)
    assert {f.check for f in findings} == {"tool_failure", "loop"}
    assert all(f.step_number == 3 for f in findings)


def test_demo_runs_without_network(capsys) -> None:
    run()
    out = capsys.readouterr().out
    assert "payment_policy_api failed" in out
    assert "Where it broke: step 3" in out
