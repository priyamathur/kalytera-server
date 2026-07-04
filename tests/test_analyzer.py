"""Tests for kalytera/analyzer.py — pattern detection logic."""
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional
from unittest.mock import MagicMock, patch, call

import pytest

from kalytera.analyzer import (
    MIN_FAILURE_COUNT,
    _check_worsening,
    _group_failures,
    _most_common_reason,
    run_analysis,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _eval(
    *,
    failure_step: Optional[int] = None,
    failure_type: Optional[str] = None,
    failure_reason: Optional[str] = None,
    passed: bool = False,
    eval_error: bool = False,
    agent_id: str = "agent-1",
    evaluated_at: Optional[datetime] = None,
) -> MagicMock:
    row = MagicMock()
    row.failure_step = failure_step
    row.failure_type = failure_type
    row.failure_reason = failure_reason
    row.passed = passed
    row.eval_error = eval_error
    row.agent_id = agent_id
    row.evaluated_at = evaluated_at or _now()
    return row


def _make_failures(
    n: int,
    failure_step: int = 3,
    failure_type: str = "tool_failure",
    failure_reason: str = "Payment API timed out at step 3.",
) -> List[MagicMock]:
    return [
        _eval(failure_step=failure_step, failure_type=failure_type, failure_reason=failure_reason)
        for _ in range(n)
    ]


def _mock_db(
    failures: Optional[List[MagicMock]] = None,
    total_evals: int = 100,
    step_evals: int = 20,
    current_window_total: int = 50,
    prior_window_total: int = 50,
    current_window_fails: int = 5,
    prior_window_fails: int = 3,
) -> MagicMock:
    """Build a mock SQLAlchemy Session for analyzer tests."""
    db = MagicMock()
    failures = failures or []

    def query_side_effect(model: Any) -> MagicMock:
        q = MagicMock()
        q.filter.return_value = q
        q.distinct.return_value = q
        q.all.return_value = failures
        # count() varies by call context — default to total_evals
        q.count.return_value = total_evals
        return q

    db.query.side_effect = query_side_effect
    db.commit = MagicMock()
    db.add = MagicMock()
    return db


# ---------------------------------------------------------------------------
# _group_failures
# ---------------------------------------------------------------------------

def test_group_failures_by_step() -> None:
    rows = _make_failures(3, failure_step=3) + _make_failures(2, failure_step=5)
    groups = list(_group_failures(rows))
    step_groups = {pv: g for pt, pv, g in groups if pt == "workflow_step"}
    assert "step_3" in step_groups
    assert len(step_groups["step_3"]) == 3
    assert "step_5" in step_groups
    assert len(step_groups["step_5"]) == 2


def test_group_failures_by_type() -> None:
    rows = _make_failures(4, failure_type="tool_failure") + _make_failures(2, failure_type="context_loss")
    groups = list(_group_failures(rows))
    type_groups = {pv: g for pt, pv, g in groups if pt == "failure_type"}
    assert "tool_failure" in type_groups
    assert len(type_groups["tool_failure"]) == 4
    assert "context_loss" in type_groups


def test_group_failures_skips_none_step() -> None:
    rows = [_eval(failure_step=None, failure_type="tool_failure")]
    groups = list(_group_failures(rows))
    step_groups = [(pt, pv) for pt, pv, _ in groups if pt == "workflow_step"]
    assert len(step_groups) == 0


def test_group_failures_skips_none_type() -> None:
    rows = [_eval(failure_step=2, failure_type=None)]
    groups = list(_group_failures(rows))
    type_groups = [(pt, pv) for pt, pv, _ in groups if pt == "failure_type"]
    assert len(type_groups) == 0


def test_group_failures_both_dimensions() -> None:
    rows = _make_failures(6, failure_step=3, failure_type="tool_failure")
    groups = list(_group_failures(rows))
    types = {pt for pt, _, _ in groups}
    assert "workflow_step" in types
    assert "failure_type" in types


# ---------------------------------------------------------------------------
# _most_common_reason
# ---------------------------------------------------------------------------

def test_most_common_reason_returns_most_frequent() -> None:
    rows = (
        [_eval(failure_reason="API timeout at step 3.")] * 4
        + [_eval(failure_reason="Wrong product category used.")] * 2
    )
    assert _most_common_reason(rows) == "API timeout at step 3."


def test_most_common_reason_empty_reasons() -> None:
    rows = [_eval(failure_reason=None), _eval(failure_reason="")]
    assert _most_common_reason(rows) is None


def test_most_common_reason_single() -> None:
    rows = [_eval(failure_reason="Policy applied to wrong region.")]
    assert _most_common_reason(rows) == "Policy applied to wrong region."


# ---------------------------------------------------------------------------
# _check_worsening
# ---------------------------------------------------------------------------

def _db_for_worsening(current_fails: int, prior_fails: int, window_total: int = 50) -> MagicMock:
    """Mock DB that returns different failure counts for current vs prior windows."""
    db = MagicMock()
    call_count = {"n": 0}

    def make_q(total: int, fails: int) -> MagicMock:
        q = MagicMock()
        q.filter.return_value = q
        q.count.return_value = total
        return q

    # Each call to db.query() is for a different sub-query.
    # We cycle: total_current, fails_current, total_prior, fails_prior
    totals = [window_total, current_fails, window_total, prior_fails]

    def query_side(*args: Any) -> MagicMock:
        n = call_count["n"] % len(totals)
        call_count["n"] += 1
        q = MagicMock()
        q.filter.return_value = q
        q.count.return_value = totals[n]
        return q

    db.query.side_effect = query_side
    return db


def test_check_worsening_true_when_rate_increases() -> None:
    # current: 10/50 = 0.20, prior: 3/50 = 0.06 → worsening
    db = _db_for_worsening(current_fails=10, prior_fails=3, window_total=50)
    assert _check_worsening("failure_type", "tool_failure", "agent-1", db) is True


def test_check_worsening_false_when_rate_drops() -> None:
    # current: 2/50 = 0.04, prior: 10/50 = 0.20 → improving
    db = _db_for_worsening(current_fails=2, prior_fails=10, window_total=50)
    assert _check_worsening("failure_type", "tool_failure", "agent-1", db) is False


def test_check_worsening_false_when_no_prior_data() -> None:
    # prior window has 0 total evals — rate 0.0 vs 0.0 → not worsening
    db = _db_for_worsening(current_fails=0, prior_fails=0, window_total=0)
    assert _check_worsening("failure_type", "tool_failure", "agent-1", db) is False


# ---------------------------------------------------------------------------
# run_analysis — end-to-end with mock DB
# ---------------------------------------------------------------------------

def _db_for_analysis(failures: List[MagicMock], total_evals: int = 100) -> MagicMock:
    db = MagicMock()

    existing_pattern = MagicMock()
    existing_pattern.failure_count = 0

    call_count = {"n": 0}

    def query_side(model: Any) -> MagicMock:
        from db.models import EvalResult, LossPattern
        q = MagicMock()
        q.filter.return_value = q
        q.distinct.return_value = q
        q.first.return_value = None          # no existing LossPattern
        q.all.return_value = failures
        q.count.return_value = total_evals
        return q

    db.query.side_effect = query_side
    db.commit = MagicMock()
    db.add = MagicMock()
    return db


def test_run_analysis_no_failures_returns_zero() -> None:
    db = _db_for_analysis(failures=[])
    result = run_analysis("agent-1", db)
    assert result == 0
    db.add.assert_not_called()


def test_run_analysis_below_min_threshold_no_patterns() -> None:
    failures = _make_failures(MIN_FAILURE_COUNT - 1, failure_step=3, failure_type="tool_failure")
    db = _db_for_analysis(failures)
    result = run_analysis("agent-1", db)
    assert result == 0


def test_run_analysis_writes_pattern_when_threshold_met() -> None:
    failures = _make_failures(MIN_FAILURE_COUNT, failure_step=3, failure_type="tool_failure")
    db = _db_for_analysis(failures, total_evals=50)
    result = run_analysis("agent-1", db)
    assert result >= 1
    db.add.assert_called()  # at least one LossPattern row added


def test_run_analysis_writes_both_step_and_type_patterns() -> None:
    failures = _make_failures(MIN_FAILURE_COUNT + 2, failure_step=3, failure_type="tool_failure")
    db = _db_for_analysis(failures, total_evals=100)
    result = run_analysis("agent-1", db)
    # One workflow_step pattern + one failure_type pattern
    assert result == 2


def test_run_analysis_pct_of_all_failures_correct() -> None:
    """10 step_3 failures out of 10 total = 100% pct_of_all_failures."""
    failures = _make_failures(10, failure_step=3, failure_type="tool_failure")
    written: List[Any] = []

    db = MagicMock()

    def query_side(model: Any) -> MagicMock:
        q = MagicMock()
        q.filter.return_value = q
        q.first.return_value = None
        q.all.return_value = failures
        q.count.return_value = 100
        return q

    db.query.side_effect = query_side
    db.add.side_effect = lambda obj: written.append(obj)
    db.commit = MagicMock()

    run_analysis("agent-1", db)

    pcts = [obj.pct_of_all_failures for obj in written]
    # Both step_3 and tool_failure group contain all 10 failures → pct = 1.0
    assert all(p == 1.0 for p in pcts)


def test_run_analysis_root_cause_from_most_common_reason() -> None:
    failures = (
        [_eval(failure_step=3, failure_type="tool_failure",
               failure_reason="Billing API returned 500.")] * 7
        + [_eval(failure_step=3, failure_type="tool_failure",
                 failure_reason="Timeout on billing API.")] * 3
    )
    written: List[Any] = []

    db = MagicMock()

    def query_side(model: Any) -> MagicMock:
        q = MagicMock()
        q.filter.return_value = q
        q.first.return_value = None
        q.all.return_value = failures
        q.count.return_value = 100
        return q

    db.query.side_effect = query_side
    db.add.side_effect = lambda obj: written.append(obj)
    db.commit = MagicMock()

    run_analysis("agent-1", db)

    root_causes = [obj.root_cause for obj in written]
    assert all(rc == "Billing API returned 500." for rc in root_causes)


def test_run_analysis_upserts_existing_pattern() -> None:
    """When a LossPattern row already exists, it's updated not duplicated."""
    failures = _make_failures(MIN_FAILURE_COUNT, failure_step=3, failure_type="tool_failure")

    existing = MagicMock()

    db = MagicMock()

    def query_side(model: Any) -> MagicMock:
        q = MagicMock()
        q.filter.return_value = q
        q.first.return_value = existing   # simulate existing row
        q.all.return_value = failures
        q.count.return_value = 100
        return q

    db.query.side_effect = query_side
    db.add = MagicMock()
    db.commit = MagicMock()

    run_analysis("agent-1", db)

    # add() should not be called since we updated the existing row
    db.add.assert_not_called()
    # The existing mock should have its attributes updated
    assert existing.failure_count == MIN_FAILURE_COUNT
