"""
agentiq/dashboard.py — three views
Run: streamlit run agentiq/dashboard.py --server.port 8501
"""
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pandas as pd
import streamlit as st

# Page config must be the first Streamlit call
st.set_page_config(
    page_title="AgentIQ",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Design tokens ─────────────────────────────────────────────────────────────
PALETTE: Dict[str, Tuple[str, str]] = {
    "tool_failure":  ("#ef4444", "#fef2f2"),
    "wrong_answer":  ("#f97316", "#fff7ed"),
    "goal_drift":    ("#8b5cf6", "#f5f3ff"),
    "hallucination": ("#ec4899", "#fdf2f8"),
    "context_loss":  ("#0891b2", "#ecfeff"),
    "incomplete":    ("#d97706", "#fffbeb"),
    "loop":          ("#475569", "#f8fafc"),
}

_FIXES: Dict[str, str] = {
    "tool_failure":  "Add retry + fallback to every external tool/API call.",
    "wrong_answer":  "Audit the context injected before each step — the agent is contradicting available data.",
    "goal_drift":    "Add a goal-alignment check at each decision point to abort when the agent drifts.",
    "hallucination": "Require the agent to cite a specific retrieved fact before asserting anything.",
    "context_loss":  "Pass the last 3 conversation turns at every step; the agent is missing prior context.",
    "incomplete":    "Add a completion checklist at session end to verify every part of the request is done.",
    "loop":          "Track actions in a session set — break and escalate after the same action appears 3×.",
}

_FIX_STEP: Dict[str, str] = {
    "tool_failure":  "Add retry/fallback at **{step}**.",
    "wrong_answer":  "Fix context injection before **{step}**.",
    "goal_drift":    "Insert goal check before **{step}**.",
    "hallucination": "Require citations at **{step}**.",
    "context_loss":  "Inject conversation history into **{step}**.",
    "incomplete":    "Add completion check after **{step}**.",
    "loop":          "Add repetition guard before **{step}**.",
}

_FIX_TRACE: Dict[str, str] = {
    "tool_failure":  "Verify the **{s}** API endpoint, auth token, and request payload.",
    "wrong_answer":  "Review context available at **{s}** — the response contradicts provided data.",
    "goal_drift":    "Add a goal check before **{s}** — confirm the agent is on the user's original request.",
    "hallucination": "Add a grounding constraint at **{s}** — require citation of retrieved facts.",
    "context_loss":  "Verify prior conversation history is passed into **{s}**.",
    "incomplete":    "Add a completion check after **{s}** to confirm all parts are addressed.",
    "loop":          "Add a repetition guard before **{s}** — break if the same action appears 3×.",
}

ALL_FT = [
    "tool_failure", "wrong_answer", "goal_drift",
    "incomplete", "hallucination", "context_loss", "loop",
]

AUTO_REFRESH_S = 30
TREND_DAYS = 7
SESSION_LIMIT = 100

# ── Utilities ─────────────────────────────────────────────────────────────────
def _ft_color(ft: str) -> Tuple[str, str]:
    return PALETTE.get(ft, ("#64748b", "#f8fafc"))


def _badge(ft: str, size: str = "12px") -> str:
    fg, bg = _ft_color(ft)
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 10px;'
        f'border-radius:20px;font-size:{size};font-weight:700;'
        f'letter-spacing:0.02em;white-space:nowrap">{ft}</span>'
    )


def _score_chip(score: int, passed: bool) -> str:
    if not passed:
        fg, bg, icon = "#dc2626", "#fef2f2", "✗"
    elif score >= 85:
        fg, bg, icon = "#16a34a", "#f0fdf4", "✓"
    else:
        fg, bg, icon = "#d97706", "#fffbeb", "~"
    return (
        f'<span style="background:{bg};color:{fg};padding:3px 12px;'
        f'border-radius:20px;font-size:13px;font-weight:800">'
        f'{icon} {score}/100</span>'
    )


def _fmt_ts(ts: Optional[datetime]) -> str:
    if ts is None:
        return "—"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.strftime("%b %d %H:%M")


def _fix_step(ft: Optional[str], step: str) -> str:
    return _FIX_STEP.get(ft or "", "Review logic at **{step}**.").format(step=step)


def _fix_trace(ft: Optional[str], step: str) -> str:
    return _FIX_TRACE.get(ft or "", "Review agent logic at **{s}**.").format(s=step)


# ── DB helpers ────────────────────────────────────────────────────────────────
@st.cache_resource
def _engine():  # type: ignore[return]
    from api.database import engine, initialize_database
    initialize_database()
    return engine


def _db():  # type: ignore[return]
    from sqlalchemy.orm import sessionmaker
    return sessionmaker(bind=_engine())()


# ── db.queries imports (must be before sidebar code that calls them) ──────────
from db.queries import (  # noqa: E402
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

# ── Handle nav redirects: pop but don't set widget key before it renders ──────
_pending_nav: Optional[str] = st.session_state.pop("_nav_to", None)

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Reset ── */
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1280px; }

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: #0f172a !important;
    border-right: none !important;
}
section[data-testid="stSidebar"] > div:first-child { padding-top: 0 !important; }
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] div { color: #94a3b8 !important; }
section[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background: #1e293b !important;
    border-color: #334155 !important;
}
section[data-testid="stSidebar"] [data-baseweb="select"] * { color: #e2e8f0 !important; }
section[data-testid="stSidebar"] hr { border-color: #1e293b !important; }
section[data-testid="stSidebar"] [data-testid="stRadio"] > div { gap: 2px !important; }
section[data-testid="stSidebar"] [data-testid="stRadio"] label {
    padding: 9px 14px !important;
    border-radius: 8px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    width: 100% !important;
    cursor: pointer !important;
    transition: all 0.12s !important;
}
section[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
    background: #1e293b !important;
}
section[data-testid="stSidebar"] input[type="radio"]:checked + div p {
    color: #f1f5f9 !important;
    font-weight: 700 !important;
}

/* ── Page background ── */
.stApp { background: #f8fafc !important; }

/* ── Metric cards ── */
[data-testid="stMetric"] {
    background: white !important;
    border-radius: 14px !important;
    padding: 20px 22px 16px !important;
    border: 1px solid #e2e8f0 !important;
    box-shadow: 0 1px 3px rgba(15,23,42,0.06) !important;
}
[data-testid="stMetricLabel"] > div {
    font-size: 11px !important;
    font-weight: 700 !important;
    color: #64748b !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
}
[data-testid="stMetricValue"] > div {
    font-size: 32px !important;
    font-weight: 800 !important;
    color: #0f172a !important;
    letter-spacing: -0.03em !important;
    line-height: 1.1 !important;
}
[data-testid="stMetricDelta"] { font-size: 12px !important; font-weight: 600 !important; }

/* ── Bordered containers ── */
[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 14px !important;
    border: 1px solid #e2e8f0 !important;
    background: white !important;
    box-shadow: 0 1px 3px rgba(15,23,42,0.04) !important;
}

/* ── Buttons ── */
.stButton > button {
    border-radius: 8px !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    height: 34px !important;
    border: 1px solid #e2e8f0 !important;
    background: white !important;
    color: #475569 !important;
    letter-spacing: 0.01em !important;
    transition: all 0.12s !important;
    box-shadow: 0 1px 2px rgba(15,23,42,0.04) !important;
}
.stButton > button:hover {
    background: #f8fafc !important;
    border-color: #94a3b8 !important;
    color: #0f172a !important;
    box-shadow: 0 2px 6px rgba(15,23,42,0.08) !important;
}

/* ── Headings ── */
h1 { font-size: 22px !important; font-weight: 800 !important; color: #0f172a !important;
     letter-spacing: -0.025em !important; margin: 0 !important; }
h2 { font-size: 15px !important; font-weight: 700 !important; color: #1e293b !important;
     margin-bottom: 4px !important; }
h3 { font-size: 13px !important; font-weight: 600 !important; color: #334155 !important; }

/* ── Divider ── */
hr { border: none !important; border-top: 1px solid #f1f5f9 !important; margin: 20px 0 !important; }

/* ── Caption ── */
.stCaption p { font-size: 12px !important; color: #94a3b8 !important; }

/* ── Expander ── */
summary { font-size: 13px !important; font-weight: 600 !important; color: #475569 !important; }

/* ── Code ── */
code {
    font-size: 11px !important;
    background: #f1f5f9 !important;
    padding: 1px 6px !important;
    border-radius: 4px !important;
    color: #475569 !important;
}

/* ── Download button ── */
[data-testid="stDownloadButton"] > button { font-size: 12px !important; background: #f8fafc !important; }

/* ── Alert boxes ── */
[data-testid="stAlert"] { border-radius: 10px !important; font-size: 13px !important; }

/* ── Dataframe ── */
[data-testid="stDataFrame"] { border-radius: 10px !important; overflow: hidden !important; }

/* ── Text input ── */
.stTextInput input { border-radius: 8px !important; font-size: 13px !important; border-color: #e2e8f0 !important; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown(
        """
        <div style="padding:24px 16px 20px">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
            <div style="background:#6366f1;width:34px;height:34px;border-radius:9px;
                        display:flex;align-items:center;justify-content:center;
                        font-size:20px;flex-shrink:0">⚡</div>
            <div>
              <div style="font-size:19px;font-weight:900;color:#f8fafc;letter-spacing:-0.03em">AgentIQ</div>
              <div style="font-size:10px;color:#475569;font-weight:600;letter-spacing:0.08em;
                          text-transform:uppercase;margin-top:-1px">AI MONITORING</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<hr style="margin:0 0 16px"/>', unsafe_allow_html=True)

    st.markdown(
        '<p style="font-size:10px;font-weight:700;color:#475569;letter-spacing:0.08em;'
        'text-transform:uppercase;margin-bottom:4px;padding:0 4px">AGENT</p>',
        unsafe_allow_html=True,
    )
    _db_s = _db()
    try:
        _all_agents = get_all_agent_ids(_db_s)
    except Exception:
        _all_agents = []
    finally:
        _db_s.close()

    if _all_agents:
        _def = _all_agents.index("demo-agent") if "demo-agent" in _all_agents else 0
        agent_id: str = st.selectbox(
            "agent", _all_agents, index=_def, key="agent_id", label_visibility="collapsed",
        )
    else:
        agent_id = st.text_input(
            "agent", value="demo-agent", key="agent_id_text",
            label_visibility="collapsed", placeholder="Enter agent ID…",
        )

    st.markdown('<div style="height:20px"/>', unsafe_allow_html=True)

    st.markdown(
        '<p style="font-size:10px;font-weight:700;color:#475569;letter-spacing:0.08em;'
        'text-transform:uppercase;margin-bottom:4px;padding:0 4px">NAVIGATE</p>',
        unsafe_allow_html=True,
    )
    _NAV_OPTIONS = ["📊  Overview", "🔴  Failure Feed", "🔍  Trace Viewer"]
    _nav_idx = (
        _NAV_OPTIONS.index(_pending_nav)
        if _pending_nav in _NAV_OPTIONS
        else _NAV_OPTIONS.index(st.session_state.get("view", _NAV_OPTIONS[0]))
        if st.session_state.get("view") in _NAV_OPTIONS
        else 0
    )
    view: str = st.radio(
        "nav",
        _NAV_OPTIONS,
        index=_nav_idx,
        key="view",
        label_visibility="collapsed",
    )

    if "Trace" in view:
        st.markdown('<div style="height:8px"/>', unsafe_allow_html=True)
        st.text_input(
            "jump",
            value="",
            key="manual_sid",
            placeholder="Paste session ID…",
            label_visibility="collapsed",
        )

    st.markdown('<hr style="margin:20px 0 12px"/>', unsafe_allow_html=True)
    st.markdown(
        '<p style="font-size:11px;color:#334155;padding:0 4px;line-height:1.7">'
        'Evals every 30s<br>Patterns hourly</p>',
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def _page_header(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div style="margin-bottom:24px">'
        f'<h1>{title}</h1>'
        f'<p style="font-size:13px;color:#64748b;margin-top:4px">{subtitle}</p>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _section_head(label: str, sub: str = "") -> None:
    sub_html = (
        f'<span style="font-size:12px;color:#94a3b8;font-weight:400;margin-left:6px">{sub}</span>'
        if sub else ""
    )
    st.markdown(f'<h2 style="margin:20px 0 8px">{label}{sub_html}</h2>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW 1 — Overview
# ═══════════════════════════════════════════════════════════════════════════════
def _show_overview(agent_id: str) -> None:
    _page_header("Agent Overview", "Quality metrics and failure patterns for the last 24 hours")

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
        st.success("No failures in the last 24 hours — your agent is healthy.", icon="✅")

    # ── KPIs ────────────────────────────────────────────────────────────────
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Sessions (24h)", extra["session_count"],
              help="Distinct agent sessions in the last 24h")
    k2.metric("Pass Rate", f"{pass_pct:.0f}%",
              delta=f"{stats['passed']} passed · {failures_24h} failed",
              help="% of steps scoring ≥ 70")
    k3.metric("Avg Score", f"{extra['avg_score']:.0f}/100",
              help="Weighted avg: accuracy 35%, goal 35%, decision 15%, completeness 15%")
    k4.metric("Avg Latency", f"{extra['avg_latency_ms']} ms",
              help="Mean step execution time")

    color = "#16a34a" if pass_pct >= 70 else "#dc2626"
    st.markdown(
        f"<style>[data-testid='stMetric']:nth-child(2) "
        f"[data-testid='stMetricValue'] > div {{ color: {color} !important; }}</style>",
        unsafe_allow_html=True,
    )

    # ── Trend ───────────────────────────────────────────────────────────────
    _section_head("Quality Trend", f"last {TREND_DAYS} days")
    if trend:
        df = pd.DataFrame(trend)
        df["Score %"] = (df["avg_score"] * 100).round(1)
        df["Pass Rate %"] = (df["pass_rate"] * 100).round(1)
        st.line_chart(df.set_index("date")[["Score %", "Pass Rate %"]], height=200)
    else:
        st.caption("No evaluation data yet.")

    # ── Failure breakdown ────────────────────────────────────────────────────
    _section_head("Failure Breakdown", "last 24h")
    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown(
            '<p style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;'
            'letter-spacing:0.06em;margin-bottom:8px">By Workflow Step</p>',
            unsafe_allow_html=True,
        )
        if step_hot:
            rows = [
                {"Step": f"{n} · {name}", "Failures": cnt, "Fail Rate": rate}
                for n, name, cnt, rate in step_hot
            ]
            st.dataframe(
                pd.DataFrame(rows),
                column_config={
                    "Fail Rate": st.column_config.ProgressColumn(
                        "Fail Rate", format="%.0f%%", min_value=0, max_value=1),
                    "Failures": st.column_config.NumberColumn("Failures"),
                },
                hide_index=True, use_container_width=True,
            )
        else:
            st.caption("No failures in the last 24h.")

    with col_r:
        st.markdown(
            '<p style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;'
            'letter-spacing:0.06em;margin-bottom:8px">By Failure Type</p>',
            unsafe_allow_html=True,
        )
        if top_types:
            rows2 = [{"Type": ft, "Count": cnt, "Share": pct} for ft, cnt, pct in top_types]
            st.dataframe(
                pd.DataFrame(rows2),
                column_config={
                    "Share": st.column_config.ProgressColumn(
                        "Share", format="%.0f%%", min_value=0, max_value=1),
                },
                hide_index=True, use_container_width=True,
            )
        else:
            st.caption("No failures in the last 24h.")

    # ── Action items ─────────────────────────────────────────────────────────
    _section_head("Action Items", "highest impact — fix in order")

    if not patterns:
        st.info("No recurring patterns yet — patterns appear once 5+ failures share a root cause.")
        return

    sorted_p = sorted(
        [p for p in patterns if p.pattern_type == "failure_type"],
        key=lambda x: x.pct_of_all_failures,
        reverse=True,
    )
    seen: set = set()
    n = 0
    for p in sorted_p:
        if p.root_cause in seen or n >= 5:
            break
        seen.add(p.root_cause)
        n += 1
        ft = p.pattern_value
        fg, bg = _ft_color(ft)
        fix = _FIXES.get(ft, "Review agent logic.")
        worsening = ' <span style="color:#ef4444;font-size:11px">▲ worsening</span>' if p.is_worsening else ""

        st.markdown(
            f"""
            <div style="background:white;border:1px solid #e2e8f0;border-left:4px solid {fg};
                        border-radius:0 12px 12px 0;padding:16px 20px;margin:8px 0;
                        box-shadow:0 1px 3px rgba(15,23,42,0.04)">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
                <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                  <span style="font-size:11px;font-weight:800;color:#94a3b8">#{n}</span>
                  {_badge(ft)}
                  {worsening}
                </div>
                <span style="font-size:13px;font-weight:800;color:{fg}">
                  {p.pct_of_all_failures * 100:.0f}% of failures
                </span>
              </div>
              <div style="font-size:14px;font-weight:600;color:#1e293b;margin-bottom:6px">
                {p.root_cause or "No root cause identified"}
              </div>
              <div style="font-size:12px;color:#0891b2;margin-bottom:8px">→ {fix}</div>
              <div style="font-size:11px;color:#94a3b8">
                {p.failure_count} occurrences · {p.failure_rate * 100:.0f}% fail rate
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW 2 — Failure Feed
# ═══════════════════════════════════════════════════════════════════════════════
@st.fragment(run_every=AUTO_REFRESH_S)
def _failure_feed_fragment(agent_id: str) -> None:
    db = _db()
    try:
        patterns = get_patterns_for_agent(agent_id, db)
        recent = get_recent_eval_failures(agent_id, 50, db)
    finally:
        db.close()

    if not patterns and not recent:
        st.success("No failures found for this agent.", icon="✅")
        return

    hcol, ecol = st.columns([6, 2])
    hcol.caption(f"⟳ Auto-refreshing every {AUTO_REFRESH_S}s")
    if recent:
        rows_csv = [
            {
                "session_id": log.session_id,
                "step": log.step_name,
                "failure_type": ev.failure_type or "",
                "failure_reason": ev.failure_reason or "",
                "score": round(ev.overall_score * 100),
                "evaluated_at": ev.evaluated_at.isoformat() if ev.evaluated_at else "",
            }
            for ev, log in recent
        ]
        ecol.download_button(
            "⬇ Export CSV",
            data=pd.DataFrame(rows_csv).to_csv(index=False),
            file_name=f"agentiq-failures-{agent_id}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    if recent:
        with st.expander("All failures — flat table", expanded=False):
            tbl = [
                {
                    "Session": log.session_id[:28] + "…",
                    "Type": ev.failure_type or "—",
                    "Step": f"{log.step_number} · {log.step_name}",
                    "Score": f"{int(round(ev.overall_score * 100))}/100",
                    "Reason": (ev.failure_reason or "")[:90],
                    "When": _fmt_ts(ev.evaluated_at),
                }
                for ev, log in recent
            ]
            st.dataframe(pd.DataFrame(tbl), hide_index=True, use_container_width=True)

    if patterns:
        st.markdown(
            '<h2 style="margin:16px 0 4px">Recurring Patterns</h2>'
            '<p style="font-size:12px;color:#94a3b8;margin:0 0 12px">'
            'Same root cause across multiple sessions — highest impact to fix first</p>',
            unsafe_allow_html=True,
        )
        for p in patterns:
            _render_pattern_card(p)

    if patterns and recent:
        st.markdown('<hr/>', unsafe_allow_html=True)

    if recent:
        st.markdown(
            '<h2 style="margin:0 0 4px">Recent Failures</h2>'
            '<p style="font-size:12px;color:#94a3b8;margin:0 0 12px">'
            'Latest failed evaluations</p>',
            unsafe_allow_html=True,
        )
        for ev, log in recent[:15]:
            _render_failure_card(ev, log)


def _render_pattern_card(p: Any) -> None:
    ft = p.pattern_value
    fg, _ = _ft_color(ft)
    fix = _FIXES.get(ft, "") if p.pattern_type == "failure_type" else ""
    worsening = (
        '&nbsp;&nbsp;<span style="color:#ef4444;font-weight:700;font-size:11px">▲ worsening</span>'
        if p.is_worsening else ""
    )

    with st.container(border=True):
        lc, rc = st.columns([6, 1])
        with lc:
            st.markdown(
                f"""
                <div style="margin-bottom:8px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                  <span style="background:#fef3c7;color:#92400e;padding:2px 8px;
                               border-radius:4px;font-size:10px;font-weight:800;letter-spacing:0.05em">
                    ⚠ PATTERN
                  </span>
                  {_badge(ft)}
                  {worsening}
                  <span style="font-size:12px;font-weight:800;color:{fg}">
                    {p.pct_of_all_failures * 100:.0f}% of all failures
                  </span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if p.root_cause:
                st.markdown(
                    f'<div style="font-size:14px;font-weight:600;color:#1e293b;margin-bottom:5px">'
                    f'{p.root_cause}</div>',
                    unsafe_allow_html=True,
                )
            if fix:
                st.markdown(
                    f'<div style="font-size:12px;color:#0891b2;margin-bottom:6px">→ {fix[:160]}</div>',
                    unsafe_allow_html=True,
                )
            st.caption(
                f"{p.failure_count} occurrences · {p.failure_rate * 100:.0f}% fail rate "
                f"· first seen {_fmt_ts(p.first_seen)}"
            )
        with rc:
            if st.button("View →", key=f"pat_{p.id}", use_container_width=True):
                st.session_state["pattern_filter"] = {
                    "type": p.pattern_type, "value": p.pattern_value,
                }
                st.session_state["selected_session"] = None
                st.session_state["view"] = "🔍  Trace Viewer"
                st.rerun(scope="app")


def _render_failure_card(ev: Any, log: Any) -> None:
    score = int(round(ev.overall_score * 100))
    ft = ev.failure_type or "unknown"

    with st.container(border=True):
        lc, rc = st.columns([6, 1])
        with lc:
            st.markdown(
                f"""
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap">
                  <span style="background:#fef2f2;color:#991b1b;padding:2px 8px;
                               border-radius:4px;font-size:10px;font-weight:800">✗ FAILED</span>
                  {_badge(ft)}
                  {_score_chip(score, False)}
                  <span style="font-size:11px;color:#94a3b8">{_fmt_ts(ev.evaluated_at)}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            reason = ev.failure_reason or ft
            st.markdown(
                f'<div style="font-size:13px;font-weight:600;color:#1e293b;margin-bottom:4px">'
                f'{reason}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div style="font-size:11px;color:#94a3b8;margin-bottom:4px">'
                f'Step {log.step_number} · {log.step_name} · '
                f'<code>{log.session_id[:26]}…</code></div>',
                unsafe_allow_html=True,
            )
            fix = _fix_step(ev.failure_type, log.step_name)
            st.markdown(
                f'<div style="font-size:12px;color:#0891b2">→ {fix}</div>',
                unsafe_allow_html=True,
            )
        with rc:
            if st.button("Trace →", key=f"fail_{ev.id}", use_container_width=True):
                st.session_state["selected_session"] = log.session_id
                st.session_state["view"] = "🔍  Trace Viewer"
                st.rerun(scope="app")


def _show_failure_feed(agent_id: str) -> None:
    _page_header("Failure Feed", "Real-time failures and recurring patterns — auto-refreshes every 30s")
    _failure_feed_fragment(agent_id)


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW 3 — Trace Viewer
# ═══════════════════════════════════════════════════════════════════════════════
def _build_diagnosis(
    steps: List[Tuple[Any, Optional[Any]]],
) -> Optional[Dict[str, str]]:
    failed = [(log, ev) for log, ev in steps if ev is not None and not ev.passed]
    if not failed:
        return None
    primary_log, primary_ev = min(failed, key=lambda x: x[1].overall_score)
    ft = primary_ev.failure_type or "unknown"
    step_name = primary_log.step_name

    if len(failed) == 1:
        what = primary_ev.failure_reason or f"{ft} at step {primary_log.step_number}."
    else:
        others = [f"step {l.step_number}" for l, _ in failed if l.id != primary_log.id]
        what = (
            f"Agent failed at {len(failed)} steps. Primary failure at step "
            f"{primary_log.step_number} ({step_name}): {primary_ev.failure_reason or ft}. "
            f"Also failed at {', '.join(others)}."
        )
    return {"what": what, "fix": _fix_trace(ft, step_name)}


def _show_trace(agent_id: str, session_id: str) -> None:
    _page_header("Trace Viewer", "Step-by-step agent trace with per-step scores and diagnosis")

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

    all_evals = [ev for _, ev in steps if ev is not None]
    failed_steps = [(l, ev) for l, ev in steps if ev is not None and not ev.passed]
    session_score = int(round(min(ev.overall_score for ev in all_evals) * 100)) if all_evals else 0
    is_failed = bool(failed_steps)
    score_color = "#dc2626" if is_failed else "#16a34a"
    status_label = "FAILED" if is_failed else "PASSED"

    st.markdown(
        f"""
        <div style="background:white;border:1px solid #e2e8f0;border-radius:14px;
                    padding:20px 24px;display:flex;justify-content:space-between;
                    align-items:center;margin-bottom:20px;
                    box-shadow:0 1px 3px rgba(15,23,42,0.05)">
          <div>
            <div style="font-size:10px;font-weight:700;color:#64748b;letter-spacing:0.08em;
                        text-transform:uppercase;margin-bottom:4px">Session ID</div>
            <code style="font-size:13px;color:#1e293b;background:transparent;padding:0">{session_id}</code>
            <div style="font-size:12px;color:#94a3b8;margin-top:6px">
              {len(steps)} steps · {len(failed_steps)} failed
            </div>
          </div>
          <div style="text-align:right">
            <div style="font-size:40px;font-weight:900;color:{score_color};
                        letter-spacing:-0.04em;line-height:1">
              {session_score}
              <span style="font-size:18px;font-weight:400;color:#94a3b8">/100</span>
            </div>
            <div style="font-size:12px;font-weight:700;color:{score_color};
                        letter-spacing:0.06em">{status_label}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    for log, ev in steps:
        passed = ev.passed if ev is not None else True
        score = int(round(ev.overall_score * 100)) if ev else None
        border = "#ef4444" if (ev and not passed) else "#22c55e" if (ev and passed) else "#e2e8f0"
        step_bg = "#fef2f2" if (ev and not passed) else "white"
        ev_badge_html = ""
        if score is not None:
            ev_badge_html = f'&nbsp;&nbsp;{_score_chip(score, passed)}'

        st.markdown(
            f"""
            <div style="background:{step_bg};border:1px solid #e2e8f0;border-left:4px solid {border};
                        border-radius:0 12px 12px 0;padding:14px 18px;margin:8px 0">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:{'8px' if ev and not passed else '0'}">
                <div>
                  <span style="font-size:10px;color:#94a3b8;font-weight:700;text-transform:uppercase;
                               letter-spacing:0.08em">Step {log.step_number}</span>
                  <span style="font-size:15px;font-weight:700;color:#1e293b;margin-left:10px">{log.step_name}</span>
                </div>
                {ev_badge_html}
              </div>
              {
                f'<div style="font-size:12px;color:#64748b;margin-top:2px">'
                f'{_badge((ev.failure_type or "unknown"), "11px")}'
                f'&nbsp;&nbsp;{ev.failure_reason or ""}'
                f'</div>'
                if ev and not ev.passed else ""
              }
            </div>
            """,
            unsafe_allow_html=True,
        )

        if ev and not ev.passed:
            sc1, sc2, sc3, sc4 = st.columns(4)
            sc1.metric("Accuracy", f"{ev.accuracy * 100:.0f}")
            sc2.metric("Goal Align", f"{ev.goal_alignment * 100:.0f}")
            sc3.metric("Decision", f"{ev.decision_quality * 100:.0f}")
            sc4.metric("Completeness", f"{ev.completeness * 100:.0f}")

        with st.expander(
            f"Input / Output  ·  {log.latency_ms} ms",
            expanded=False,
        ):
            ic, oc = st.columns(2)
            with ic:
                st.markdown(
                    '<p style="font-size:10px;font-weight:700;color:#64748b;'
                    'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px">Input</p>',
                    unsafe_allow_html=True,
                )
                st.code(log.input[:1000] + ("…" if len(log.input) > 1000 else ""), language=None)
            with oc:
                st.markdown(
                    '<p style="font-size:10px;font-weight:700;color:#64748b;'
                    'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px">Output</p>',
                    unsafe_allow_html=True,
                )
                st.code(log.output[:1000] + ("…" if len(log.output) > 1000 else ""), language=None)
            if log.tool_calls:
                try:
                    tools = json.loads(log.tool_calls) if isinstance(log.tool_calls, str) else log.tool_calls
                    if tools:
                        st.markdown(
                            '<p style="font-size:10px;font-weight:700;color:#64748b;'
                            'text-transform:uppercase;letter-spacing:0.06em;margin:8px 0 4px">Tool Calls</p>',
                            unsafe_allow_html=True,
                        )
                        st.json(tools)
                except (json.JSONDecodeError, TypeError):
                    pass

    diag = _build_diagnosis(steps)
    if diag:
        st.markdown(
            f"""
            <div style="background:white;border:1px solid #e2e8f0;border-radius:14px;
                        padding:20px 24px;margin-top:16px;
                        box-shadow:0 1px 3px rgba(15,23,42,0.05)">
              <div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;
                          letter-spacing:0.08em;margin-bottom:10px">Diagnosis</div>
              <div style="font-size:14px;color:#475569;margin-bottom:16px;line-height:1.7">
                {diag['what']}
              </div>
              <div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;
                          letter-spacing:0.08em;margin-bottom:8px">Recommended Fix</div>
              <div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:10px;
                          padding:12px 16px;font-size:13px;color:#0c4a6e;line-height:1.6">
                {diag['fix']}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _show_session_browser(agent_id: str) -> None:
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
        elif ptype == "failure_type" and pval in ALL_FT:
            preset_types = [pval]
        st.info(
            f"Filtered to pattern **{pval}** ({ptype.replace('_', ' ')}). "
            "Clear filters below to see all.",
        )
    else:
        st.info(
            "Select a session below, or click **Trace →** on any card in the Failure Feed.",
        )

    fc1, fc2, fc3, fc4 = st.columns(4)
    sort_lbl = fc1.selectbox(
        "Sort by", ["Newest first", "Lowest score first", "Failure type"], key="session_sort",
    )
    ft_sel: List[str] = fc2.multiselect(
        "Failure type", ALL_FT, default=preset_types, key="session_ft",
    )
    step_sel: List[int] = fc3.multiselect(
        "Step number", list(range(1, 9)), default=preset_steps, key="session_step",
    )
    time_lbl = fc4.selectbox(
        "Time range", ["Last 24h", "Last 7 days", "All time"], index=1, key="session_time",
    )

    sort_map = {
        "Newest first": "newest",
        "Lowest score first": "score_asc",
        "Failure type": "failure_type",
    }
    hours_map: Dict[str, Optional[int]] = {
        "Last 24h": 24, "Last 7 days": 168, "All time": None,
    }

    db = _db()
    try:
        sessions = get_recent_failing_sessions(
            agent_id,
            limit=SESSION_LIMIT,
            db=db,
            failure_types=ft_sel or None,
            step_numbers=step_sel or None,
            since_hours=hours_map[time_lbl],
            sort_by=sort_map[sort_lbl],
        )
    finally:
        db.close()

    if not sessions:
        st.caption("No failing sessions match the current filters.")
        return

    st.markdown(
        f'<p style="font-size:12px;color:#94a3b8;margin:12px 0 8px">'
        f'{len(sessions)} session{"s" if len(sessions) != 1 else ""}</p>',
        unsafe_allow_html=True,
    )

    for s in sessions:
        ft = s["failure_type"] or "unknown"
        score = s["overall_score"] * 100

        with st.container(border=True):
            ca, cb, cc = st.columns([5, 1, 1])
            with ca:
                step_html = (
                    f'<span style="font-size:11px;color:#94a3b8">· step {s["failure_step"]}</span>'
                    if s.get("failure_step") else ""
                )
                st.markdown(
                    f"""
                    <div style="display:flex;align-items:center;gap:8px;margin-bottom:5px;flex-wrap:wrap">
                      {_badge(ft)}
                      <span style="font-size:11px;color:#94a3b8">{_fmt_ts(s['failed_at'])}</span>
                      {step_html}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if s["failure_reason"]:
                    r = s["failure_reason"]
                    st.markdown(
                        f'<div style="font-size:13px;color:#475569;margin-bottom:4px">'
                        f'{r[:130]}{"…" if len(r) > 130 else ""}</div>',
                        unsafe_allow_html=True,
                    )
                st.markdown(
                    f'<code style="font-size:10px;color:#94a3b8">{s["session_id"][:34]}…</code>',
                    unsafe_allow_html=True,
                )
            cb.metric("Score", f"{score:.0f}")
            with cc:
                if st.button("Open →", key=f"open_{s['session_id']}", use_container_width=True):
                    st.session_state["selected_session"] = s["session_id"]
                    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════════════
if "Overview" in view:
    _show_overview(agent_id)
elif "Failure" in view:
    _show_failure_feed(agent_id)
elif "Trace" in view:
    sid = st.session_state.get("selected_session") or st.session_state.get("manual_sid", "")
    _show_trace(agent_id, str(sid))
