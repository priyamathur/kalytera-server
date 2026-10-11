"""Dashboard queries count sessions, not scored steps."""
from datetime import datetime, timedelta, timezone
from typing import Generator, Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from db.models import AgentLog, Base, EvalResult
from db.queries import (
    get_failures_by_step,
    get_pattern_sessions,
    get_session_failure_counts,
    get_session_steps,
    get_todays_stats,
    get_top_failure_types,
    search_sessions,
)

AGENT = "support-bot"


@pytest.fixture()
def db() -> Generator[Session, None, None]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _step(db: Session, sid: str, n: int, name: str, passed: bool, ftype: Optional[str] = None,
          reason: Optional[str] = None, agent: str = AGENT, minutes_ago: int = 5) -> None:
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    log_id = f"{agent}-{sid}-{n}"
    db.add(AgentLog(id=log_id, agent_id=agent, session_id=sid, step_number=n, step_name=name,
                    input="", output="", timestamp=ts))
    db.add(EvalResult(log_id=log_id, session_id=sid, agent_id=agent, accuracy=0.5, goal_alignment=0.5,
                      decision_quality=0.5, completeness=0.5, overall_score=0.9 if passed else 0.3,
                      passed=passed, failure_type=None if passed else ftype,
                      failure_step=None if passed else name, failure_reason=None if passed else reason,
                      evaluated_at=ts))


@pytest.fixture()
def seeded(db: Session) -> Session:
    # s1: two failing steps, both goal drift -> one session, not two
    _step(db, "s1", 1, "plan", False, "goal_drift", "Wandered off topic", minutes_ago=30)
    _step(db, "s1", 2, "reply", False, "goal_drift", "Wandered off topic", minutes_ago=29)
    # s2: one failing step
    _step(db, "s2", 1, "plan", False, "goal_drift", "Wandered off topic", minutes_ago=10)
    # s3, s4: passed every step
    _step(db, "s3", 1, "plan", True)
    _step(db, "s3", 2, "reply", True)
    _step(db, "s4", 1, "plan", True)
    # another agent's session with a clashing ID
    _step(db, "s1", 1, "plan", True, agent="other-bot")
    db.commit()
    return db


def test_session_failure_counts_are_distinct_sessions(seeded: Session) -> None:
    counts = get_session_failure_counts(AGENT, seeded)
    assert counts["total"] == 4
    assert counts["failure_type"] == {"goal_drift": 2}
    assert counts["workflow_step"] == {"plan": 2, "reply": 1}


def test_todays_stats_count_sessions(seeded: Session) -> None:
    stats = get_todays_stats(AGENT, seeded, hours=24)
    assert stats["total"] == 4
    assert stats["passed"] == 2
    assert stats["pass_rate"] == 0.5


def test_top_failure_types_count_sessions(seeded: Session) -> None:
    assert get_top_failure_types(AGENT, 24, seeded) == [("goal_drift", 2, 1.0)]


def test_failures_by_step_count_sessions(seeded: Session) -> None:
    rows = {name: (n, rate) for _, name, n, rate in get_failures_by_step(AGENT, 24, seeded)}
    assert rows["plan"] == (2, 0.5)     # 2 of the 4 sessions that reached step 1
    assert rows["reply"] == (1, 0.5)    # 1 of the 2 sessions that reached step 2


def test_pattern_sessions_one_row_per_session_newest_first(seeded: Session) -> None:
    rows = get_pattern_sessions(AGENT, "failure_type", "goal_drift", 10, seeded)
    assert [r["session_id"] for r in rows] == ["s2", "s1"]
    rows = get_pattern_sessions(AGENT, "workflow_step", "reply", 10, seeded)
    assert [r["session_id"] for r in rows] == ["s1"]
    assert get_pattern_sessions(AGENT, "failure_type", "goal_drift", 1, seeded)[0]["session_id"] == "s2"


def test_search_by_id_and_by_error_text(seeded: Session) -> None:
    exact = search_sessions([AGENT], "s3", 20, seeded)
    assert exact[0]["session_id"] == "s3" and exact[0]["failed"] is False
    by_text = search_sessions([AGENT], "off topic", 20, seeded)
    assert {r["session_id"] for r in by_text} == {"s1", "s2"}
    assert all(r["failed"] and r["failure_reason"] == "Wandered off topic" for r in by_text)
    assert search_sessions([AGENT], "", 20, seeded) == []
    assert search_sessions([AGENT], "nothing-like-this", 20, seeded) == []


def test_search_only_sees_given_agents(seeded: Session) -> None:
    rows = search_sessions(["other-bot"], "s", 20, seeded)
    assert [(r["session_id"], r["agent_id"]) for r in rows] == [("s1", "other-bot")]


def test_session_steps_scoped_to_agent(seeded: Session) -> None:
    assert len(get_session_steps("s1", seeded, agent_id=AGENT)) == 2
    assert len(get_session_steps("s1", seeded, agent_id="other-bot")) == 1
    steps = get_session_steps("s1", seeded, agent_id=AGENT)
    assert all(ev is not None and ev.agent_id == AGENT for _, ev in steps)
