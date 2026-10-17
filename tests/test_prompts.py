"""Tests for kalytera/prompts.py — judge prompt construction."""
import json

from kalytera.prompts import (
    build_session_prompt,
    EXPECTED_KEYS,
    FAILURE_TYPES,
    StepContext,
    build_prompt,
    build_retry_prompt,
    system_prompt,
)


def _make_step(n: int = 1, name: str = "retrieve_policy") -> StepContext:
    return StepContext(
        step_number=n,
        step_name=name,
        input="What is the refund policy?",
        output="The refund window is 30 days.",
    )


# --- system_prompt ---

def test_system_prompt_is_nonempty() -> None:
    assert len(system_prompt()) > 20


def test_system_prompt_mentions_json() -> None:
    assert "JSON" in system_prompt()


# --- build_prompt structure ---

def test_build_prompt_returns_messages_list() -> None:
    msgs = build_prompt(_make_step(), prior_steps=[])
    assert isinstance(msgs, list)
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"


def test_build_prompt_content_is_string() -> None:
    msgs = build_prompt(_make_step(), prior_steps=[])
    assert isinstance(msgs[0]["content"], str)
    assert len(msgs[0]["content"]) > 50


def test_build_prompt_contains_step_name() -> None:
    step = _make_step(name="apply_refund_policy")
    msgs = build_prompt(step, prior_steps=[])
    assert "apply_refund_policy" in msgs[0]["content"]


def test_build_prompt_contains_input_and_output() -> None:
    step = _make_step()
    msgs = build_prompt(step, prior_steps=[])
    content = msgs[0]["content"]
    assert step.input in content
    assert step.output in content


def test_build_prompt_contains_json_template() -> None:
    msgs = build_prompt(_make_step(), prior_steps=[])
    content = msgs[0]["content"]
    # All expected keys must appear in the template
    for key in EXPECTED_KEYS:
        assert key in content, f"JSON template missing key: {key}"


def test_build_prompt_contains_failure_types() -> None:
    msgs = build_prompt(_make_step(), prior_steps=[])
    content = msgs[0]["content"]
    for ft in FAILURE_TYPES:
        assert ft in content, f"Prompt missing failure type: {ft}"


# --- prior context ---

def test_build_prompt_no_prior_shows_none() -> None:
    msgs = build_prompt(_make_step(), prior_steps=[])
    assert "(none)" in msgs[0]["content"]


def test_build_prompt_prior_steps_included() -> None:
    prior = [_make_step(n=1, name="fetch_order"), _make_step(n=2, name="check_status")]
    msgs = build_prompt(_make_step(n=3, name="apply_policy"), prior_steps=prior)
    content = msgs[0]["content"]
    assert "fetch_order" in content
    assert "check_status" in content


def test_build_prompt_uses_only_last_3_prior_steps() -> None:
    prior = [_make_step(n=i, name=f"step_{i}") for i in range(1, 6)]  # 5 steps
    msgs = build_prompt(_make_step(n=6), prior_steps=prior)
    content = msgs[0]["content"]
    # step_1 and step_2 should be dropped; step_3/4/5 kept
    assert "step_3" in content
    assert "step_5" in content
    assert "step_1" not in content
    assert "step_2" not in content


# --- tool calls ---

def test_build_prompt_no_tool_calls_shows_none() -> None:
    step = StepContext(1, "fetch", "q", "a", tool_calls=[])
    msgs = build_prompt(step, prior_steps=[])
    assert "none" in msgs[0]["content"]


def test_build_prompt_tool_calls_formatted() -> None:
    step = StepContext(
        1, "call_api", "q", "a",
        tool_calls=[
            {"name": "payment_api", "success": True},
            {"name": "billing_db", "success": False},
        ],
    )
    msgs = build_prompt(step, prior_steps=[])
    content = msgs[0]["content"]
    assert "payment_api() ok" in content
    assert "billing_db() FAILED: no detail" in content


def test_session_prompt_shows_what_each_action_was_given_and_returned() -> None:
    """Without these the judge can't see a $450 refund for a $45 request, or a reply the result contradicts."""
    steps = [StepContext(1, "turn 1", "Refund the $45 fee on E5", "Refunded.", tool_calls=[
        {"name": "refund_api", "input": {"order_id": "E5", "amount": 450}, "output": '{"refunded": 450}',
         "success": True},
        *[{"name": "check_stock", "input": {"sku": "551"}, "success": False, "error": "timeout"}] * 3,
        {"name": "send_money", "input": {"amount": 900}, "success": False, "blocked": "DENY",
         "rule_id": "cap", "error": "over limit"},
    ])]
    content = build_session_prompt(steps)[0]["content"]
    assert 'refund_api({"order_id": "E5", "amount": 450}) ok -> {"refunded": 450}' in content
    assert 'check_stock({"sku": "551"}) FAILED: timeout  [repeated 3 times]' in content
    assert "BLOCKED by rule cap: over limit" in content
    long = [StepContext(1, "t", "q", "a", tool_calls=[{"name": "x", "input": {"blob": "y" * 5000}, "success": True}])]
    assert "more characters]" in build_session_prompt(long)[0]["content"]  # big payloads are clipped


# --- retry prompt ---

def test_build_retry_prompt_returns_messages_list() -> None:
    msgs = build_retry_prompt(_make_step())
    assert isinstance(msgs, list)
    assert msgs[0]["role"] == "user"


def test_build_retry_prompt_is_shorter_than_full_prompt() -> None:
    step = _make_step()
    full = build_prompt(step, prior_steps=[])
    retry = build_retry_prompt(step)
    assert len(retry[0]["content"]) < len(full[0]["content"])


def test_build_retry_prompt_contains_expected_keys() -> None:
    msgs = build_retry_prompt(_make_step())
    content = msgs[0]["content"]
    for key in EXPECTED_KEYS:
        assert key in content, f"Retry prompt missing key: {key}"


# --- constants ---

def test_failure_types_count() -> None:
    assert len(FAILURE_TYPES) == 7


def test_expected_keys_count() -> None:
    assert len(EXPECTED_KEYS) == 12


def test_all_seven_failure_types_present() -> None:
    expected = {
        "wrong_answer", "tool_failure", "goal_drift", "incomplete",
        "hallucination", "context_loss", "loop",
    }
    assert FAILURE_TYPES == expected
