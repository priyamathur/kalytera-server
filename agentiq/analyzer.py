"""
agentiq/analyzer.py — hourly loss pattern detection job.
Runs after the judge; never in the trace path.

Public API:
  run_analysis(agent_id, db)  — detect patterns for one agent, write LossPattern rows
  run_all(db)                 — run for every agent with new EvalResults since last run
"""
import logging
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Generator, List, Optional, Tuple

logger = logging.getLogger(__name__)

MIN_FAILURE_COUNT = 5          # only surface patterns with ≥5 failures
ANALYSIS_WINDOW_DAYS = 7       # look back this many days for current failure rate
WORSENING_WINDOW_DAYS = 7      # compare current vs prior window to flag worsening


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_analysis(agent_id: str, db: Any) -> int:
    """
    Detect patterns for one agent and upsert LossPattern rows.
    Returns the number of patterns written. Idempotent.
    """
    from db.models import EvalResult

    start_time = datetime.now(timezone.utc)
    logger.info("[analyzer] start agent=%s", agent_id)

    all_failures = _fetch_failures(agent_id, db)
    total_evals = _count_total_evals(agent_id, db)
    total_failures = len(all_failures)

    if total_failures == 0:
        logger.info("[analyzer] done agent=%s failures=0 patterns=0", agent_id)
        return 0

    patterns_written = 0
    for ptype, pvalue, group in _group_failures(all_failures):
        if len(group) < MIN_FAILURE_COUNT:
            continue

        total_for_group = _total_for_group(ptype, pvalue, agent_id, total_evals, db)
        failure_rate = len(group) / total_for_group if total_for_group > 0 else 0.0
        pct_of_all = len(group) / total_failures if total_failures > 0 else 0.0
        root_cause = _most_common_reason(group)
        is_worsening = _check_worsening(ptype, pvalue, agent_id, db)

        _upsert_pattern(
            agent_id=agent_id,
            pattern_type=ptype,
            pattern_value=pvalue,
            failure_count=len(group),
            total_count=total_for_group,
            failure_rate=round(failure_rate, 4),
            pct_of_all_failures=round(pct_of_all, 4),
            root_cause=root_cause,
            is_worsening=is_worsening,
            first_seen=min(r.evaluated_at for r in group),
            last_seen=max(r.evaluated_at for r in group),
            db=db,
        )
        patterns_written += 1

    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    logger.info(
        "[analyzer] done agent=%s failures=%d patterns=%d elapsed=%.2fs",
        agent_id, total_failures, patterns_written, elapsed,
    )
    return patterns_written


def run_all(db: Any) -> Dict[str, int]:
    """
    Run pattern detection for every agent that has EvalResult rows.
    Returns {agent_id: patterns_written}.
    """
    from db.models import EvalResult

    start_time = datetime.now(timezone.utc)
    logger.info("[analyzer] run_all start")

    agent_ids: List[str] = [
        row[0] for row in db.query(EvalResult.agent_id).distinct().all()
    ]

    results: Dict[str, int] = {}
    for agent_id in agent_ids:
        try:
            results[agent_id] = run_analysis(agent_id, db)
        except Exception as exc:
            logger.error("[analyzer] agent=%s error: %s", agent_id, exc)
            results[agent_id] = 0

    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    logger.info(
        "[analyzer] run_all done agents=%d total_patterns=%d elapsed=%.2fs",
        len(agent_ids), sum(results.values()), elapsed,
    )
    return results


# ---------------------------------------------------------------------------
# Private helpers — pure functions (easy to test without DB)
# ---------------------------------------------------------------------------

def _group_failures(
    failures: List[Any],
) -> Generator[Tuple[str, str, List[Any]], None, None]:
    """
    Yield (pattern_type, pattern_value, group) for two pattern types:
      - workflow_step: grouped by failure_step
      - failure_type:  grouped by failure_type string
    """
    by_step: Dict[str, List[Any]] = {}
    by_type: Dict[str, List[Any]] = {}

    for row in failures:
        if row.failure_step is not None:
            key = f"step_{row.failure_step}"
            by_step.setdefault(key, []).append(row)
        if row.failure_type:
            by_type.setdefault(row.failure_type, []).append(row)

    for pvalue, group in by_step.items():
        yield "workflow_step", pvalue, group

    for pvalue, group in by_type.items():
        yield "failure_type", pvalue, group


def _most_common_reason(group: List[Any]) -> Optional[str]:
    """Return the most frequent non-empty failure_reason in the group."""
    reasons = [r.failure_reason for r in group if r.failure_reason]
    if not reasons:
        return None
    return Counter(reasons).most_common(1)[0][0]


def _check_worsening(
    pattern_type: str,
    pattern_value: str,
    agent_id: str,
    db: Any,
) -> bool:
    """
    Compare failure rate in current 7-day window vs prior 7-day window.
    Returns True if the current rate is higher (pattern is getting worse).
    """
    from db.models import EvalResult

    now = datetime.now(timezone.utc)
    current_start = now - timedelta(days=WORSENING_WINDOW_DAYS)
    prior_start = current_start - timedelta(days=WORSENING_WINDOW_DAYS)

    def failure_rate_in_window(start: datetime, end: datetime) -> float:
        total = (
            db.query(EvalResult)
            .filter(
                EvalResult.agent_id == agent_id,
                EvalResult.evaluated_at >= start,
                EvalResult.evaluated_at < end,
            )
            .count()
        )
        if total == 0:
            return 0.0
        failed = _count_group_in_window(pattern_type, pattern_value, agent_id, start, end, db)
        return failed / total

    current_rate = failure_rate_in_window(current_start, now)
    prior_rate = failure_rate_in_window(prior_start, current_start)
    return current_rate > prior_rate


def _count_group_in_window(
    pattern_type: str,
    pattern_value: str,
    agent_id: str,
    start: datetime,
    end: datetime,
    db: Any,
) -> int:
    from db.models import EvalResult

    q = (
        db.query(EvalResult)
        .filter(
            EvalResult.agent_id == agent_id,
            EvalResult.passed == False,  # noqa: E712
            EvalResult.evaluated_at >= start,
            EvalResult.evaluated_at < end,
        )
    )
    if pattern_type == "workflow_step":
        step_num = int(pattern_value.split("_")[1])
        q = q.filter(EvalResult.failure_step == step_num)
    elif pattern_type == "failure_type":
        q = q.filter(EvalResult.failure_type == pattern_value)
    return q.count()


def _upsert_pattern(
    *,
    agent_id: str,
    pattern_type: str,
    pattern_value: str,
    failure_count: int,
    total_count: int,
    failure_rate: float,
    pct_of_all_failures: float,
    root_cause: Optional[str],
    is_worsening: bool,
    first_seen: datetime,
    last_seen: datetime,
    db: Any,
) -> None:
    from db.models import LossPattern

    existing = (
        db.query(LossPattern)
        .filter(
            LossPattern.agent_id == agent_id,
            LossPattern.pattern_type == pattern_type,
            LossPattern.pattern_value == pattern_value,
        )
        .first()
    )

    if existing is not None:
        existing.failure_count = failure_count
        existing.total_count = total_count
        existing.failure_rate = failure_rate
        existing.pct_of_all_failures = pct_of_all_failures
        existing.root_cause = root_cause
        existing.is_worsening = is_worsening
        existing.last_seen = last_seen
        # first_seen is immutable once set
    else:
        db.add(LossPattern(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            pattern_type=pattern_type,
            pattern_value=pattern_value,
            failure_count=failure_count,
            total_count=total_count,
            failure_rate=failure_rate,
            pct_of_all_failures=pct_of_all_failures,
            root_cause=root_cause,
            is_worsening=is_worsening,
            first_seen=first_seen,
            last_seen=last_seen,
        ))

    db.commit()


def _fetch_failures(agent_id: str, db: Any) -> List[Any]:
    from db.models import EvalResult

    return (
        db.query(EvalResult)
        .filter(
            EvalResult.agent_id == agent_id,
            EvalResult.passed == False,  # noqa: E712
            EvalResult.eval_error == False,  # noqa: E712
        )
        .all()
    )


def _count_total_evals(agent_id: str, db: Any) -> int:
    from db.models import EvalResult

    return db.query(EvalResult).filter(EvalResult.agent_id == agent_id).count()


def _total_for_group(
    pattern_type: str,
    pattern_value: str,
    agent_id: str,
    total_evals: int,
    db: Any,
) -> int:
    from db.models import EvalResult

    if pattern_type == "failure_type":
        return total_evals
    if pattern_type == "workflow_step":
        step_num = int(pattern_value.split("_")[1])
        return (
            db.query(EvalResult)
            .filter(
                EvalResult.agent_id == agent_id,
                EvalResult.failure_step == step_num,
            )
            .count()
            or total_evals
        )
    return total_evals
