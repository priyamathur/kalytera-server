"""
agentiq/dashboard.py — three views per agentiq-dashboard-spec.md
Run: streamlit run agentiq/dashboard.py --server.port 8501
"""
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from db.queries import (
    get_all_agent_ids,
    get_failures_by_step,
    get_patterns_for_agent,
    get_quality_trend,
    get_recent_eval_failures,
    get_recent_failing_sessions,
    get_session_and_latency_stats,
    get_session_steps,
    get_todays_stats,
    get_top_failure_types,
)

AUTO_REFRESH_SECONDS = 30
TREND_DAYS = 7
SESSION_BROWSER_LIMIT = 100
ALL_FAILURE_TYPES = [
    "tool_failure", "wrong_answer", "goal_drift",
    "incomplete", "hallucination", "context_loss", "loop",
]

# One-sentence fix per failure type — used in Overview action items and Feed cards
_FIXES: Dict[str, str] = {
    "tool_failure":  "Add retry logic with exponential backoff and a graceful fallback for every external API/tool call.",
    "wrong_answer":  "Audit the context injected before each step — the agent is contradicting the available data.",
    "goal_drift":    "Add a goal-alignment check at each decision point to abort if the agent drifts from the user's intent.",
    "hallucination": "Require the agent to cite a specific retrieved fact before asserting anything.",
    "context_loss":  "Verify conversation history is passed at every step; keep at least the last 3 exchanges.",
    "incomplete":    "Add a completion checklist at session end to verify every part of the request was addressed.",
    "loop":          "Track actions in a session set — if the same action appears 3× without progress, break and escalate.",
}

_FIX_STEP_TEMPLATE: Dict[str, str] = {
    "tool_failure": "Add retry/fallback to **{step}**.",
    "wrong_answer": "Fix context injection before **{step}**.",
    "goal_drift": "Add goal check before **{step}**.",
    "hallucination": "Require citations at **{step}**.",
    "context_loss": "Inject history correctly into **{step}**.",
    "incomplete": "Add completion check after **{step}**.",
    "loop": "Add repetition guard before **{step}**.",
}


def _fix_one_line(failure_type: Optional[str], step_name: str) -> str:
    template = _FIX_STEP_TEMPLATE.get(failure_type or "", "Review logic at **{step}**.")
    return template.format(step=step_name)


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

@st.cache_resource
def _get_engine():  # type: ignore[return]
    from api.database import engine, initialize_database
    initialize_database()
    return engine


def _db():  # type: ignore[return]
    from sqlalchemy.orm import sessionmaker
    return sessionmaker(bind=_get_engine())()


# ---------------------------------------------------------------------------
# Navigation — apply before any widget renders
# ---------------------------------------------------------------------------

st.set_page_config(page_title="AgentIQ", layout="wide", page_icon="🔍")

if "_nav_to" in st.session_state:
    st.session_state["view"] = st.session_state.pop("_nav_to")

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("AgentIQ")

    _db_s = _db()
    try:
        _all_agents = get_all_agent_ids(_db_s)
    finally:
        _db_s.close()

    if _all_agents:
        agent_id: str = st.selectbox(
            "Agent",
            _all_agents,
            index=_all_agents.index("demo-agent") if "demo-agent" in _all_agents else 0,
            key="agent_id",
        )
    else:
        agent_id = st.text_input("Agent ID", value="demo-agent", key="agent_id_text")

    view: str = st.radio(
        "View",
        ["Agent Overview", "Failure Feed", "Interaction Detail"],
        key="view",
    )

    if view == "Interaction Detail":
        st.text_input(
            "Jump to Session ID",
            value="",
            key="manual_sid",
            placeholder="paste a session ID…",
        )

st.divider()


# ===========================================================================
# VIEW 1 — Agent Overview
# ===========================================================================

def _show_overview(agent_id: str) -> None:
    st.header("Agent Overview")

    db = _db()
    try:
        stats = get_todays_stats(agent_id, db)
        extra = get_session_and_latency_stats(agent_id, 24, db)
        trend = get_quality_trend(agent_id, TREND_DAYS, db)
        top_types = get_top_failure_types(agent_id, 24, db)
        step_hot = get_failures_by_step(agent_id, 24, db)
        patterns = get_patterns_for_agent(agent_id, db)
    finally:
        db.close()

    failures_24h = stats["total"] - stats["passed"]
    pass_pct = stats["pass_rate"] * 100

    if failures_24h == 0 and stats["total"] > 0:
        st.success("No failures in the last 24h — your agent is healthy.")

    # ── Row 1: 4 key metrics ──────────────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "Sessions (24h)",
        extra["session_count"],
        help=(
            "Distinct agent sessions recorded in the last 24 hours. "
            "A session groups all steps of one workflow run — e.g. one customer support ticket."
        ),
    )
    m2.metric(
        "Pass Rate",
        f"{pass_pct:.0f}%",
        help=(
            "Percentage of evaluated steps where overall_score ≥ 70. "
            "Computed as passed_evals ÷ total_evals for today. "
            "Green = healthy (≥ 70%), Red = needs attention (< 70%)."
        ),
    )
    m3.metric(
        "Avg Score",
        f"{extra['avg_score']:.0f}/100",
        help=(
            "Average quality score across all evaluated steps today, on a 0–100 scale. "
            "Score = accuracy×35% + goal_alignment×35% + decision_quality×15% + completeness×15%. "
            "Each dimension is rated 0.0–1.0 by the LLM judge."
        ),
    )
    m4.metric(
        "Avg Latency",
        f"{extra['avg_latency_ms']} ms",
        help=(
            "Average step execution time in milliseconds across all agent steps in the last 24h. "
            "Measured from when the step input is received to when the output is returned. "
            "Does not include AgentIQ evaluation time."
        ),
    )

    pass_color = "#16a34a" if pass_pct >= 70 else "#dc2626"
    st.markdown(
        f"<style>[data-testid='stMetric']:nth-child(2) "
        f"[data-testid='stMetricValue'] {{ color: {pass_color} !important; }}</style>",
        unsafe_allow_html=True,
    )

    st.markdown("---")

    # ── Row 2: 7-day quality trend ────────────────────────────────────────
    st.subheader(f"Quality Trend — Last {TREND_DAYS} Days")
    if trend:
        df_trend = pd.DataFrame(trend)
        df_trend["Score %"] = (df_trend["avg_score"] * 100).round(1)
        df_trend["Pass Rate %"] = (df_trend["pass_rate"] * 100).round(1)
        st.line_chart(df_trend.set_index("date")[["Score %", "Pass Rate %"]], height=200)
    else:
        st.caption("No evaluation data yet.")

    st.markdown("---")

    # ── Row 3: step hotspots + failure type breakdown ─────────────────────
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Failure Hotspots by Step")
        st.caption("Which workflow steps fail most often in the last 24h")
        if step_hot:
            rows = [
                {
                    "Step": f"{num} · {name}",
                    "Failures": fail_count,
                    "Fail Rate": fail_rate,
                }
                for num, name, fail_count, fail_rate in step_hot
            ]
            st.dataframe(
                pd.DataFrame(rows),
                column_config={
                    "Fail Rate": st.column_config.ProgressColumn(
                        "Fail Rate",
                        format="%.0f%%",
                        min_value=0,
                        max_value=1,
                        help=(
                            "Fraction of evaluations for this step that failed (score < 70). "
                            "E.g. 0.67 means 67 out of every 100 runs of this step produce a failure."
                        ),
                    ),
                    "Failures": st.column_config.NumberColumn(
                        "Failures",
                        help="Raw count of failed evaluations for this step in the last 24h.",
                    ),
                },
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("No failures in the last 24h.")

    with c2:
        st.subheader("Failure Types (24h)")
        st.caption("What categories of failure your agent is producing")
        if top_types:
            rows = [{"Type": ft, "Count": count, "Share": pct} for ft, count, pct in top_types]
            st.dataframe(
                pd.DataFrame(rows),
                column_config={
                    "Share": st.column_config.ProgressColumn(
                        "Share of failures",
                        format="%.0f%%",
                        min_value=0,
                        max_value=1,
                        help=(
                            "This failure type as a percentage of all failures in the last 24h. "
                            "Use this to prioritise which problem to fix first."
                        ),
                    ),
                    "Type": st.column_config.TextColumn(
                        "Failure type",
                        help=(
                            "wrong_answer: response contradicts available data  |  "
                            "tool_failure: tool called incorrectly or API error  |  "
                            "goal_drift: agent stopped serving the user's intent  |  "
                            "incomplete: request not fully resolved  |  "
                            "hallucination: fact not grounded in context  |  "
                            "context_loss: prior conversation ignored  |  "
                            "loop: agent repeated same action without progress"
                        ),
                    ),
                },
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("No failures in the last 24h.")

    # ── Row 4: Action Items ───────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Action Items")
    st.caption("Fix these in order — #1 accounts for the largest share of failures.")

    if not patterns:
        st.info("No recurring patterns detected yet. Run more sessions and check back.")
        return

    ft_patterns = [p for p in patterns if p.pattern_type == "failure_type"]
    seen_root: set = set()
    items_rendered = 0

    for p in sorted(ft_patterns, key=lambda x: x.pct_of_all_failures, reverse=True):
        if p.root_cause in seen_root:
            continue
        seen_root.add(p.root_cause)
        items_rendered += 1
        ft = p.pattern_value
        fix = _FIXES.get(ft, "Review agent logic for this failure type.")
        worsening = "&nbsp;🔺" if p.is_worsening else ""

        num_col, body_col = st.columns([0.5, 9.5])
        num_col.markdown(
            f"<div style='font-size:28px;font-weight:700;color:#9ca3af;"
            f"line-height:1.3;padding-top:4px'>#{items_rendered}</div>",
            unsafe_allow_html=True,
        )
        with body_col:
            st.markdown(
                f"**`{ft}`** &nbsp;&nbsp; "
                f"`{p.pct_of_all_failures * 100:.0f}%` of failures"
                f" &nbsp;·&nbsp; {p.failure_count} occurrences"
                f"{worsening}",
                unsafe_allow_html=True,
            )
            st.markdown(p.root_cause)
            st.markdown(
                f"<div style='color:#0891b2;margin-top:2px'>→ {fix}</div>",
                unsafe_allow_html=True,
            )

        if items_rendered < min(len(ft_patterns), 5):
            st.divider()
        if items_rendered >= 5:
            break

    if items_rendered == 0:
        st.caption("Pattern data uses workflow_step grouping — switch to the Failure Feed for details.")


# ===========================================================================
# VIEW 2 — Failure Feed
# PATTERN cards: recurring issues (from LossPattern)
# RECENT FAILURES: the latest N individual failed sessions
# ===========================================================================

@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _failure_feed_fragment(agent_id: str) -> None:
    db = _db()
    try:
        patterns = get_patterns_for_agent(agent_id, db)
        recent_failures = get_recent_eval_failures(agent_id, 50, db)
    finally:
        db.close()

    if not patterns and not recent_failures:
        st.success("No failures found for this agent.")
        return

    hdr_col, export_col = st.columns([7, 3])
    hdr_col.caption(f"auto-refresh every {AUTO_REFRESH_SECONDS}s")

    # — CSV export —
    if recent_failures:
        rows_csv = [
            {
                "session_id": log.session_id,
                "step_number": log.step_number,
                "step_name": log.step_name,
                "failure_type": ev.failure_type or "",
                "failure_reason": ev.failure_reason or "",
                "overall_score": round(ev.overall_score, 3),
                "accuracy": round(ev.accuracy, 3),
                "goal_alignment": round(ev.goal_alignment, 3),
                "decision_quality": round(ev.decision_quality, 3),
                "completeness": round(ev.completeness, 3),
                "evaluated_at": ev.evaluated_at.isoformat() if ev.evaluated_at else "",
                "fix": _fix_one_line(ev.failure_type, log.step_name),
            }
            for ev, log in recent_failures
        ]
        csv_str = pd.DataFrame(rows_csv).to_csv(index=False)
        export_col.download_button(
            "⬇ Export failures CSV",
            data=csv_str,
            file_name=f"failures_{agent_id}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    # — Compact summary table —
    if recent_failures:
        with st.expander("Summary table", expanded=False):
            summary_rows = [
                {
                    "Session": log.session_id[:28] + "…",
                    "Type": ev.failure_type or "—",
                    "Step": f"{log.step_number} · {log.step_name}",
                    "Score": f"{int(round(ev.overall_score * 100))}/100",
                    "Reason": (ev.failure_reason or "")[:80] + ("…" if len(ev.failure_reason or "") > 80 else ""),
                    "When": _fmt_ts(ev.evaluated_at),
                }
                for ev, log in recent_failures
            ]
            st.dataframe(
                pd.DataFrame(summary_rows),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Reason": st.column_config.TextColumn("Reason", width="large"),
                    "Session": st.column_config.TextColumn("Session", width="medium"),
                },
            )

    # — PATTERN cards (amber) —
    if patterns:
        st.markdown("##### Recurring Patterns")
        st.caption("Failures that share the same root cause across multiple sessions — fix these to have the biggest impact")
        for p in patterns:
            _render_pattern_card(p)

    if patterns and recent_failures:
        st.markdown("---")

    # — Recent failures (real-time feed) —
    if recent_failures:
        st.markdown("##### Recent Failures")
        st.caption("Latest failed sessions — use these to spot new issues before they become patterns")
        for ev, log in recent_failures[:15]:
            _render_recent_failure_card(ev, log)


def _render_pattern_card(p: Any) -> None:
    with st.container(border=True):
        left, right = st.columns([5, 1])
        with left:
            st.markdown(
                f'<span style="background:#92400e;color:#fef3c7;padding:2px 9px;'
                f'border-radius:4px;font-size:11px;font-weight:700">⚠ PATTERN</span>'
                f'&ensp;`{p.pattern_value}` &ensp;·&ensp; '
                f'**{p.pct_of_all_failures * 100:.0f}% of all failures**'
                f'{"&ensp;🔺" if p.is_worsening else ""}',
                unsafe_allow_html=True,
            )
            if p.root_cause:
                st.markdown(f"**{p.root_cause}**")
            fix = _FIXES.get(p.pattern_value, "") if p.pattern_type == "failure_type" else ""
            if fix:
                st.markdown(
                    f'<span style="color:#0ea5e9;font-size:12px">Fix: '
                    f'{fix[:120]}{"…" if len(fix) > 120 else ""}</span>',
                    unsafe_allow_html=True,
                )
            st.caption(
                f"{p.failure_count} occurrences &nbsp;·&nbsp; "
                f"{p.failure_rate * 100:.0f}% fail rate"
                f"{'  ↑ worsening' if p.is_worsening else ''}"
            )
        with right:
            help_label = (
                "View the failing sessions for this pattern, "
                "pre-filtered so you only see the relevant traces"
            )
            if st.button(
                "View sessions",
                key=f"pat_{p.id}",
                width="stretch",
                help=help_label,
            ):
                # Store structured filter so the session browser can apply it
                st.session_state["pattern_filter"] = {
                    "type": p.pattern_type,
                    "value": p.pattern_value,
                    "label": f"{p.pattern_type}: {p.pattern_value}",
                }
                st.session_state["selected_session"] = None
                st.session_state["_nav_to"] = "Interaction Detail"
                st.rerun()


def _render_recent_failure_card(ev: Any, log: Any) -> None:
    sid_short = log.session_id[:20] + "…"
    score = int(round(ev.overall_score * 100))
    ft = ev.failure_type or "unknown"
    fix = _fix_one_line(ev.failure_type, log.step_name)

    with st.container(border=True):
        left, right = st.columns([5, 1])
        with left:
            st.markdown(
                f'<span style="background:#991b1b;color:#fee2e2;padding:2px 9px;'
                f'border-radius:4px;font-size:11px;font-weight:700">✗ FAILED</span>'
                f'&ensp;`{sid_short}`'
                f'&ensp;·&ensp;Score **{score}/100**'
                f'&ensp;·&ensp;{_fmt_ts(ev.evaluated_at)}',
                unsafe_allow_html=True,
            )
            reason = ev.failure_reason or ft
            st.markdown(f"**{reason}**")
            st.caption(f"`{ft}` at step {log.step_number} · {log.step_name}")
            st.markdown(
                f'<span style="color:#0ea5e9;font-size:12px">Fix: {fix}</span>',
                unsafe_allow_html=True,
            )
        with right:
            if st.button(
                "View trace",
                key=f"fail_{ev.id}",
                width="stretch",
                help="Open the step-by-step trace for this session, with failure reason and fix at the bottom",
            ):
                st.session_state["selected_session"] = log.session_id
                st.session_state["_nav_to"] = "Interaction Detail"
                st.rerun()


def _show_failure_feed(agent_id: str) -> None:
    st.header("Failure Feed")
    _failure_feed_fragment(agent_id)


# ===========================================================================
# VIEW 3 — Interaction Detail
# ===========================================================================

_FIX_TEMPLATES: Dict[str, str] = {
    "tool_failure": (
        "Verify the **{step_name}** tool call — check the API endpoint, "
        "authentication token, and request payload are correct."
    ),
    "wrong_answer": (
        "Review what context is available to the agent at **{step_name}** — "
        "the response contradicts the information provided."
    ),
    "goal_drift": (
        "Add an explicit goal check before **{step_name}** — confirm the agent "
        "is still addressing the user's original request, not a derived sub-goal."
    ),
    "hallucination": (
        "Add a grounding constraint at **{step_name}** — require the agent to "
        "cite specific context before asserting facts."
    ),
    "context_loss": (
        "Verify that prior conversation history is passed correctly into "
        "**{step_name}** — the agent lost context from earlier in the session."
    ),
    "incomplete": (
        "Add a completion check after **{step_name}** — confirm all parts of "
        "the user's request are resolved before the session ends."
    ),
    "loop": (
        "Add a repetition guard before **{step_name}** — detect and break if "
        "the same action has been attempted within the last 3 steps."
    ),
}


def _build_diagnosis(steps: List[Tuple[Any, Optional[Any]]]) -> Optional[Dict[str, str]]:
    failed = [(log, ev) for log, ev in steps if ev is not None and not ev.passed]
    if not failed:
        return None

    primary_log, primary_ev = min(failed, key=lambda x: x[1].overall_score)
    ft = primary_ev.failure_type or "unknown"
    step_name = primary_log.step_name

    if len(failed) == 1:
        what = primary_ev.failure_reason or f"{ft} at step {primary_log.step_number}."
    else:
        others = [f"step {log.step_number}" for log, _ in failed if log.id != primary_log.id]
        what = (
            f"Agent failed at {len(failed)} steps. "
            f"Primary failure at step {primary_log.step_number} ({step_name}): "
            f"{primary_ev.failure_reason or ft}. "
            f"Also failed at {', '.join(others)}."
        )

    template = _FIX_TEMPLATES.get(
        ft, "Review agent logic at **{step_name}** — step produced an incorrect or incomplete result."
    )
    fix = template.format(step_name=step_name)
    return {"what_went_wrong": what, "fix": fix}


def _show_interaction_detail(agent_id: str, session_id: str) -> None:
    st.header("Interaction Detail")

    if not session_id:
        _show_session_browser(agent_id)
        return

    if st.button("← Back to session list"):
        st.session_state["selected_session"] = ""
        st.rerun()

    db = _db()
    try:
        steps = get_session_steps(session_id, db)
    finally:
        db.close()

    if not steps:
        st.warning(f"No steps found for session `{session_id}`.")
        return

    failed_steps = [(log, ev) for log, ev in steps if ev is not None and not ev.passed]
    all_evals = [ev for _, ev in steps if ev is not None]
    session_score = int(round(min(ev.overall_score for ev in all_evals) * 100)) if all_evals else 0
    is_failed = bool(failed_steps)

    col_h1, col_h2 = st.columns([4, 1])
    col_h1.markdown(
        f"**Session** `{session_id[:36]}`  "
        f"&nbsp;·&nbsp;  {'**FAILED**' if is_failed else '**PASSED**'}"
    )
    col_h2.markdown(
        f"<div style='text-align:right;font-size:30px;font-weight:700;"
        f"color:{'#dc2626' if is_failed else '#16a34a'}'>"
        f"{session_score}/100</div>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    for log, ev in steps:
        passed = ev.passed if ev is not None else True
        score = int(round(ev.overall_score * 100)) if ev else None
        chip = (
            f"<span style='background:{'#16a34a' if passed else '#dc2626'};"
            f"color:#fff;padding:2px 10px;border-radius:10px;font-size:12px;"
            f"font-weight:600'>{'✓' if passed else '✗'} {score}/100</span>"
            if score is not None else ""
        )
        st.markdown(
            f"**Step {log.step_number} — {log.step_name}**&nbsp;&nbsp;{chip}",
            unsafe_allow_html=True,
        )
        if ev and not ev.passed:
            st.error(
                f"**{ev.failure_type or 'failure'}** — "
                f"{ev.failure_reason or 'No reason recorded.'}"
            )
            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("Accuracy", f"{ev.accuracy * 100:.0f}", help="How factually correct the response is given the available context (0–100)")
            mc2.metric("Goal Align", f"{ev.goal_alignment * 100:.0f}", help="How well the response serves the user's original intent (0–100)")
            mc3.metric("Decision", f"{ev.decision_quality * 100:.0f}", help="Quality of tool selection and reasoning steps (0–100)")
            mc4.metric("Complete", f"{ev.completeness * 100:.0f}", help="Whether all parts of the user's request were addressed (0–100)")

        with st.expander("Show input / output", expanded=False):
            st.markdown("**Input**")
            st.code(log.input, language=None)
            st.markdown("**Output**")
            st.code(log.output, language=None)
            if log.tool_calls:
                try:
                    tools = json.loads(log.tool_calls)
                    if tools:
                        st.markdown("**Tool Calls**")
                        st.json(tools)
                except (json.JSONDecodeError, TypeError):
                    pass
            st.caption(f"Latency: {log.latency_ms} ms · {_fmt_ts(log.timestamp)}")
        st.markdown("")

    # Mandatory bottom: What went wrong + Fix
    diagnosis = _build_diagnosis(steps)
    if diagnosis:
        st.markdown("---")
        st.subheader("What went wrong")
        st.write(diagnosis["what_went_wrong"])
        st.subheader("Fix")
        st.info(diagnosis["fix"])


def _show_session_browser(agent_id: str) -> None:
    """Session browser with sort/filter controls and pattern pre-filter support."""

    # Consume pattern_filter set by Failure Feed → "View sessions" button
    preset: Optional[Dict[str, str]] = st.session_state.pop("pattern_filter", None)
    preset_steps: List[int] = []
    preset_types: List[str] = []

    if preset:
        ptype = preset.get("type", "")
        pval = preset.get("value", "")
        if ptype == "workflow_step":
            try:
                preset_steps = [int(pval.split("_")[1])]
            except (ValueError, IndexError):
                pass
        elif ptype == "failure_type":
            if pval in ALL_FAILURE_TYPES:
                preset_types = [pval]
        st.info(
            f"Showing sessions for pattern **{pval}** "
            f"({ptype.replace('_', ' ')}). "
            f"Clear filters below to see all sessions."
        )
    else:
        st.info("Select a session below, or click **View trace** on any failure card.")

    # Filter + sort controls
    fc1, fc2, fc3, fc4 = st.columns([2, 2, 2, 2])

    sort_label = fc1.selectbox(
        "Sort by",
        ["Newest first", "Lowest score first", "Failure type"],
        key="session_sort",
    )
    ft_filter: List[str] = fc2.multiselect(
        "Failure type",
        ALL_FAILURE_TYPES,
        default=preset_types,
        key="session_ft_filter",
    )
    step_filter: List[int] = fc3.multiselect(
        "Step number",
        list(range(1, 9)),
        default=preset_steps,
        key="session_step_filter",
    )
    time_label = fc4.selectbox(
        "Time range",
        ["Last 24h", "Last 7 days", "All time"],
        index=1,
        key="session_time_filter",
    )

    sort_map = {"Newest first": "newest", "Lowest score first": "score_asc", "Failure type": "failure_type"}
    hours_map = {"Last 24h": 24, "Last 7 days": 168, "All time": None}

    db = _db()
    try:
        sessions = get_recent_failing_sessions(
            agent_id,
            limit=SESSION_BROWSER_LIMIT,
            db=db,
            failure_types=ft_filter or None,
            step_numbers=step_filter or None,
            since_hours=hours_map[time_label],
            sort_by=sort_map[sort_label],
        )
    finally:
        db.close()

    if not sessions:
        st.caption("No failing sessions match the current filters.")
        return

    st.caption(f"{len(sessions)} sessions")
    st.markdown("---")

    for s in sessions:
        with st.container(border=True):
            ca, cb, cc = st.columns([5, 1, 1])
            with ca:
                ft = s["failure_type"] or "unknown"
                step = s.get("failure_step")
                step_txt = f" · step {step}" if step else ""
                sid_short = s["session_id"][:32] + "…"
                st.markdown(
                    f"`{sid_short}` &nbsp;·&nbsp; `{ft}`{step_txt}"
                    f" &nbsp;·&nbsp; {_fmt_ts(s['failed_at'])}"
                )
                if s["failure_reason"]:
                    r = s["failure_reason"]
                    st.caption(r[:120] + "…" if len(r) > 120 else r)
            cb.metric(
                "Score",
                f"{s['overall_score'] * 100:.0f}/100",
                help="Lowest step score in this session (0–100). Sessions fail when any step scores below 70.",
            )
            with cc:
                if st.button("Load trace →", key=f"load_{s['session_id']}"):
                    st.session_state["selected_session"] = s["session_id"]
                    st.rerun()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_ts(ts: Optional[datetime]) -> str:
    if ts is None:
        return "—"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.strftime("%b %d %H:%M")


# ===========================================================================
# Router
# ===========================================================================

if view == "Agent Overview":
    _show_overview(agent_id)
elif view == "Failure Feed":
    _show_failure_feed(agent_id)
elif view == "Interaction Detail":
    sid = st.session_state.get("selected_session") or st.session_state.get("manual_sid", "")
    _show_interaction_detail(agent_id, str(sid))
