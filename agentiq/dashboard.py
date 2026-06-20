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

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

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


# ── Imports ───────────────────────────────────────────────────────────────────
from db.queries import (  # noqa: E402
    get_all_agent_ids,
    get_failures_by_step,
    get_latency_values,
    get_patterns_for_agent,
    get_quality_trend,
    get_recent_eval_failures,
    get_recent_failing_sessions,
    get_score_buckets,
    get_session_and_latency_stats,
    get_session_steps,
    get_todays_stats,
    get_top_failure_types,
    search_eval_failures,
)

# ── Nav redirect (pop before sidebar renders, set index from it) ──────────────
_pending_nav: Optional[str] = st.session_state.pop("_nav_to", None)

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Reset ── */
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1400px; }

/* ── Sidebar — light, matches main content ── */
section[data-testid="stSidebar"] {
    background: #ffffff !important;
    border-right: 1px solid #e2e8f0 !important;
}
section[data-testid="stSidebar"] > div:first-child { padding-top: 0 !important; }
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] div { color: #64748b !important; }
section[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background: #f8fafc !important; border-color: #e2e8f0 !important;
}
section[data-testid="stSidebar"] [data-baseweb="select"] * { color: #1e293b !important; }
section[data-testid="stSidebar"] hr { border-color: #f1f5f9 !important; }
section[data-testid="stSidebar"] [data-testid="stRadio"] > div { gap: 2px !important; }
section[data-testid="stSidebar"] [data-testid="stRadio"] label {
    padding: 9px 14px !important; border-radius: 8px !important;
    font-size: 13px !important; font-weight: 500 !important;
    width: 100% !important; cursor: pointer !important; transition: all 0.12s !important;
    color: #475569 !important;
}
section[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
    background: #f5f3ff !important; color: #6366f1 !important;
}
section[data-testid="stSidebar"] input[type="radio"]:checked + div p {
    color: #6366f1 !important; font-weight: 700 !important;
}
section[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) {
    background: #eff0fe !important;
}

/* ── Page background ── */
.stApp { background: #f8fafc !important; }

/* ── Metric cards ── */
[data-testid="stMetric"] {
    background: white !important; border-radius: 14px !important;
    padding: 20px 22px 16px !important; border: 1px solid #e2e8f0 !important;
    box-shadow: 0 1px 3px rgba(15,23,42,0.06) !important;
}
[data-testid="stMetricLabel"] > div {
    font-size: 11px !important; font-weight: 700 !important;
    color: #64748b !important; text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
}
[data-testid="stMetricValue"] > div {
    font-size: 30px !important; font-weight: 800 !important;
    color: #0f172a !important; letter-spacing: -0.03em !important;
    line-height: 1.1 !important;
}
[data-testid="stMetricDelta"] { font-size: 12px !important; font-weight: 600 !important; }

/* ── Bordered containers ── */
[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 14px !important; border: 1px solid #e2e8f0 !important;
    background: white !important; box-shadow: 0 1px 3px rgba(15,23,42,0.04) !important;
}

/* ── Buttons ── */
.stButton > button {
    border-radius: 8px !important; font-size: 12px !important;
    font-weight: 600 !important; height: 34px !important;
    border: 1px solid #e2e8f0 !important; background: white !important;
    color: #475569 !important; letter-spacing: 0.01em !important;
    transition: all 0.12s !important; box-shadow: 0 1px 2px rgba(15,23,42,0.04) !important;
}
.stButton > button:hover {
    background: #f8fafc !important; border-color: #94a3b8 !important;
    color: #0f172a !important; box-shadow: 0 2px 6px rgba(15,23,42,0.08) !important;
}

/* ── Headings ── */
h1 { font-size: 22px !important; font-weight: 800 !important; color: #0f172a !important;
     letter-spacing: -0.025em !important; margin: 0 !important; }
h2 { font-size: 15px !important; font-weight: 700 !important; color: #1e293b !important;
     margin-bottom: 4px !important; }
h3 { font-size: 13px !important; font-weight: 600 !important; color: #334155 !important; }

/* ── Divider ── */
hr { border: none !important; border-top: 1px solid #e2e8f0 !important; margin: 20px 0 !important; }

/* ── Caption ── */
.stCaption p { font-size: 12px !important; color: #94a3b8 !important; }

/* ── Expander ── */
summary { font-size: 13px !important; font-weight: 600 !important; color: #475569 !important; }

/* ── Code ── */
code {
    font-size: 11px !important; background: #f1f5f9 !important;
    padding: 1px 6px !important; border-radius: 4px !important; color: #475569 !important;
}

/* ── Download button ── */
[data-testid="stDownloadButton"] > button { font-size: 12px !important; background: #f8fafc !important; }

/* ── Alert boxes ── */
[data-testid="stAlert"] { border-radius: 10px !important; font-size: 13px !important; }

/* ── Text input ── */
.stTextInput input { border-radius: 8px !important; font-size: 13px !important; border-color: #e2e8f0 !important; }

/* ── Search input ── */
.search-box input { font-size: 13px !important; }

/* ── Plotly charts ── */
.js-plotly-plot { border-radius: 12px !important; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown(
        """
        <div style="padding:24px 16px 20px">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px">
            <div style="background:linear-gradient(135deg,#6366f1,#8b5cf6);width:34px;height:34px;
                        border-radius:9px;display:flex;align-items:center;justify-content:center;
                        font-size:20px;flex-shrink:0;box-shadow:0 2px 8px rgba(99,102,241,0.3)">⚡</div>
            <div>
              <div style="font-size:19px;font-weight:900;color:#0f172a;letter-spacing:-0.03em">AgentIQ</div>
              <div style="font-size:10px;color:#94a3b8;font-weight:600;letter-spacing:0.08em;
                          text-transform:uppercase;margin-top:-1px">AI MONITORING</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<hr style="margin:0 0 16px"/>', unsafe_allow_html=True)

    st.markdown(
        '<p style="font-size:10px;font-weight:700;color:#94a3b8;letter-spacing:0.08em;'
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
        '<p style="font-size:10px;font-weight:700;color:#94a3b8;letter-spacing:0.08em;'
        'text-transform:uppercase;margin-bottom:4px;padding:0 4px">NAVIGATE</p>',
        unsafe_allow_html=True,
    )
    _NAV_OPTIONS = ["📊  Overview", "🔴  Failure Feed", "🔍  Trace Viewer"]
    _nav_idx = (
        _NAV_OPTIONS.index(_pending_nav)
        if _pending_nav in _NAV_OPTIONS
        else (
            _NAV_OPTIONS.index(st.session_state.get("view", _NAV_OPTIONS[0]))
            if st.session_state.get("view") in _NAV_OPTIONS
            else 0
        )
    )
    view: str = st.radio(
        "nav", _NAV_OPTIONS, index=_nav_idx, key="view", label_visibility="collapsed",
    )

    if "Trace" in view:
        st.markdown('<div style="height:8px"/>', unsafe_allow_html=True)
        st.text_input(
            "jump", value="", key="manual_sid", placeholder="Paste session ID…",
            label_visibility="collapsed",
        )

    st.markdown('<hr style="margin:20px 0 12px"/>', unsafe_allow_html=True)
    st.markdown(
        '<p style="font-size:11px;color:#94a3b8;padding:0 4px;line-height:1.7">'
        'Evals every 30s&nbsp;·&nbsp;Patterns hourly</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<a href="http://localhost:8000/docs" target="_blank" '
        'style="font-size:11px;color:#94a3b8;text-decoration:none;padding:0 4px">'
        '→ API docs</a>',
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


def _plotly_defaults(fig: go.Figure, height: int = 220) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=0, r=0, t=8, b=0),
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Inter, -apple-system, sans-serif", size=12, color="#475569"),
        xaxis=dict(gridcolor="#f1f5f9", linecolor="#e2e8f0", showline=True),
        yaxis=dict(gridcolor="#f1f5f9", linecolor="#e2e8f0"),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
            font=dict(size=11),
        ),
        hoverlabel=dict(bgcolor="white", font_size=12, bordercolor="#e2e8f0"),
    )
    return fig


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW 1 — Overview
# ═══════════════════════════════════════════════════════════════════════════════
def _show_overview(agent_id: str) -> None:
    _page_header("Agent Overview", "Quality, latency, and failure breakdown for the last 24 hours")

    db = _db()
    try:
        stats = get_todays_stats(agent_id, db)
        extra = get_session_and_latency_stats(agent_id, 24, db)
        trend = get_quality_trend(agent_id, TREND_DAYS, db)
        top_types = get_top_failure_types(agent_id, 24, db)
        step_hot = get_failures_by_step(agent_id, 24, db)
        patterns = get_patterns_for_agent(agent_id, db)
        latencies = get_latency_values(agent_id, 24, db)
        score_buckets = get_score_buckets(agent_id, 24, db)
    finally:
        db.close()

    failures_24h = stats["total"] - stats["passed"]
    pass_pct = stats["pass_rate"] * 100

    if failures_24h == 0 and stats["total"] > 0:
        st.success("No failures in the last 24 hours — your agent is healthy.", icon="✅")

    # ── KPI row ─────────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Sessions (24h)", extra["session_count"])
    k2.metric("Pass Rate", f"{pass_pct:.0f}%",
              delta=f"{stats['passed']} passed · {failures_24h} failed")
    k3.metric("Avg Score", f"{extra['avg_score']:.0f}/100")
    k4.metric("Avg Latency", f"{extra['avg_latency_ms']} ms")

    # Latency P99
    p99 = int(np.percentile(latencies, 99)) if latencies else 0
    k5.metric("P99 Latency", f"{p99} ms", help="99th percentile step latency")

    # Color pass rate
    color = "#16a34a" if pass_pct >= 70 else "#dc2626"
    st.markdown(
        f"<style>[data-testid='stMetric']:nth-child(2) "
        f"[data-testid='stMetricValue'] > div {{ color: {color} !important; }}</style>",
        unsafe_allow_html=True,
    )

    # ── Two main charts ──────────────────────────────────────────────────────
    _section_head("Trend & Distribution", f"last {TREND_DAYS} days quality, last 24h scores")
    ch1, ch2 = st.columns([3, 2])

    with ch1:
        if trend:
            df_t = pd.DataFrame(trend)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_t["date"], y=(df_t["avg_score"] * 100).round(1),
                name="Avg Score", mode="lines+markers",
                line=dict(color="#6366f1", width=2.5),
                marker=dict(size=5),
                hovertemplate="%{y:.0f}/100<extra>Avg Score</extra>",
            ))
            fig.add_trace(go.Scatter(
                x=df_t["date"], y=(df_t["pass_rate"] * 100).round(1),
                name="Pass Rate %", mode="lines+markers",
                line=dict(color="#22c55e", width=2, dash="dot"),
                marker=dict(size=5),
                hovertemplate="%{y:.0f}%<extra>Pass Rate</extra>",
            ))
            fig.add_hline(y=70, line_dash="dash", line_color="#ef4444", line_width=1,
                          annotation_text="Pass threshold", annotation_position="right",
                          annotation_font_size=10, annotation_font_color="#ef4444")
            _plotly_defaults(fig, 200).update_layout(yaxis=dict(range=[0, 105]))
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.caption("No evaluation data yet.")

    with ch2:
        if score_buckets:
            df_b = pd.DataFrame(score_buckets)
            colors = [
                "#ef4444" if b < 50 else "#f97316" if b < 70 else "#22c55e"
                for b in df_b["bucket"]
            ]
            fig2 = go.Figure(go.Bar(
                x=df_b["range"], y=df_b["count"],
                marker_color=colors,
                text=df_b["count"], textposition="outside",
                textfont=dict(size=11, color="#475569"),
                hovertemplate="%{x}: %{y} sessions<extra></extra>",
            ))
            _plotly_defaults(fig2, 200).update_layout(
                yaxis_title="sessions",
                xaxis=dict(tickfont=dict(size=10)),
            )
            st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})
        else:
            st.caption("No score data yet.")

    # ── Latency percentiles ──────────────────────────────────────────────────
    if latencies:
        _section_head("Latency Profile", "step execution time distribution")
        arr = np.array(latencies)
        pcts = [50, 75, 90, 95, 99]
        vals = [int(np.percentile(arr, p)) for p in pcts]

        fig3 = go.Figure(go.Bar(
            x=[f"P{p}" for p in pcts], y=vals,
            marker_color=["#6366f1", "#8b5cf6", "#f59e0b", "#f97316", "#ef4444"],
            text=[f"{v:,} ms" for v in vals],
            textposition="outside",
            textfont=dict(size=11, color="#475569"),
            hovertemplate="%{x}: %{y} ms<extra></extra>",
        ))
        _plotly_defaults(fig3, 160).update_layout(
            yaxis_title="ms",
            bargap=0.4,
            xaxis=dict(tickfont=dict(size=12, color="#0f172a")),
        )
        pcol1, pcol2 = st.columns([2, 3])
        with pcol1:
            pc1, pc2, pc3 = st.columns(3)
            pc1.metric("P50", f"{vals[0]} ms")
            pc2.metric("P95", f"{vals[3]} ms")
            pc3.metric("P99", f"{vals[4]} ms")
        with pcol2:
            st.plotly_chart(fig3, use_container_width=True, config={"displayModeBar": False})

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
            # Donut chart
            fig_d = go.Figure(go.Pie(
                labels=[ft for ft, _, _ in top_types],
                values=[cnt for _, cnt, _ in top_types],
                hole=0.55,
                marker_colors=[_ft_color(ft)[0] for ft, _, _ in top_types],
                textinfo="label+percent",
                textfont=dict(size=11),
                hovertemplate="%{label}: %{value}<extra></extra>",
            ))
            fig_d.update_layout(
                height=180, margin=dict(l=0, r=0, t=0, b=0),
                paper_bgcolor="white",
                font=dict(family="Inter, sans-serif", size=11),
                showlegend=False,
            )
            st.plotly_chart(fig_d, use_container_width=True, config={"displayModeBar": False})
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
def _failure_feed_fragment(agent_id: str, _unused: str) -> None:
    db = _db()
    try:
        patterns = get_patterns_for_agent(agent_id, db)
        recent = get_recent_eval_failures(agent_id, 50, db)
    finally:
        db.close()

    if not patterns and not recent:
        st.success("No failures found for this agent.", icon="✅")
        return

    # ── Tabs: one thing at a time ─────────────────────────────────────────────
    tab_patterns, tab_recent = st.tabs([
        f"⚠  Patterns  ({len(patterns)})",
        f"🔴  Recent failures  ({len(recent)})",
    ])

    with tab_patterns:
        if not patterns:
            st.info("No recurring patterns yet — patterns form once 5+ failures share a root cause.")
        else:
            st.markdown(
                '<p style="font-size:13px;color:#64748b;margin:8px 0 16px">'
                'These are repeated failures with the same root cause. Fix the top one first — '
                'it has the biggest impact.</p>',
                unsafe_allow_html=True,
            )
            for i, p in enumerate(patterns):
                _render_pattern_full(p, rank=i + 1)

    with tab_recent:
        if not recent:
            st.info("No recent failures.")
            return

        # Search + export row
        sc1, sc2 = st.columns([4, 1])
        search = sc1.text_input(
            "search", placeholder="Search failure reasons…", key="_feed_search",
            label_visibility="collapsed",
        )
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
        sc2.download_button(
            "⬇ CSV", data=pd.DataFrame(rows_csv).to_csv(index=False),
            file_name=f"agentiq-failures-{agent_id}.csv", mime="text/csv",
            use_container_width=True,
        )

        # Filter by search
        filtered = recent
        if search.strip():
            q = search.strip().lower()
            filtered = [
                (ev, log) for ev, log in recent
                if q in (ev.failure_reason or "").lower()
                or q in (ev.failure_type or "").lower()
                or q in log.step_name.lower()
            ]

        _plural = "s" if len(filtered) != 1 else ""
        _match = f' matching "{search}"' if search.strip() else ""
        st.markdown(
            f'<p style="font-size:12px;color:#94a3b8;margin:8px 0 12px">'
            f'{len(filtered)} failure{_plural}{_match}'
            f' · auto-refreshes every {AUTO_REFRESH_S}s</p>',
            unsafe_allow_html=True,
        )

        if not filtered:
            st.caption(f'No failures matching "{search}".')
            return

        for ev, log in filtered[:25]:
            _render_failure_row(ev, log)


def _render_pattern_full(p: Any, rank: int = 0) -> None:
    """Full readable pattern card for the Patterns tab."""
    ft = p.pattern_value
    fg, bg = _ft_color(ft)
    fix = _FIXES.get(ft, "Review agent logic.")
    worsening = (
        '<span style="background:#fef2f2;color:#dc2626;padding:2px 8px;border-radius:4px;'
        'font-size:11px;font-weight:700">▲ Getting worse</span>'
        if p.is_worsening else ""
    )

    with st.container(border=True):
        # Top row: rank + badge + share + worsening
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap">'
            f'<span style="font-size:13px;font-weight:800;color:#94a3b8">#{rank}</span>'
            f'{_badge(ft)}'
            f'<span style="font-size:14px;font-weight:800;color:{fg}">'
            f'{p.pct_of_all_failures * 100:.0f}% of all failures</span>'
            f'{worsening}'
            f'</div>',
            unsafe_allow_html=True,
        )
        # Root cause — large, readable
        st.markdown(
            f'<div style="font-size:15px;font-weight:600;color:#0f172a;margin-bottom:8px;line-height:1.5">'
            f'{p.root_cause or "No root cause identified."}'
            f'</div>',
            unsafe_allow_html=True,
        )
        # Fix — highlighted
        st.markdown(
            f'<div style="background:{bg};border-left:3px solid {fg};border-radius:0 8px 8px 0;'
            f'padding:10px 14px;font-size:13px;color:#1e293b;margin-bottom:10px">'
            f'<span style="font-weight:700;color:{fg}">How to fix: </span>{fix}'
            f'</div>',
            unsafe_allow_html=True,
        )
        # Stats footer
        st.markdown(
            f'<div style="font-size:12px;color:#94a3b8">'
            f'{p.failure_count} occurrences &nbsp;·&nbsp; '
            f'{p.failure_rate * 100:.0f}% fail rate &nbsp;·&nbsp; '
            f'First seen {_fmt_ts(p.first_seen)}'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.markdown('<div style="height:8px"/>', unsafe_allow_html=True)
        if st.button("See affected sessions →", key=f"pat_{p.id}"):
            st.session_state["pattern_filter"] = {"type": p.pattern_type, "value": p.pattern_value}
            st.session_state["selected_session"] = None
            st.session_state["view"] = "🔍  Trace Viewer"
            st.rerun(scope="app")


def _render_failure_row(ev: Any, log: Any) -> None:
    """Clean single row for the Recent Failures tab."""
    score = int(round(ev.overall_score * 100))
    ft = ev.failure_type or "unknown"
    fg, _ = _ft_color(ft)

    with st.container(border=True):
        lc, rc = st.columns([6, 1])
        with lc:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap">'
                f'{_badge(ft)}'
                f'<span style="font-size:13px;font-weight:700;color:{fg}">{score}/100</span>'
                f'<span style="font-size:12px;color:#94a3b8">{_fmt_ts(ev.evaluated_at)}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            reason = ev.failure_reason or ft
            st.markdown(
                f'<div style="font-size:14px;color:#1e293b;font-weight:500;margin-bottom:4px">'
                f'{reason}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div style="font-size:12px;color:#94a3b8">'
                f'Step {log.step_number} · {log.step_name}'
                f'</div>',
                unsafe_allow_html=True,
            )
        with rc:
            if st.button("Trace →", key=f"row_{ev.id}", use_container_width=True):
                st.session_state["selected_session"] = log.session_id
                st.session_state["view"] = "🔍  Trace Viewer"
                st.rerun(scope="app")


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
    _page_header("Failure Feed", "Recurring patterns and recent failures")
    _failure_feed_fragment(agent_id, "")


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW 3 — Trace Viewer
# ═══════════════════════════════════════════════════════════════════════════════
def _build_waterfall(steps: List[Tuple[Any, Optional[Any]]]) -> Optional[go.Figure]:
    """Build a Plotly Gantt/waterfall chart from session steps."""
    if not steps:
        return None

    # Compute cumulative start times
    cumulative = 0
    rows_data = []
    for log, ev in steps:
        latency = max(log.latency_ms or 0, 1)
        passed = ev.passed if ev else True
        failed = ev is not None and not ev.passed
        rows_data.append({
            "step": f"Step {log.step_number} · {log.step_name}",
            "start": cumulative,
            "end": cumulative + latency,
            "latency": latency,
            "passed": passed,
            "failed": failed,
            "score": int(round(ev.overall_score * 100)) if ev else None,
        })
        cumulative += latency

    fig = go.Figure()
    total_ms = cumulative

    for row in rows_data:
        color = "#ef4444" if row["failed"] else "#22c55e"
        score_text = f" · {row['score']}/100" if row["score"] is not None else ""

        fig.add_trace(go.Bar(
            name=row["step"],
            x=[row["latency"]],
            y=[row["step"]],
            base=[row["start"]],
            orientation="h",
            marker=dict(
                color=color,
                opacity=0.85,
                line=dict(color="white", width=1),
            ),
            text=f"{row['latency']} ms{score_text}",
            textposition="inside" if row["latency"] > total_ms * 0.08 else "outside",
            textfont=dict(size=11, color="white" if row["latency"] > total_ms * 0.08 else color),
            hovertemplate=(
                f"<b>{row['step']}</b><br>"
                f"Latency: {row['latency']} ms<br>"
                f"Start: {row['start']} ms<br>"
                + (f"Score: {row['score']}/100" if row['score'] is not None else "Pending eval")
                + "<extra></extra>"
            ),
            showlegend=False,
        ))

    fig.update_layout(
        height=max(160, len(rows_data) * 36 + 40),
        barmode="overlay",
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=0, r=0, t=8, b=0),
        font=dict(family="Inter, sans-serif", size=11, color="#475569"),
        xaxis=dict(
            title="Time (ms)", gridcolor="#f1f5f9", linecolor="#e2e8f0",
            showline=True, zeroline=False,
        ),
        yaxis=dict(
            autorange="reversed",
            gridcolor="#f1f5f9",
            tickfont=dict(size=11),
        ),
        hoverlabel=dict(bgcolor="white", font_size=12, bordercolor="#e2e8f0"),
    )
    return fig


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
    _page_header("Trace Viewer", "Step-by-step waterfall trace with scores and diagnosis")

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
    total_ms = sum(log.latency_ms or 0 for log, _ in steps)

    # Session banner
    st.markdown(
        f"""
        <div style="background:white;border:1px solid #e2e8f0;border-radius:14px;
                    padding:20px 24px;display:flex;justify-content:space-between;
                    align-items:center;margin-bottom:20px;
                    box-shadow:0 1px 3px rgba(15,23,42,0.05)">
          <div>
            <div style="font-size:10px;font-weight:700;color:#64748b;letter-spacing:0.08em;
                        text-transform:uppercase;margin-bottom:4px">Session</div>
            <code style="font-size:13px;color:#1e293b;background:transparent;padding:0">{session_id}</code>
            <div style="font-size:12px;color:#94a3b8;margin-top:6px">
              {len(steps)} steps · {len(failed_steps)} failed · {total_ms:,} ms total
            </div>
          </div>
          <div style="text-align:right">
            <div style="font-size:40px;font-weight:900;color:{score_color};
                        letter-spacing:-0.04em;line-height:1">
              {session_score}
              <span style="font-size:18px;font-weight:400;color:#94a3b8">/100</span>
            </div>
            <div style="font-size:12px;font-weight:700;color:{score_color};
                        letter-spacing:0.06em">{"FAILED" if is_failed else "PASSED"}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Waterfall chart ──────────────────────────────────────────────────────
    _section_head("Execution Waterfall", "step timing — width = latency")
    waterfall = _build_waterfall(steps)
    if waterfall:
        st.plotly_chart(
            waterfall, use_container_width=True, config={"displayModeBar": False}
        )
        # Legend
        st.markdown(
            '<div style="display:flex;gap:16px;margin:-8px 0 12px;font-size:11px;color:#64748b">'
            '<span><span style="background:#22c55e;border-radius:3px;display:inline-block;width:12px;height:12px;vertical-align:middle"></span> Passed</span>'
            '<span><span style="background:#ef4444;border-radius:3px;display:inline-block;width:12px;height:12px;vertical-align:middle"></span> Failed</span>'
            '</div>',
            unsafe_allow_html=True,
        )

    # ── Step details ──────────────────────────────────────────────────────────
    _section_head("Step Details", "expand to see input/output")

    for log, ev in steps:
        passed = ev.passed if ev is not None else True
        score = int(round(ev.overall_score * 100)) if ev else None
        border = "#ef4444" if (ev and not passed) else "#22c55e" if (ev and passed) else "#e2e8f0"
        step_bg = "#fef2f2" if (ev and not passed) else "white"
        ev_badge_html = f'&nbsp;&nbsp;{_score_chip(score, passed)}' if score is not None else ""
        ft_html = ""
        if ev and not ev.passed:
            ft_html = (
                f'<div style="font-size:12px;color:#64748b;margin-top:6px">'
                f'{_badge((ev.failure_type or "unknown"), "11px")}'
                f'&nbsp;&nbsp;{ev.failure_reason or ""}'
                f'</div>'
            )

        st.markdown(
            f"""
            <div style="background:{step_bg};border:1px solid #e2e8f0;border-left:4px solid {border};
                        border-radius:0 12px 12px 0;padding:14px 18px;margin:6px 0">
              <div style="display:flex;justify-content:space-between;align-items:center">
                <div>
                  <span style="font-size:10px;color:#94a3b8;font-weight:700;text-transform:uppercase;
                               letter-spacing:0.08em">Step {log.step_number}</span>
                  <span style="font-size:15px;font-weight:700;color:#1e293b;margin-left:10px">{log.step_name}</span>
                  <span style="font-size:11px;color:#94a3b8;margin-left:10px">{log.latency_ms:,} ms</span>
                </div>
                {ev_badge_html}
              </div>
              {ft_html}
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

        with st.expander(f"Input / Output  ·  {log.latency_ms:,} ms", expanded=False):
            ic, oc = st.columns(2)
            with ic:
                st.markdown(
                    '<p style="font-size:10px;font-weight:700;color:#64748b;'
                    'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px">Input</p>',
                    unsafe_allow_html=True,
                )
                st.code(log.input[:1200] + ("…" if len(log.input) > 1200 else ""), language=None)
            with oc:
                st.markdown(
                    '<p style="font-size:10px;font-weight:700;color:#64748b;'
                    'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px">Output</p>',
                    unsafe_allow_html=True,
                )
                st.code(log.output[:1200] + ("…" if len(log.output) > 1200 else ""), language=None)
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

    # ── Diagnosis ─────────────────────────────────────────────────────────────
    diag = _build_diagnosis(steps)
    if diag:
        st.markdown(
            f"""
            <div style="background:white;border:1px solid #e2e8f0;border-radius:14px;
                        padding:20px 24px;margin-top:16px;
                        box-shadow:0 1px 3px rgba(15,23,42,0.05)">
              <div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;
                          letter-spacing:0.08em;margin-bottom:10px">Root Cause</div>
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

    # Filter row
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
        st.info("No failing sessions match the current filters. Try expanding the time range.")
        return

    st.markdown(
        f'<p style="font-size:12px;color:#94a3b8;margin:12px 0 8px">'
        f'{len(sessions)} session{"s" if len(sessions) != 1 else ""} · click a row to open its trace</p>',
        unsafe_allow_html=True,
    )

    # Build a proper dataframe table
    df_rows = [
        {
            "When": _fmt_ts(s["failed_at"]),
            "Failure type": s["failure_type"] or "unknown",
            "Step": s["failure_step"] or "—",
            "Score": int(s["overall_score"] * 100),
            "Root cause": (s["failure_reason"] or "")[:70],
            "_session_id": s["session_id"],
        }
        for s in sessions
    ]
    df = pd.DataFrame(df_rows)
    display_df = df.drop(columns=["_session_id"])

    # Show table, then per-row open buttons below
    st.dataframe(
        display_df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Score": st.column_config.ProgressColumn(
                "Score", format="%d/100", min_value=0, max_value=100,
            ),
            "When": st.column_config.TextColumn("When", width="small"),
            "Failure type": st.column_config.TextColumn("Type", width="medium"),
            "Step": st.column_config.NumberColumn("Step", width="small"),
            "Root cause": st.column_config.TextColumn("Root Cause", width="large"),
        },
    )

    # Quick-open buttons under the table
    st.markdown(
        '<p style="font-size:11px;color:#94a3b8;margin:8px 0 4px">Open a session:</p>',
        unsafe_allow_html=True,
    )
    btn_cols = st.columns(min(len(sessions), 6))
    for i, s in enumerate(sessions[:6]):
        ft = s["failure_type"] or "?"
        fg, _ = _ft_color(ft)
        with btn_cols[i]:
            if st.button(
                f"{ft[:12]}\n{int(s['overall_score']*100)}/100",
                key=f"open_{s['session_id']}",
                use_container_width=True,
            ):
                st.session_state["selected_session"] = s["session_id"]
                st.rerun()

    # If more than 6, show a selectbox
    if len(sessions) > 6:
        st.markdown('<div style="height:8px"/>', unsafe_allow_html=True)
        chosen = st.selectbox(
            "Or pick any session:",
            options=[s["session_id"] for s in sessions],
            format_func=lambda sid: f"{sid[:28]}… — {next((s['failure_type'] or '?' for s in sessions if s['session_id']==sid), '?')}",
            key="session_picker",
            index=None,
            placeholder="Select session ID…",
        )
        if chosen:
            st.session_state["selected_session"] = chosen
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
