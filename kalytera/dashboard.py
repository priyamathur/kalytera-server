"""
agentiq/dashboard.py — three views
Run: streamlit run agentiq/dashboard.py --server.port 8501
"""
import html
import json
import os
import re
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
    page_title="Kalytera",
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
    "tool_failure":  "Add exit-code checks after every bash/tool call — retry once, then report the failure explicitly.",
    "wrong_answer":  "Verify the agent reads the actual file before writing a fix — wrong outputs usually mean unread context.",
    "goal_drift":    "Re-inject the original task description at each step so the agent cannot drift to unrelated issues.",
    "hallucination": "Require the agent to look up imports and API signatures in the codebase before using them.",
    "context_loss":  "Pass the full file path, line numbers, and prior diffs into every step — don't rely on short-term memory.",
    "incomplete":    "Add a completion checklist: tests passing, changes committed, PR opened — verify all three before closing.",
    "loop":          "Track executed commands in a set per session — halt and surface an error after the same command runs 3×.",
}

_FIX_STEP: Dict[str, str] = {
    "tool_failure":  "Check exit code and retry at **{step}**.",
    "wrong_answer":  "Read the target file before writing at **{step}**.",
    "goal_drift":    "Re-inject original task spec before **{step}**.",
    "hallucination": "Verify import/API exists in repo before **{step}**.",
    "context_loss":  "Pass file path and prior diff into **{step}**.",
    "incomplete":    "Add commit + PR check after **{step}**.",
    "loop":          "Add command dedup guard before **{step}**.",
}

_FIX_TRACE: Dict[str, str] = {
    "tool_failure":  "Check the exit code from **{s}** — add a retry and surface the stderr if it fails again.",
    "wrong_answer":  "Review what the agent read before **{s}** — the output contradicts what is in the file.",
    "goal_drift":    "Prepend the original issue/task spec to **{s}** — the agent lost its objective.",
    "hallucination": "Grep the codebase for the import used at **{s}** — the agent invented a nonexistent API.",
    "context_loss":  "Confirm the file path and prior changes are passed into **{s}** — agent has no context.",
    "incomplete":    "Add a post-step check after **{s}**: verify commit hash exists and PR is open.",
    "loop":          "Log commands executed before **{s}** — break if the same command has already run this session.",
}

ALL_FT = [
    "tool_failure", "wrong_answer", "goal_drift",
    "incomplete", "hallucination", "context_loss", "loop",
]

AUTO_REFRESH_S = 30
TREND_DAYS = 7
SESSION_LIMIT = 100
PATTERN_SESSIONS_SHOWN = 10
SEARCH_LIMIT = 20
OVERVIEW_CACHE_S = 30

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
    """HTML: the trace view renders this inside HTML, where **bold** would show literally."""
    text = _FIX_TRACE.get(ft or "", "Review agent logic at **{s}**.").format(s=html.escape(step))
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def _short_reason(reason: Optional[str], ft: Optional[str], step_name: str) -> str:
    """Return a concise one-line failure reason for cards/feed — never a paragraph."""
    if not reason:
        return f"{ft or 'failure'} at {step_name}"
    # Take text up to the first sentence break
    for sep in (". ", "; ", "\n"):
        idx = reason.find(sep)
        if 0 < idx < 120:
            return reason[:idx + 1].strip()
    # Hard truncate at 100 chars
    return reason[:100].rstrip(" ,") + ("…" if len(reason) > 100 else "")


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
    get_agent_ids_for_org,
    get_all_agent_ids,
    get_avg_score_by_step,
    get_calibration_stats,
    get_failures_by_step,
    get_golden_label,
    get_latency_values,
    get_patterns_for_agent,
    get_quality_config,
    get_quality_trend,
    get_recent_eval_failures,
    get_pattern_sessions,
    get_session_failure_counts,
    get_step_names,
    step_label,
    get_score_buckets,
    get_session_and_latency_stats,
    get_session_steps,
    get_todays_stats,
    get_top_failure_types,
    search_sessions,
    upsert_golden_label,
    upsert_quality_config,
)

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
.stButton > button[kind="primary"] {
    background: #6366f1 !important; border-color: #6366f1 !important; color: white !important;
}
.stButton > button[kind="primary"]:hover {
    background: #4f46e5 !important; border-color: #4f46e5 !important; color: white !important;
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

/* ── Sidebar: hide collapse button so sidebar is always open ── */
/* Collapse button inside expanded sidebar */
section[data-testid="stSidebar"] button[data-testid="stBaseButton-headerNoPadding"],
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"],
section[data-testid="stSidebar"] button[kind="header"] {
    display: none !important;
}
/* Expand button when sidebar is collapsed (fallback) */
section[data-testid="stSidebarCollapsedControl"],
div[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"] {
    display: none !important;
}
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH GATE — API key login, validated against /billing/usage
# ═══════════════════════════════════════════════════════════════════════════════
import requests as _requests

from kalytera.dashboard_rules import (  # noqa: E402
    API as _API, _api as _rules_api, create_rule, fetch_suggestion_data, promote_rule, sentence, show_rules,
    try_rule,
)


def _validate_key(key: str) -> Optional[Dict[str, Any]]:
    try:
        r = _requests.get(
            f"{_API}/billing/usage",
            headers={"Authorization": f"Bearer {key}"},
            timeout=5,
        )
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def _agents_for_key(key: str) -> List[str]:
    """Agents the key can see. Cached: this ran on every click and is one network round trip."""
    try:
        r = _requests.get(f"{_API}/agents", headers={"Authorization": f"Bearer {key}"}, timeout=5)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


if not st.session_state.get("authenticated"):
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown('<div style="height:72px"/>', unsafe_allow_html=True)
        st.markdown("""
        <div style="text-align:center;margin-bottom:32px">
          <div style="display:inline-flex;align-items:center;gap:10px;margin-bottom:18px">
            <div style="background:linear-gradient(135deg,#6366f1,#8b5cf6);width:42px;height:42px;
                        border-radius:11px;display:flex;align-items:center;justify-content:center;
                        font-size:26px;box-shadow:0 2px 10px rgba(99,102,241,0.3)">⚡</div>
            <div style="font-size:28px;font-weight:900;color:#0f172a;letter-spacing:-0.03em">Kalytera</div>
          </div>
          <div style="font-size:22px;font-weight:800;color:#0f172a;margin-bottom:6px">Welcome back</div>
          <div style="font-size:14px;color:#64748b;line-height:1.5">
            Paste your API key to access your dashboard.<br/>
            <span style="font-size:12px">No password needed — your key is your login.</span>
          </div>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form"):
            _key_input = st.text_input(
                "API key",
                type="password",
                placeholder="kly_live_...",
                label_visibility="collapsed",
            )
            _submitted = st.form_submit_button("Sign in →", use_container_width=True)

        if _submitted:
            if not _key_input.startswith("kly_live_"):
                st.error("That doesn't look right — Kalytera API keys start with `kly_live_`")
            else:
                with st.spinner("Verifying…"):
                    _usage = _validate_key(_key_input)
                if _usage:
                    st.session_state.update({
                        "authenticated": True,
                        "api_key": _key_input,
                        "org_id": _usage.get("org_id", ""),
                        "org_name": _usage.get("org_name", ""),
                        "tier": _usage.get("tier", "free"),
                        "sessions_used": _usage.get("sessions_used", 0),
                        "sessions_limit": _usage.get("sessions_limit", 10000),
                    })
                    st.rerun()
                else:
                    st.error("Invalid key. Check it at kalytera.dev or email priya@kalytera.ai")

        st.markdown("""
        <div style="text-align:center;margin-top:20px;font-size:12px;color:#94a3b8">
          No key yet?
          <a href="https://kalytera.dev" target="_blank"
             style="color:#6366f1;font-weight:600;text-decoration:none">
            Get one free at kalytera.dev →
          </a>
        </div>
        """, unsafe_allow_html=True)

    st.stop()


# A finished sample run switches agent and page; widgets can only be set before they render.
_switch = st.session_state.pop("_switch_to", None)
if _switch:
    _agents_for_key.clear()
    st.session_state["agent_id"], st.session_state["view"] = _switch
    st.session_state.pop("open_session", None)

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
              <div style="font-size:19px;font-weight:900;color:#0f172a;letter-spacing:-0.03em">Kalytera</div>
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
    _stored_key = st.session_state.get("api_key", "")
    if _stored_key:
        _all_agents = _agents_for_key(_stored_key)
    else:
        _db_s = _db()
        try:
            _all_agents = get_all_agent_ids(_db_s)
        except Exception:
            _all_agents = []
        finally:
            _db_s.close()

    if _all_agents:
        # The API lists your own agents first; the shared demo agent only when you have none.
        _own = [a for a in _all_agents if a != "demo-agent"]
        _def = _all_agents.index(_own[0]) if _own else 0
        if st.session_state.get("agent_id") not in _all_agents:
            st.session_state["agent_id"] = _all_agents[_def]
        agent_id: str = st.selectbox(
            "agent", _all_agents, key="agent_id", label_visibility="collapsed",
            on_change=lambda: st.session_state.pop("open_session", None),
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
    _NAV_OPTIONS = ["📊  Overview", "🔴  Failure Feed", "🛡  Rules"]
    if st.session_state.get("view") not in _NAV_OPTIONS:
        st.session_state.pop("view", None)  # e.g. the old Trace Viewer entry
    view: str = st.radio(
        "nav", _NAV_OPTIONS, key="view", label_visibility="collapsed",
        on_change=lambda: st.session_state.pop("open_session", None),
    )

    if _stored_key and not any(a.startswith("sample-refund-bot-") for a in _all_agents or []) \
            and any(a != "demo-agent" for a in _all_agents or []):
        st.markdown('<div style="height:8px"/>', unsafe_allow_html=True)
        st.button("▶ Try the sample agent", key="sidebar_sample", use_container_width=True,
                  on_click=st.session_state.__setitem__, args=("_want_sample", True),
                  help="See Kalytera find a failing agent's problem and block it — about 2 minutes")

    st.markdown('<hr style="margin:20px 0 12px"/>', unsafe_allow_html=True)

    # ── Org info + usage bar ──────────────────────────────────────────────────
    _org = st.session_state.get("org_name", "")
    _tier = st.session_state.get("tier", "free")
    _used = st.session_state.get("sessions_used", 0)
    _limit = st.session_state.get("sessions_limit", 10000)
    _pct = min(round(_used / _limit * 100) if _limit else 0, 100)
    _bar_color = "#ef4444" if _pct >= 90 else "#6366f1"
    st.markdown(
        f"""
        <div style="padding:11px 13px;background:#f8fafc;border-radius:10px;
                    border:1px solid #e2e8f0;margin-bottom:10px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
            <span style="font-size:11px;color:#94a3b8;font-weight:700;
                         text-transform:uppercase;letter-spacing:0.08em">{_tier}</span>
            <span style="font-size:11px;color:#64748b">{_used:,} / {_limit:,}</span>
          </div>
          <div style="background:#e2e8f0;border-radius:4px;height:4px">
            <div style="background:{_bar_color};width:{_pct}%;height:4px;border-radius:4px"></div>
          </div>
          {"" if not _org else f'<div style="font-size:11px;color:#94a3b8;margin-top:5px">{_org}</div>'}
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Sign out", use_container_width=True, key="signout_btn"):
        for _k in ["authenticated", "api_key", "org_name", "tier", "sessions_used", "sessions_limit"]:
            st.session_state.pop(_k, None)
        st.rerun()

    st.markdown(
        '<p style="font-size:11px;color:#94a3b8;padding:4px 4px 0;line-height:1.7">'
        'Evals every 30s&nbsp;·&nbsp;Patterns hourly</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<a href="https://api.kalytera.dev/docs" target="_blank" '
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


def _kpi_card(label: str, value: str, subtitle: str, color: str = "#0f172a") -> str:
    return (
        f'<div style="background:white;border:1px solid #e2e8f0;border-radius:14px;'
        f'padding:20px 22px 16px;box-shadow:0 1px 3px rgba(15,23,42,0.06);height:100%">'
        f'<div style="font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;'
        f'letter-spacing:0.08em;margin-bottom:8px">{label}</div>'
        f'<div style="font-size:28px;font-weight:800;color:{color};letter-spacing:-0.03em;'
        f'line-height:1.1;margin-bottom:5px">{value}</div>'
        f'<div style="font-size:10px;color:#94a3b8;font-style:italic">{subtitle}</div>'
        f'</div>'
    )


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW 1 — Overview
# ═══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=OVERVIEW_CACHE_S, show_spinner=False)
def _overview_data(agent_id: str, hours: int) -> Tuple[Any, ...]:
    """Every Overview query in one cached call, so switching pages back here is instant."""
    calib_default = {"total_labeled": 0, "agreement_count": 0, "agreement_rate": None, "status": "unlabeled"}
    db = _db()
    try:
        try:
            calib = get_calibration_stats(agent_id, db)
        except Exception:
            calib = calib_default
        return (
            get_todays_stats(agent_id, db, hours=hours),
            get_session_and_latency_stats(agent_id, hours, db),
            get_quality_trend(agent_id, TREND_DAYS, db),
            get_top_failure_types(agent_id, hours, db),
            get_failures_by_step(agent_id, hours, db),
            get_latency_values(agent_id, hours, db),
            get_score_buckets(agent_id, hours, db),
            get_avg_score_by_step(agent_id, hours, db),
            calib,
        )
    finally:
        db.close()


def _show_overview(agent_id: str) -> None:
    _hours_map = {"24h": 24, "7 days": 168, "30 days": 720}
    hdr_col, filter_col = st.columns([5, 1])
    with hdr_col:
        _page_header("Agent Overview", "Quality, latency, and failure breakdown")
    with filter_col:
        st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)
        sel_label = st.selectbox(
            "Range", list(_hours_map.keys()), index=1,
            key="overview_time_range", label_visibility="collapsed",
        )
    sel_hours = _hours_map[sel_label]

    (stats, extra, trend, top_types, step_hot, latencies,
     score_buckets, step_scores, calib) = _overview_data(agent_id, sel_hours)

    failures_n = stats["total"] - stats["passed"]
    pass_pct = stats["pass_rate"] * 100
    arr = np.array(latencies) if latencies else np.array([0])
    p_vals = [int(np.percentile(arr, p)) for p in [50, 75, 90, 95, 99]]

    if failures_n == 0 and stats["total"] > 0:
        st.success(f"No failed sessions in the {sel_label} — your agent is healthy.", icon="✅")

    # ── KPI row ─────────────────────────────────────────────────────────────
    pass_color = "#16a34a" if pass_pct >= 70 else "#dc2626"
    fail_color = "#dc2626" if failures_n > 0 else "#16a34a"
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.markdown(_kpi_card("Sessions", str(extra["session_count"]), f"distinct sessions, {sel_label}"), unsafe_allow_html=True)
    k2.markdown(_kpi_card("Pass Rate", f"{pass_pct:.0f}%", "score ≥ 70", color=pass_color), unsafe_allow_html=True)
    k3.markdown(_kpi_card("Avg Score", f"{extra['avg_score']:.0f}/100", "weighted 4 dims"), unsafe_allow_html=True)
    k4.markdown(_kpi_card("Failed sessions", str(failures_n), f"{_pct(failures_n, stats['total'])} of sessions, {sel_label}", color=fail_color), unsafe_allow_html=True)
    k5.markdown(_kpi_card("Avg Latency", f"{extra['avg_latency_ms']:,} ms", "mean per step"), unsafe_allow_html=True)
    _CALIB_COLOR = {"excellent": "#16a34a", "good": "#0891b2", "needs_calibration": "#dc2626", "unlabeled": "#6366f1"}
    _CALIB_LABEL = {"excellent": "Calibrated ✓", "good": "Good", "needs_calibration": "Review weights", "unlabeled": "Not yet labeled"}
    calib_status = calib["status"]
    calib_val = f"{calib['agreement_rate']*100:.0f}%" if calib["agreement_rate"] is not None else "—"
    calib_sub = f"{calib['total_labeled']} sessions labeled · {_CALIB_LABEL[calib_status]}" if calib["total_labeled"] > 0 else "Open a session (search ↗) → label 👍👎"
    k6.markdown(_kpi_card("Judge Accuracy", calib_val, calib_sub, color=_CALIB_COLOR[calib_status]), unsafe_allow_html=True)

    # ── Quality trend + session volume ───────────────────────────────────────
    _section_head("Quality Trend", f"last {TREND_DAYS} days — avg score · pass rate")
    ch1, ch2 = st.columns([3, 2])

    with ch1:
        if trend:
            df_t = pd.DataFrame(trend)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_t["date"], y=(df_t["avg_score"] * 100).round(1),
                name="Avg Score",
                mode="lines",
                fill="tozeroy",
                fillcolor="rgba(99,102,241,0.10)",
                line=dict(color="#6366f1", width=2.5),
                hovertemplate="%{y:.0f}/100<extra>Avg Score</extra>",
            ))
            fig.add_trace(go.Scatter(
                x=df_t["date"], y=(df_t["pass_rate"] * 100).round(1),
                name="Pass Rate %",
                mode="lines+markers",
                line=dict(color="#22c55e", width=2, dash="dot"),
                marker=dict(size=4),
                hovertemplate="%{y:.0f}%<extra>Pass Rate</extra>",
            ))
            fig.add_hline(y=70, line_dash="dash", line_color="#ef4444", line_width=1,
                          annotation_text="70 — pass threshold",
                          annotation_position="bottom right",
                          annotation_font_size=10, annotation_font_color="#ef4444")
            _plotly_defaults(fig, 230).update_layout(
                xaxis=dict(title="Date", gridcolor="#f1f5f9", linecolor="#e2e8f0"),
                yaxis=dict(title="Score / Pass %", range=[0, 108],
                           gridcolor="#f1f5f9", linecolor="#e2e8f0"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02,
                            xanchor="right", x=1, font=dict(size=11)),
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.caption("No evaluation data yet.")

    with ch2:
        if score_buckets:
            df_b = pd.DataFrame(score_buckets)
            colors_b = [
                "#ef4444" if b < 50 else "#f97316" if b < 70 else "#22c55e"
                for b in df_b["bucket"]
            ]
            fig2 = go.Figure(go.Bar(
                x=df_b["range"], y=df_b["count"],
                marker_color=colors_b,
                text=df_b["count"], textposition="outside",
                textfont=dict(size=11, color="#475569"),
                hovertemplate="Score %{x}: %{y} sessions<extra></extra>",
            ))
            _plotly_defaults(fig2, 230).update_layout(
                yaxis=dict(title="Sessions", gridcolor="#f1f5f9", linecolor="#e2e8f0"),
                xaxis=dict(title="Score range (0–100)", tickfont=dict(size=10),
                           gridcolor="#f1f5f9", linecolor="#e2e8f0"),
                showlegend=False,
                margin=dict(l=10, r=10, t=8, b=50),
            )
            st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})
        else:
            st.caption("No score data yet.")

    # ── Latency ─────────────────────────────────────────────────────────────
    if latencies:
        _section_head("Latency", f"step response time percentiles — {sel_label}")
        lc1, lc2, lc3, lc4 = st.columns(4)
        lc1.markdown(_kpi_card("P50", f"{p_vals[0]:,} ms", "median response"), unsafe_allow_html=True)
        lc2.markdown(_kpi_card("P75", f"{p_vals[1]:,} ms", "75th percentile", color="#8b5cf6"), unsafe_allow_html=True)
        lc3.markdown(_kpi_card("P95", f"{p_vals[3]:,} ms", "95th percentile", color="#f97316"), unsafe_allow_html=True)
        lc4.markdown(_kpi_card("P99", f"{p_vals[4]:,} ms", "worst 1% of steps", color="#ef4444"), unsafe_allow_html=True)

    # ── Quality Score by Step ────────────────────────────────────────────────
    if step_scores:
        _section_head("Quality Score by Step", "avg score per workflow step — red steps are your biggest quality risk")
        y_steps  = [s for s, _, _ in step_scores]
        x_scores = [round(sc * 100) for _, sc, _ in step_scores]
        x_counts = [cnt for _, _, cnt in step_scores]
        bar_clrs = [
            "#ef4444" if sc < 50 else "#f97316" if sc < 70 else "#22c55e"
            for sc in x_scores
        ]
        fig_sq = go.Figure(go.Bar(
            x=x_scores,
            y=y_steps,
            orientation="h",
            marker_color=bar_clrs,
            marker_line=dict(color="white", width=1),
            customdata=x_counts,
            text=[f"{sc}/100  ·  {cnt} session{'s' if cnt != 1 else ''}" for sc, cnt in zip(x_scores, x_counts)],
            textposition="outside",
            textfont=dict(size=11, color="#475569"),
            hovertemplate="<b>%{y}</b><br>Avg score: %{x}/100<br>Based on %{customdata} session(s)<extra></extra>",
        ))
        fig_sq.add_vline(x=70, line_dash="dash", line_color="#ef4444", line_width=1,
                         annotation_text="pass threshold",
                         annotation_position="top left",
                         annotation_font_size=10, annotation_font_color="#ef4444")
        _plotly_defaults(fig_sq, max(160, len(step_scores) * 44)).update_layout(
            xaxis=dict(title="Avg quality score (0–100)", range=[0, 130],
                       gridcolor="#f1f5f9", linecolor="#e2e8f0"),
            yaxis=dict(tickfont=dict(size=12), linecolor="#e2e8f0", automargin=True),
            showlegend=False,
            margin=dict(l=10, r=130, t=8, b=40),
        )
        st.plotly_chart(fig_sq, use_container_width=True, config={"displayModeBar": False})

    # ── Failure Breakdown ─────────────────────────────────────────────────────
    _section_head("Failure Breakdown", sel_label)
    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown(
            '<p style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;'
            'letter-spacing:0.06em;margin-bottom:8px">By Workflow Step</p>',
            unsafe_allow_html=True,
        )
        if step_hot:
            rows_s = [
                {"Step": name, "Sessions failed": cnt, "% of sessions": f"{rate * 100:.0f}%"}
                for n, name, cnt, rate in step_hot
            ]
            st.dataframe(
                pd.DataFrame(rows_s),
                column_config={
                    "Step": st.column_config.TextColumn("Step"),
                    "Sessions failed": st.column_config.NumberColumn("Sessions failed", width="small"),
                    "% of sessions": st.column_config.TextColumn("% of sessions", width="small"),
                },
                hide_index=True, use_container_width=True,
            )
        else:
            st.caption(f"No failed sessions in the {sel_label}.")

    with col_r:
        st.markdown(
            '<p style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;'
            'letter-spacing:0.06em;margin-bottom:8px">By Failure Type</p>',
            unsafe_allow_html=True,
        )
        if top_types:
            sorted_types = list(reversed(top_types))
            y_labels = [ft for ft, _, _ in sorted_types]
            x_vals   = [cnt for _, cnt, _ in sorted_types]
            pct_vals  = [pct for _, _, pct in sorted_types]
            bar_colors = [_ft_color(ft)[0] for ft in y_labels]

            fig_ft = go.Figure(go.Bar(
                x=x_vals,
                y=y_labels,
                orientation="h",
                marker_color=bar_colors,
                marker_line=dict(color="white", width=1),
                text=[f"{v}  ({p * 100:.0f}%)" for v, p in zip(x_vals, pct_vals)],
                textposition="outside",
                textfont=dict(size=11, color="#475569"),
                hovertemplate="<b>%{y}</b><br>%{x} sessions<extra></extra>",
            ))
            chart_h = max(160, len(top_types) * 44)
            _plotly_defaults(fig_ft, chart_h).update_layout(
                xaxis=dict(title="Sessions with this failure", gridcolor="#f1f5f9", linecolor="#e2e8f0"),
                yaxis=dict(tickfont=dict(size=12), linecolor="#e2e8f0", automargin=True),
                showlegend=False,
                margin=dict(l=10, r=90, t=8, b=40),
            )
            st.plotly_chart(fig_ft, use_container_width=True, config={"displayModeBar": False})
        else:
            st.caption(f"No failed sessions in the {sel_label}.")

    # ── Scoring Configuration ─────────────────────────────────────────────────
    st.markdown('<div style="height:8px"/>', unsafe_allow_html=True)
    with st.expander("⚙  Scoring Configuration", expanded=False):
        db2 = _db()
        try:
            cfg = get_quality_config(agent_id, db2)
        finally:
            db2.close()

        _PRESETS: Dict[str, Dict[str, Any]] = {
            "Default":          dict(weight_accuracy=0.25, weight_goal_alignment=0.25, weight_decision=0.15, weight_completeness=0.15, weight_helpfulness=0.10, weight_factuality=0.10, pass_threshold=0.70),
            "Customer support": dict(weight_accuracy=0.20, weight_goal_alignment=0.35, weight_decision=0.15, weight_completeness=0.15, weight_helpfulness=0.10, weight_factuality=0.05, pass_threshold=0.70),
            "Healthcare":       dict(weight_accuracy=0.30, weight_goal_alignment=0.20, weight_decision=0.15, weight_completeness=0.10, weight_helpfulness=0.10, weight_factuality=0.15, pass_threshold=0.80),
            "Legal":            dict(weight_accuracy=0.30, weight_goal_alignment=0.25, weight_decision=0.15, weight_completeness=0.10, weight_helpfulness=0.05, weight_factuality=0.15, pass_threshold=0.80),
            "Sales":            dict(weight_accuracy=0.15, weight_goal_alignment=0.35, weight_decision=0.20, weight_completeness=0.15, weight_helpfulness=0.10, weight_factuality=0.05, pass_threshold=0.65),
            "Coding assistant": dict(weight_accuracy=0.30, weight_goal_alignment=0.20, weight_decision=0.20, weight_completeness=0.15, weight_helpfulness=0.05, weight_factuality=0.10, pass_threshold=0.75),
        }

        _industry_map = {
            "default": "Default", "customer_support": "Customer support",
            "healthcare": "Healthcare", "legal": "Legal",
            "sales": "Sales", "coding_assistant": "Coding assistant",
        }
        _industry_key_map = {v: k for k, v in _industry_map.items()}

        # ── Preset pills ──────────────────────────────────────────────────────
        st.markdown(
            '<p style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;'
            'letter-spacing:0.06em;margin-bottom:6px">Start from a preset</p>',
            unsafe_allow_html=True,
        )
        cur_label = _industry_map.get(cfg.get("industry", "default"), "Default")
        preset_cols = st.columns(len(_PRESETS))
        selected_preset_label = cur_label
        for col, (label, _) in zip(preset_cols, _PRESETS.items()):
            is_active = label == cur_label
            btn_style = (
                "background:#6366f1;color:white;border:1px solid #6366f1;"
                if is_active else
                "background:white;color:#475569;border:1px solid #e2e8f0;"
            )
            if col.button(
                label,
                key=f"preset_{label}",
                use_container_width=True,
                help=f"Load {label} weights",
            ):
                selected_preset_label = label
                p = _PRESETS[label]
                st.session_state["cfg_acc"]   = int(p["weight_accuracy"] * 100)
                st.session_state["cfg_goal"]  = int(p["weight_goal_alignment"] * 100)
                st.session_state["cfg_dec"]   = int(p["weight_decision"] * 100)
                st.session_state["cfg_comp"]  = int(p["weight_completeness"] * 100)
                st.session_state["cfg_help"]  = int(p["weight_helpfulness"] * 100)
                st.session_state["cfg_fact"]  = int(p["weight_factuality"] * 100)
                st.session_state["cfg_thresh"]= int(p["pass_threshold"] * 100)
                st.rerun()

        st.markdown('<div style="height:12px"/>', unsafe_allow_html=True)

        # ── Weight table ──────────────────────────────────────────────────────
        st.markdown(
            '<p style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;'
            'letter-spacing:0.06em;margin-bottom:8px">Dimension weights</p>',
            unsafe_allow_html=True,
        )

        _DIMS = [
            ("cfg_acc",   "Accuracy",          cfg["weight_accuracy"],        "Contextual correctness — did the answer fit the situation?"),
            ("cfg_goal",  "Goal alignment",     cfg["weight_goal_alignment"],  "Did the agent address what the user actually needed?"),
            ("cfg_dec",   "Decision quality",   cfg["weight_decision"],        "Soundness of reasoning and tool choice"),
            ("cfg_comp",  "Completeness",       cfg["weight_completeness"],    "Was the request fully resolved?"),
            ("cfg_help",  "Helpfulness",        cfg.get("weight_helpfulness", 0.10), "Did the response practically help the user accomplish their goal?"),
            ("cfg_fact",  "Factuality",         cfg.get("weight_factuality", 0.10),  "Were all claims verifiable and grounded — no hallucinations?"),
        ]

        w_vals = []
        for key, label, default_frac, hint in _DIMS:
            default_pct = int(default_frac * 100)
            stored = st.session_state.get(key, default_pct)
            lc, nc, hc = st.columns([3, 1, 4])
            lc.markdown(
                f'<div style="font-size:13px;font-weight:600;color:#1e293b;padding-top:6px">'
                f'{label}</div>'
                f'<div style="font-size:11px;color:#94a3b8">{hint}</div>',
                unsafe_allow_html=True,
            )
            val = nc.number_input(
                label, min_value=5, max_value=95, value=int(stored), step=5,
                key=key, label_visibility="collapsed",
            )
            bar_w = val
            bar_color = "#6366f1" if val >= 30 else "#94a3b8"
            hc.markdown(
                f'<div style="padding-top:10px">'
                f'<div style="display:flex;align-items:center;gap:8px">'
                f'<div style="flex:1;background:#f1f5f9;border-radius:4px;height:6px">'
                f'<div style="background:{bar_color};width:{bar_w}%;height:6px;border-radius:4px"></div>'
                f'</div>'
                f'<span style="font-size:12px;color:#64748b;width:28px;text-align:right">{val}%</span>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
            w_vals.append(val)

        total = sum(w_vals)
        total_color = "#16a34a" if total == 100 else "#dc2626"
        st.markdown(
            f'<div style="border-top:1px solid #e2e8f0;margin:8px 0;padding-top:8px;'
            f'display:flex;justify-content:space-between;align-items:center">'
            f'<span style="font-size:13px;font-weight:700;color:#1e293b">Total</span>'
            f'<span style="font-size:14px;font-weight:800;color:{total_color}">{total}%'
            f'{"  ✓" if total == 100 else "  — must equal 100%"}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        st.markdown('<div style="height:8px"/>', unsafe_allow_html=True)

        # ── Pass threshold ────────────────────────────────────────────────────
        st.markdown(
            '<p style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;'
            'letter-spacing:0.06em;margin-bottom:8px">Pass threshold</p>',
            unsafe_allow_html=True,
        )
        thresh_stored = st.session_state.get("cfg_thresh", int(cfg["pass_threshold"] * 100))
        tc1, tc2 = st.columns([1, 3])
        thresh = tc1.number_input(
            "Pass threshold %", min_value=50, max_value=95, value=int(thresh_stored), step=5,
            key="cfg_thresh", label_visibility="collapsed",
        )
        tc2.markdown(
            f'<div style="font-size:12px;color:#64748b;padding-top:8px">'
            f'Steps scoring below <strong>{thresh}%</strong> are flagged as failures '
            f'and appear in the Failure Feed.</div>',
            unsafe_allow_html=True,
        )

        # ── Custom metrics ────────────────────────────────────────────────────
        st.markdown('<div style="height:8px"/>', unsafe_allow_html=True)
        st.markdown(
            '<p style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;'
            'letter-spacing:0.06em;margin-bottom:8px">Custom metrics</p>',
            unsafe_allow_html=True,
        )

        existing_custom: list = list(cfg.get("custom_metrics") or [])
        if "custom_metrics_state" not in st.session_state:
            st.session_state["custom_metrics_state"] = existing_custom

        custom_list: list = st.session_state["custom_metrics_state"]
        to_remove: Optional[int] = None

        for ci, cm in enumerate(custom_list):
            cc1, cc2, cc3, cc4 = st.columns([3, 1, 4, 0.6])
            cc1.markdown(
                f'<div style="font-size:13px;font-weight:600;color:#1e293b;padding-top:6px">'
                f'{cm["name"]}</div>'
                f'<div style="font-size:11px;color:#94a3b8">{cm.get("description","")}</div>',
                unsafe_allow_html=True,
            )
            new_w = cc2.number_input(
                f"w_{ci}", min_value=1, max_value=50, value=int(cm["weight"] * 100), step=1,
                key=f"cm_w_{ci}", label_visibility="collapsed",
            )
            custom_list[ci]["weight"] = new_w / 100
            cc3.markdown(
                f'<div style="padding-top:10px">'
                f'<div style="flex:1;background:#f1f5f9;border-radius:4px;height:6px">'
                f'<div style="background:#8b5cf6;width:{new_w*2}%;height:6px;border-radius:4px"></div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
            if cc4.button("×", key=f"rm_cm_{ci}", help=f"Remove {cm['name']}"):
                to_remove = ci

        if to_remove is not None:
            custom_list.pop(to_remove)
            st.session_state["custom_metrics_state"] = custom_list
            st.rerun()

        # Add metric form
        with st.expander("＋ Add custom metric", expanded=False):
            nm_col, desc_col, w_col = st.columns([2, 4, 1])
            new_name = nm_col.text_input("Metric name", placeholder="helpfulness", key="new_cm_name")
            new_desc = desc_col.text_input("Description", placeholder="Was the agent genuinely helpful?", key="new_cm_desc")
            new_w_pct = w_col.number_input("Weight %", min_value=1, max_value=50, value=10, step=1, key="new_cm_w")
            if st.button("Add metric", key="add_cm_btn") and new_name.strip():
                safe_name = new_name.strip().lower().replace(" ", "_")
                if not any(m["name"] == safe_name for m in custom_list):
                    custom_list.append({"name": safe_name, "weight": new_w_pct / 100, "description": new_desc.strip()})
                    st.session_state["custom_metrics_state"] = custom_list
                    st.rerun()

        custom_weight_total = int(round(sum(m["weight"] * 100 for m in custom_list)))
        standard_total = sum(w_vals)
        grand_total = standard_total + custom_weight_total
        total_color = "#16a34a" if grand_total == 100 else "#dc2626"

        if custom_list:
            st.markdown(
                f'<div style="font-size:11px;color:#64748b;margin-top:4px">'
                f'Standard: {standard_total}% · Custom: {custom_weight_total}% · '
                f'<strong style="color:{total_color}">Total: {grand_total}%'
                f'{"  ✓" if grand_total == 100 else "  — must equal 100%"}</strong></div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div style="font-size:11px;color:#94a3b8">No custom metrics. '
                f'Add one above to evaluate dimensions like helpfulness, tone, or compliance.</div>',
                unsafe_allow_html=True,
            )

        can_save = grand_total == 100 if custom_list else total == 100

        st.markdown('<div style="height:12px"/>', unsafe_allow_html=True)

        # ── Save ──────────────────────────────────────────────────────────────
        _, save_col = st.columns([3, 1])
        if save_col.button("Save", use_container_width=True, disabled=not can_save):
            db3 = _db()
            try:
                upsert_quality_config(agent_id, {
                    "industry": _industry_key_map.get(selected_preset_label, "default"),
                    "weight_accuracy":       w_vals[0] / 100,
                    "weight_goal_alignment": w_vals[1] / 100,
                    "weight_decision":       w_vals[2] / 100,
                    "weight_completeness":   w_vals[3] / 100,
                    "weight_helpfulness":    w_vals[4] / 100,
                    "weight_factuality":     w_vals[5] / 100,
                    "pass_threshold":      thresh / 100,
                    "custom_metrics":      custom_list,
                }, db3)
            finally:
                db3.close()
            st.session_state["custom_metrics_state"] = custom_list
            _overview_data.clear()
            st.success("Saved. New weights apply to the next evaluation cycle.")


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW 2 — Failure Feed
# ═══════════════════════════════════════════════════════════════════════════════
def _open_trace(session_id: str, agent: Optional[str] = None) -> None:
    """Show one session's trace in place of the current page (← Back returns)."""
    st.session_state["open_session"] = session_id
    if agent and agent != st.session_state.get("agent_id"):
        st.session_state["agent_id"] = agent


def _ago(ts: Optional[datetime]) -> str:
    if not ts:
        return ""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    secs = (datetime.now(timezone.utc) - ts).total_seconds()
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= size:
            return f"{int(secs // size)}{unit} ago"
    return "just now"


def _n_sessions(n: int) -> str:
    return f"{n} session{'' if n == 1 else 's'}"


def _pct(n: int, total: int) -> str:
    if not total:
        return ""
    p = n / total * 100
    return f"{p:.0f}%" if p >= 1 or p == 0 else "<1%"


def _problems(patterns: List[Any], counts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    One entry per distinct problem. The analyzer files the same failures under a
    workflow step *and* a failure type; group them by root cause so each problem
    shows once. Sizes are distinct sessions (from `counts`), not scored steps.
    """
    groups: Dict[str, Dict[str, Any]] = {}
    for p in patterns:
        key = (p.root_cause or p.pattern_value).strip().lower()
        g = groups.setdefault(key, {"title": p.root_cause or p.pattern_value, "sessions": 0,
                                    "steps": [], "types": [], "worsening": False, "patterns": [], "main": p})
        n = counts.get(p.pattern_type, {}).get(p.pattern_value, p.failure_count)
        if n > g["sessions"]:
            g["sessions"], g["main"] = n, p
        g["worsening"] = g["worsening"] or p.is_worsening
        g["patterns"].append(p)
        (g["steps"] if p.pattern_type == "workflow_step" else g["types"]).append(p.pattern_value)
    return sorted(groups.values(), key=lambda g: -g["sessions"])


def _rule_option(g: Dict[str, Any], by_pattern: Dict[str, Any]) -> Dict[str, Any]:
    """The best thing to offer for a problem: a ready rule, an existing one, or why there's none."""
    options = [by_pattern[p.id] for p in g["patterns"] if p.id in by_pattern]
    for status in ("suggested", "exists", "none"):
        for o in options:
            if o.get("status") == status:
                return o
    return {"status": "none", "reason": "Rule suggestions are still loading or unavailable."}


_FEED_CSS = """
<style>
.ff-title{font-size:16px;font-weight:600;color:#0f172a;line-height:1.45;margin-bottom:3px}
.ff-meta{font-size:13px;color:#64748b}
.ff-meta b{color:#0f172a}
.ff-meta code,.ff-rule code{background:#f1f5f9;color:#334155;padding:0 5px;border-radius:4px;font-size:12px}
.ff-worse{color:#dc2626;font-weight:600}
.ff-rule{font-size:13px;color:#334155;background:#f8fafc;border:1px solid #eef2f7;border-radius:8px;
         padding:8px 12px;margin-top:10px;line-height:1.55}
.ff-rule .ok{color:#16a34a;font-weight:600}
.ff-rule .warn{color:#b45309;font-weight:600}
.ff-rule .muted{color:#94a3b8}
.ff-row{font-size:14px;color:#1e293b;line-height:1.4}
.ff-sub{font-size:12px;color:#94a3b8}
.ff-h{font-size:15px;font-weight:700;color:#0f172a;margin:22px 0 8px}
</style>
"""


def _problem_meta(g: Dict[str, Any], total: int) -> str:
    """'12 sessions with a tool failure · 8% of sessions · at `issue_refund` · ▲ getting worse'."""
    n = g["sessions"]
    kind = g["types"][0].replace("_", " ") if g["types"] else ""
    if kind:
        label = kind if kind.endswith("failure") else f"{kind} failure"
        kind = f"{'an' if label[0] in 'aeiou' else 'a'} {html.escape(label)}"
    head = f"<b>{_n_sessions(n)}</b> with {kind or 'this failure'}"
    parts = [head]
    if total:
        parts.append(f"{_pct(n, total)} of all sessions")
    if g["steps"]:
        parts.append(f"at <code>{html.escape(g['steps'][0])}</code>")
    if g["worsening"]:
        parts.append('<span class="ff-worse">▲ getting worse</span>')
    return " · ".join(parts)


def _rule_box(option: Dict[str, Any]) -> str:
    status = option.get("status")
    if status == "suggested":
        cov = option.get("coverage") or {}
        fm, ft = cov.get("failing_matched", 0), cov.get("failing_total", 0)
        pm, pt = cov.get("passing_matched", 0), cov.get("passing_total", 0)
        good = f' · <span class="{"ok" if pm == 0 else "warn"}">{pm} of {pt} successful ones</span>' if pt else ""
        return (f'<div class="ff-rule">🛡 <b>Rule ready:</b> {sentence(option["rule"])}<br/>'
                f'<span class="muted">Would have caught</span> <b>{fm} of {_n_sessions(ft)}</b> '
                f'<span class="muted">that failed this way</span>{good}</div>')
    if status == "exists":
        return (f'<div class="ff-rule"><span class="ok">✓ Covered</span> by your rule '
                f'<code>{html.escape(option.get("rule_id", ""))}</code> — manage it in Rules.</div>')
    return f'<div class="ff-rule"><span class="muted">No rule to suggest: {html.escape(option.get("reason", ""))}</span></div>'


def _make_rule(agent_id: str, pattern_id: str, rule: Dict[str, Any]) -> None:
    ok, msg, rid = create_rule(agent_id, rule)
    st.session_state.setdefault("_feed_made", {})[pattern_id] = {
        "ok": ok, "msg": msg, "rule": {**rule, "id": rid or rule.get("id")}, "test": None, "blocking": False}


def _test_rule(agent_id: str, pattern_id: str) -> None:
    m = st.session_state["_feed_made"][pattern_id]
    m["test"] = try_rule(agent_id, m["rule"])


def _start_blocking(agent_id: str, pattern_id: str) -> None:
    m = st.session_state["_feed_made"][pattern_id]
    ok, msg = promote_rule(agent_id, m["rule"]["id"])
    m["blocking"] = ok
    m["test"] = try_rule(agent_id, m["rule"]) if ok else ("error", msg)


def _rule_in_place(agent_id: str, p: Any, option: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The rule this card can test and turn on: one just made here, or one that already covers it."""
    made = st.session_state.setdefault("_feed_made", {})
    if p.id not in made and option.get("status") == "exists":
        made[p.id] = {"ok": True, "msg": "", "rule": {**option["rule"], "id": option["rule_id"]},
                      "test": None, "blocking": False}
    m = made.get(p.id)
    return m if m and m["ok"] else None


_TEST_STYLE = {"blocked": ("#fef2f2", "#b91c1c", "✋"), "watching": ("#fffbeb", "#b45309", "👀"),
               "allowed": ("#f0fdf4", "#15803d", "✓"), "error": ("#fef2f2", "#b91c1c", "✗")}


def _rule_controls(agent_id: str, p: Any, m: Dict[str, Any]) -> None:
    """After a rule exists: try the call it should stop, then turn blocking on — right on the card."""
    if m["msg"]:
        st.markdown(f'<div class="ff-rule"><span class="ok">✓ {html.escape(m["msg"])}</span></div>',
                    unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="ff-rule">🛡 <b>Your rule:</b> {sentence(m["rule"])}</div>', unsafe_allow_html=True)
    if m["test"]:
        kind, text = m["test"]
        bg, fg, icon = _TEST_STYLE.get(kind, _TEST_STYLE["error"])
        st.markdown(f'<div style="background:{bg};color:{fg};border-radius:8px;padding:9px 12px;margin-top:8px;'
                    f'font-size:14px;font-weight:600">{icon} {html.escape(text)}</div>', unsafe_allow_html=True)
    if m["blocking"] and m["test"] and m["test"][0] == "blocked":
        st.markdown(
            '<div style="font-size:14px;color:#334155;margin-top:10px;line-height:1.6">🎉 <b>That\'s the loop.</b> '
            'Kalytera spotted the failure in the conversations, wrote the rule from the tool calls, and now '
            'stops the bad call before the tool runs — no code from you.</div>', unsafe_allow_html=True)
        with st.popover("Do this for my own agent →"):
            st.markdown("Two changes ([guide](https://github.com/priyamathur/kalytera-server"
                        "#add-kalytera-to-an-agent-in-production)):")
            st.code('import kalytera\nkalytera.configure(api_key="kly_live_...", agent_id="support-bot")\n\n'
                    '@kalytera.tool                    # checks your rules before each call\n'
                    'def refund_api(order_id, amount): ...\n\n'
                    'with kalytera.session(conversation_id, input=message) as s:\n'
                    '    s.output = run_my_agent(message)', language="python")
    c1, c2, _ = st.columns([1.5, 1.3, 2.6])
    c1.button("▶ Test it", key=f"test_{p.id}", type="secondary" if m["test"] else "primary",
              use_container_width=True, on_click=_test_rule, args=(agent_id, p.id),
              help="Sends the call this rule should catch through guard(), exactly as your agent would")
    if not m["blocking"]:
        c2.button("Start blocking", key=f"block_{p.id}", type="primary" if m["test"] else "secondary",
                  use_container_width=True, on_click=_start_blocking, args=(agent_id, p.id),
                  help="From now on guard() stops matching calls before the tool runs")


@st.fragment(run_every=AUTO_REFRESH_S)
def _failure_feed_fragment(agent_id: str) -> None:
    db = _db()
    try:
        patterns = get_patterns_for_agent(agent_id, db)
        recent = get_recent_eval_failures(agent_id, 50, db)
        counts = get_session_failure_counts(agent_id, db)
    except Exception as _exc:
        st.error(f"Could not load failures: {_exc}", icon="🔴")
        return
    finally:
        db.close()

    st.markdown(_FEED_CSS, unsafe_allow_html=True)
    if not patterns and not recent:
        st.success("No failed sessions for this agent.", icon="✅")
        return

    problems = _problems(patterns, counts)
    db = _db()
    try:
        names = get_step_names(agent_id, db)
    finally:
        db.close()
    for g in problems:
        g["steps"] = [step_label(v, names) for v in g["steps"]]
    by_pattern = fetch_suggestion_data(agent_id).get("by_pattern", {}) if problems else {}
    total = counts.get("total", 0)
    recent_sessions = len({log.session_id for _, log in recent})
    n_recent = f"{recent_sessions}+" if len(recent) >= 50 else str(recent_sessions)
    st.markdown(
        f'<div class="ff-meta" style="margin:-8px 0 4px">{n_recent} recent failed '
        f'session{"s" if recent_sessions != 1 else ""}'
        + (f" · {len(problems)} problem{'s keep' if len(problems) != 1 else ' keeps'} happening" if problems else "")
        + "</div>",
        unsafe_allow_html=True,
    )

    # ── What keeps failing ────────────────────────────────────────────────────
    st.markdown('<div class="ff-h">What keeps failing</div>', unsafe_allow_html=True)
    if not problems:
        st.markdown('<div class="ff-meta">Nothing yet — a problem shows here once the same failure repeats '
                    '(patterns update hourly).</div>', unsafe_allow_html=True)
    opened: set = st.session_state.setdefault("_feed_open", set())
    made: Dict[str, Any] = st.session_state.setdefault("_feed_made", {})
    for g in problems:
        p = g["main"]
        option = _rule_option(g, by_pattern)
        with st.container(border=True):
            st.markdown(
                f'<div class="ff-title">{html.escape(g["title"])}</div>'
                f'<div class="ff-meta">{_problem_meta(g, total)}</div>',
                unsafe_allow_html=True,
            )
            in_place = _rule_in_place(agent_id, p, option)
            result = made.get(p.id)
            if in_place:
                _rule_controls(agent_id, p, in_place)
            else:
                st.markdown(_rule_box(option), unsafe_allow_html=True)
                if result and not result["ok"]:
                    st.error(result["msg"])
            b1, b2, _ = st.columns([1.3, 1.3, 3])
            if option.get("status") == "suggested" and not in_place:
                b1.button("⚡ Make it a rule", key=f"make_{p.id}", type="primary", use_container_width=True,
                          on_click=_make_rule, args=(agent_id, p.id, option["rule"]),
                          help="Adds this rule in watch mode: it counts matching calls and never blocks "
                               "until you turn blocking on in Rules.")
                see_col = b2
            else:
                see_col = b1
            is_open = p.id in opened
            see_col.button("Hide sessions" if is_open else f"See {_n_sessions(g['sessions'])}",
                           key=f"see_{p.id}", use_container_width=True,
                           on_click=opened.symmetric_difference_update, args=({p.id},))
            if is_open:
                _pattern_sessions(agent_id, p)

    # ── Latest failures (same failure grouped, newest first) ──────────────────
    st.markdown('<div class="ff-h">Latest failed sessions</div>', unsafe_allow_html=True)
    grouped: Dict[Tuple[str, str], Dict[str, Tuple[Any, Any]]] = {}
    for ev, log in recent:  # already newest first
        reason = _short_reason(ev.failure_reason, ev.failure_type, log.step_name)
        grouped.setdefault((reason, log.step_name), {}).setdefault(log.session_id, (ev, log))
    rows = list(grouped.items())
    shown = st.session_state.get("_feed_shown", 8)
    for (reason, step), by_session in rows[:shown]:
        ev, log = next(iter(by_session.values()))
        n = len(by_session)
        count = f"{_n_sessions(n)} · " if n > 1 else ""
        text, btn = st.columns([6, 1], vertical_alignment="center")
        text.markdown(
            f'<div class="ff-row">{html.escape(reason)}</div>'
            f'<div class="ff-sub">{count}at {html.escape(step)} · '
            f'{"latest " if n > 1 else ""}{_ago(ev.evaluated_at)}</div>',
            unsafe_allow_html=True,
        )
        if btn.button("Open" if n == 1 else "Open latest", key=f"row_{ev.id}", use_container_width=True):
            _open_trace(log.session_id)
            st.rerun(scope="app")
    more, csv, _ = st.columns([1, 1, 3])
    if len(rows) > shown:
        more.button(f"Show more ({len(rows) - shown})", key="_feed_more",
                    on_click=st.session_state.__setitem__, args=("_feed_shown", shown + 10))
    (csv if len(rows) > shown else more).download_button(
        "Download CSV",
        data=pd.DataFrame([{
            "session_id": log.session_id, "step": log.step_name, "failure_type": ev.failure_type or "",
            "failure_reason": ev.failure_reason or "", "score": round(ev.overall_score * 100),
            "evaluated_at": ev.evaluated_at.isoformat() if ev.evaluated_at else "",
        } for ev, log in recent]).to_csv(index=False),
        file_name=f"kalytera-failures-{agent_id}.csv", mime="text/csv", key="_feed_csv",
    )


def _pattern_sessions(agent_id: str, p: Any) -> None:
    """The sessions behind one problem, inline under its card."""
    db = _db()
    try:
        sessions = get_pattern_sessions(agent_id, p.pattern_type, p.pattern_value, PATTERN_SESSIONS_SHOWN, db)
        names = get_step_names(agent_id, db)
    finally:
        db.close()
    if not sessions:
        st.caption("These sessions are no longer in the database.")
        return
    for s in sessions:
        text, btn = st.columns([6, 1], vertical_alignment="center")
        text.markdown(
            f'<div class="ff-row"><code>{html.escape(s["session_id"])}</code></div>'
            f'<div class="ff-sub">{_ago(s["failed_at"])} · score {int(s["overall_score"] * 100)}'
            f'{" · at " + html.escape(step_label(s["failure_step"], names)) if s["failure_step"] else ""}</div>',
            unsafe_allow_html=True,
        )
        if btn.button("Open", key=f"ps_{p.id}_{s['session_id']}", use_container_width=True):
            _open_trace(s["session_id"])
            st.rerun(scope="app")
    if len(sessions) >= PATTERN_SESSIONS_SHOWN:
        st.caption(f"Showing the latest {PATTERN_SESSIONS_SHOWN}. Search a session ID at the top right to find any other.")


def _show_failure_feed(agent_id: str) -> None:
    _page_header("Failure Feed", "What keeps going wrong, and the sessions it happened in")
    if agent_id.startswith(SAMPLE_PREFIX):
        _sample_hint()
    _failure_feed_fragment(agent_id)


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW 3 — Trace Viewer
# ═══════════════════════════════════════════════════════════════════════════════
def _build_step_duration_chart(steps: List[Tuple[Any, Optional[Any]]]) -> Optional[go.Figure]:
    """Bar chart: one bar per step, height = latency, color = pass/fail. None if no latency was recorded."""
    if not steps or not any(log.latency_ms for log, _ in steps):
        return None

    labels, durations, colors, hover = [], [], [], []
    for log, ev in steps:
        latency = log.latency_ms or 0
        failed = ev is not None and not ev.passed
        score = int(round(ev.overall_score * 100)) if ev else None
        labels.append(f"Step {log.step_number}<br>{log.step_name}")
        durations.append(latency)
        colors.append("#ef4444" if failed else "#22c55e")
        score_line = f"Score: {score}/100" if score is not None else "Pending eval"
        hover.append(
            f"<b>{log.step_name}</b><br>Duration: {latency:,} ms<br>{score_line}<extra></extra>"
        )

    fig = go.Figure(go.Bar(
        x=labels,
        y=durations,
        marker_color=colors,
        marker_line=dict(color="white", width=1),
        text=[f"{d:,} ms" for d in durations],
        textposition="outside",
        textfont=dict(size=11, color="#475569"),
        hovertemplate=hover,
        showlegend=False,
    ))
    fig.update_layout(
        height=220,
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=0, r=0, t=8, b=0),
        font=dict(family="Inter, sans-serif", size=11, color="#475569"),
        xaxis=dict(tickfont=dict(size=11), linecolor="#e2e8f0"),
        yaxis=dict(
            title="ms", gridcolor="#f1f5f9", linecolor="#e2e8f0",
            zeroline=False,
        ),
        bargap=0.35,
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


def _score_bar(label: str, value: float, color: str) -> str:
    pct = int(value * 100)
    width = max(pct, 2)
    return (
        f'<div style="margin-bottom:6px">'
        f'<div style="display:flex;justify-content:space-between;margin-bottom:2px">'
        f'<span style="font-size:11px;color:#64748b;font-weight:600">{label}</span>'
        f'<span style="font-size:11px;font-weight:700;color:{color}">{pct}</span>'
        f'</div>'
        f'<div style="background:#f1f5f9;border-radius:4px;height:5px">'
        f'<div style="background:{color};width:{width}%;height:5px;border-radius:4px;transition:width 0.3s"></div>'
        f'</div></div>'
    )


def _show_trace(agent_id: str, session_id: str) -> None:
    st.button(f"← Back to {view.split('  ', 1)[-1]}", key="trace_back",
              on_click=lambda: st.session_state.pop("open_session", None))
    _page_header("Session trace", "Every step, its score, and where it went wrong")

    db = _db()
    try:
        steps = get_session_steps(session_id, db, agent_id=agent_id)
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

    # ── Session header ────────────────────────────────────────────────────────
    passed_count = len(steps) - len(failed_steps)
    st.markdown(
        f"""
        <div style="background:white;border:1px solid #e2e8f0;border-radius:14px;
                    padding:20px 24px;display:flex;justify-content:space-between;
                    align-items:center;margin-bottom:16px;
                    box-shadow:0 1px 3px rgba(15,23,42,0.05)">
          <div>
            <div style="font-size:10px;font-weight:700;color:#64748b;letter-spacing:0.08em;
                        text-transform:uppercase;margin-bottom:6px">Session ID</div>
            <code style="font-size:13px;color:#1e293b;background:#f8fafc;padding:4px 8px;
                         border-radius:6px;border:1px solid #e2e8f0">{session_id}</code>
            <div style="display:flex;gap:16px;margin-top:10px">
              <span style="font-size:12px;color:#64748b">{len(steps)} steps</span>
              <span style="font-size:12px;color:#16a34a;font-weight:600">✓ {passed_count} passed</span>
              {'<span style="font-size:12px;color:#dc2626;font-weight:600">✗ ' + str(len(failed_steps)) + ' failed</span>' if failed_steps else ''}
              <span style="font-size:12px;color:#64748b">{total_ms:,} ms total</span>
            </div>
          </div>
          <div style="text-align:right">
            <div style="font-size:44px;font-weight:900;color:{score_color};
                        letter-spacing:-0.04em;line-height:1">
              {session_score}<span style="font-size:20px;font-weight:400;color:#cbd5e1">/100</span>
            </div>
            <div style="font-size:11px;font-weight:800;color:{score_color};
                        letter-spacing:0.1em;text-transform:uppercase;margin-top:2px">
              {"● FAILED" if is_failed else "● PASSED"}
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Golden label — calibrate the judge ───────────────────────────────────
    db_lbl = _db()
    try:
        existing_label = get_golden_label(agent_id, session_id, db_lbl)
    finally:
        db_lbl.close()

    lc, mc, rc = st.columns([2, 2, 6])
    if existing_label is not None:
        verb = "✓ Labeled: PASSED" if existing_label.human_passed else "✗ Labeled: FAILED"
        lbl_color = "#16a34a" if existing_label.human_passed else "#dc2626"
        lc.markdown(
            f'<div style="font-size:12px;font-weight:700;color:{lbl_color};padding-top:8px">{verb}</div>',
            unsafe_allow_html=True,
        )
        if mc.button("Change label", key="change_lbl"):
            db_lbl2 = _db()
            try:
                upsert_golden_label(agent_id, session_id, not existing_label.human_passed, "", db_lbl2)
                _overview_data.clear()
            finally:
                db_lbl2.close()
            st.rerun()
    else:
        if lc.button("👍 Mark passed", key="lbl_pass", help="Confirm this session passed — trains the judge"):
            db_lbl2 = _db()
            try:
                upsert_golden_label(agent_id, session_id, True, "", db_lbl2)
                _overview_data.clear()
            finally:
                db_lbl2.close()
            st.rerun()
        if mc.button("👎 Mark failed", key="lbl_fail", help="Override — this session actually failed"):
            db_lbl2 = _db()
            try:
                upsert_golden_label(agent_id, session_id, False, "", db_lbl2)
                _overview_data.clear()
            finally:
                db_lbl2.close()
            st.rerun()
        rc.markdown(
            '<div style="font-size:11px;color:#94a3b8;padding-top:8px">'
            'Label sessions to measure and calibrate judge accuracy.</div>',
            unsafe_allow_html=True,
        )

    # ── Root cause alert — shown immediately if session failed ────────────────
    diag = _build_diagnosis(steps)
    if diag:
        primary_ft = next(
            (ev.failure_type for _, ev in failed_steps if ev and ev.failure_type), "unknown"
        )
        fg, bg = _ft_color(primary_ft)
        st.markdown(
            f"""
            <div style="background:{bg};border:1px solid {fg}33;border-left:4px solid {fg};
                        border-radius:0 12px 12px 0;padding:16px 20px;margin-bottom:20px">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
                <span style="font-size:11px;font-weight:800;color:{fg};text-transform:uppercase;
                             letter-spacing:0.06em">Root Cause</span>
                {_badge(primary_ft, "11px")}
              </div>
              <div style="font-size:14px;font-weight:600;color:#1e293b;margin-bottom:10px;line-height:1.6">
                {diag['what']}
              </div>
              <div style="display:flex;align-items:flex-start;gap:8px;font-size:13px;color:#0369a1">
                <span style="font-weight:700;flex-shrink:0">→ Fix:</span>
                <span>{diag['fix']}</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ── Step duration chart ───────────────────────────────────────────────────
    duration_chart = _build_step_duration_chart(steps)
    if duration_chart:
        _section_head("Step Duration", "latency per step — green = passed, red = failed")
        st.plotly_chart(duration_chart, use_container_width=True, config={"displayModeBar": False})

    # ── Conversation trace ────────────────────────────────────────────────────
    _section_head("Conversation", "click any step to expand — failed steps open automatically")

    for log, ev in steps:
        passed = ev.passed if ev is not None else True
        score = int(round(ev.overall_score * 100)) if ev else None
        is_step_failed = ev is not None and not passed
        border_color = "#ef4444" if is_step_failed else "#22c55e" if ev else "#94a3b8"
        status_icon = "✗" if is_step_failed else ("✓" if ev else "·")

        # Expander label: the step_name IS the summary — no extra words needed
        if score is not None:
            label = f"{status_icon}  Step {log.step_number} · {log.step_name}  ·  {log.latency_ms:,} ms  ·  {score}/100"
        else:
            label = f"·  Step {log.step_number} · {log.step_name}  ·  {log.latency_ms:,} ms  ·  pending"

        # Failed steps open automatically so failures are never hidden
        with st.expander(label, expanded=is_step_failed):

            # User → Agent conversation
            msg_l, msg_r = st.columns(2)
            with msg_l:
                st.markdown(
                    '<p style="font-size:10px;font-weight:700;color:#64748b;'
                    'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px">User</p>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;'
                    f'padding:12px 14px;font-size:13px;color:#1e293b;line-height:1.6;min-height:52px">'
                    f'{log.input[:800]}{"…" if len(log.input) > 800 else ""}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with msg_r:
                st.markdown(
                    '<p style="font-size:10px;font-weight:700;color:#64748b;'
                    'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px">Agent</p>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div style="background:white;border:1px solid #e2e8f0;border-radius:10px;'
                    f'padding:12px 14px;font-size:13px;color:#1e293b;line-height:1.6;min-height:52px">'
                    f'{log.output[:800]}{"…" if len(log.output) > 800 else ""}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            # Score bars + fix — only on failed steps
            if is_step_failed and ev:
                ft = ev.failure_type or "unknown"
                fg, bg = _ft_color(ft)
                fix = _fix_trace(ft, log.step_name)
                bars = (
                    _score_bar("Accuracy", ev.accuracy, "#6366f1")
                    + _score_bar("Goal alignment", ev.goal_alignment, "#8b5cf6")
                    + _score_bar("Decision quality", ev.decision_quality, "#f59e0b")
                    + _score_bar("Completeness", ev.completeness, "#0891b2")
                    + _score_bar("Helpfulness", getattr(ev, "helpfulness", None) or 0.0, "#10b981")
                    + _score_bar("Factuality", getattr(ev, "factuality", None) or 0.0, "#ef4444")
                )
                st.markdown('<div style="height:10px"/>', unsafe_allow_html=True)
                st.markdown(
                    f"""
                    <div style="background:{bg};border:1px solid {fg}33;border-radius:10px;
                                padding:14px 16px">
                      <div style="display:flex;gap:24px;flex-wrap:wrap;align-items:flex-start">
                        <div style="flex:1;min-width:200px">
                          <div style="margin-bottom:8px">{_badge(ft)}</div>
                          <div style="font-size:13px;font-weight:600;color:#1e293b;
                                      line-height:1.5;margin-bottom:8px">
                            {ev.failure_reason or ft}
                          </div>
                          <div style="font-size:12px;color:#0369a1">→ {fix}</div>
                        </div>
                        <div style="width:190px;flex-shrink:0">{bars}</div>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            # Tool calls — only when present
            if log.tool_calls:
                try:
                    tools = (
                        json.loads(log.tool_calls)
                        if isinstance(log.tool_calls, str)
                        else log.tool_calls
                    )
                    if tools:
                        st.markdown('<div style="height:8px"/>', unsafe_allow_html=True)
                        st.json(tools, expanded=False)
                except (json.JSONDecodeError, TypeError):
                    pass


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION SEARCH (top right, every page)
# ═══════════════════════════════════════════════════════════════════════════════
def _run_search() -> None:
    """on_change: open an exact match straight away, otherwise list what matched."""
    q = st.session_state.get("session_search", "").strip()
    st.session_state.pop("search_results", None)
    if not q:
        return
    db = _db()
    try:
        found = search_sessions(_all_agents or [agent_id], q, SEARCH_LIMIT, db)
    finally:
        db.close()
    if found and found[0]["session_id"] == q:
        _open_trace(q, found[0]["agent_id"])
        st.session_state["session_search"] = ""
        return
    st.session_state["search_results"] = (q, found)


def _clear_search() -> None:
    st.session_state.pop("search_results", None)
    st.session_state["session_search"] = ""


def _open_result(session_id: str, agent: str) -> None:
    _open_trace(session_id, agent)
    _clear_search()


def _search_bar() -> None:
    _, box = st.columns([3, 1.25])
    box.text_input("Search sessions", key="session_search", on_change=_run_search,
                   placeholder="🔍  Search sessions — ID or error text", label_visibility="collapsed")
    results = st.session_state.get("search_results")
    if not results:
        return
    q, found = results
    with st.container(border=True):
        head, close = st.columns([6, 1], vertical_alignment="center")
        head.markdown(f"**{len(found)}{'+' if len(found) >= SEARCH_LIMIT else ''} session"
                      f"{'' if len(found) == 1 else 's'}** matching “{html.escape(q)}”" if found
                      else f"No sessions match “{html.escape(q)}”. Session IDs and error text are searched, "
                           f"across all your agents.")
        close.button("Close", key="search_close", on_click=_clear_search, use_container_width=True)
        for r in found:
            text, btn = st.columns([6, 1], vertical_alignment="center")
            status = ('<span style="color:#dc2626;font-weight:600">failed</span>' if r["failed"]
                      else '<span style="color:#16a34a;font-weight:600">passed</span>')
            reason = (f' · {html.escape(_short_reason(r["failure_reason"], None, ""))}'
                      if r.get("failure_reason") else "")
            agent_note = f" · {html.escape(r['agent_id'])}" if r["agent_id"] != agent_id else ""
            text.markdown(f'<div style="font-size:14px"><code>{html.escape(r["session_id"])}</code></div>'
                          f'<div style="font-size:12px;color:#94a3b8">{status} · {_ago(r["last_seen"])}'
                          f'{agent_note}{reason}</div>', unsafe_allow_html=True)
            btn.button("Open", key=f"sr_{r['session_id']}", use_container_width=True,
                       on_click=_open_result, args=(r["session_id"], r["agent_id"]))


# ═══════════════════════════════════════════════════════════════════════════════
# SAMPLE AGENT — a new account's first two minutes
# ═══════════════════════════════════════════════════════════════════════════════
SAMPLE_PREFIX = "sample-refund-bot-"
SAMPLE_SESSIONS = 24
SAMPLE_TIMEOUT_S = 240


def _run_sample_agent() -> None:
    """Create the sample agent's conversations on the server and show scoring live."""
    import time

    status, body = _rules_api("POST", "/agents/sample")
    if status not in (200, 202):
        st.error(f"Couldn't start the sample agent: {body.get('detail') if isinstance(body, dict) else body}")
        return
    agent = body["agent_id"]
    with st.status("Running the sample agent…", expanded=True) as box:
        st.write(f"✓ {SAMPLE_SESSIONS} customer conversations sent")
        bar = st.progress(0.0, text="The AI judge is reading each conversation…")
        deadline = time.monotonic() + SAMPLE_TIMEOUT_S
        while time.monotonic() < deadline:
            _, s_ = _rules_api("GET", f"/agents/{agent}/refresh")
            state = s_.get("state") if isinstance(s_, dict) else "error"
            if state == "error":
                box.update(label="Scoring failed", state="error")
                st.error(s_.get("error") if isinstance(s_, dict) else "Scoring failed")
                return
            to_score = s_.get("to_score") or 0
            done = SAMPLE_SESSIONS - to_score + s_.get("scored", 0) if to_score else 0
            if state in ("analyzing", "done"):
                bar.progress(1.0, text="Looking for what the failures have in common…")
            else:
                bar.progress(min(done, SAMPLE_SESSIONS) / SAMPLE_SESSIONS,
                             text=f"The AI judge is reading conversation {min(done + 1, SAMPLE_SESSIONS)} "
                                  f"of {SAMPLE_SESSIONS}…")
            if state == "done":
                box.update(label=f"Done — {s_.get('sessions_failed', 0)} of {s_.get('sessions_scored', 0)} "
                                 f"conversations failed", state="complete")
                break
            time.sleep(2)
        else:
            box.update(label="Still scoring — check Failure Feed in a minute", state="running")
    st.session_state["_switch_to"] = (agent, "🔴  Failure Feed")
    st.rerun()


def _welcome_panel() -> None:
    with st.container(border=True):
        st.markdown(
            '<div style="font-size:20px;font-weight:800;color:#0f172a;margin-bottom:6px">'
            'See Kalytera catch a failing agent — about 2 minutes, no code</div>'
            '<div style="font-size:14px;color:#475569;line-height:1.65;max-width:760px">'
            'A sample refund agent handles 24 customer conversations. Its refund tool rejects refunds over '
            '$500, but the agent tells the customer the refund went through anyway. <b>Kalytera isn\'t told any '
            'of this</b> — watch it find the problem, write the rule, and stop the next bad refund.</div>',
            unsafe_allow_html=True,
        )
        c1, c2, _ = st.columns([1.4, 1.6, 3])
        run = c1.button("▶ Run the sample agent", type="primary", use_container_width=True, key="run_sample")
        with c2.popover("Connect my own agent", use_container_width=True):
            st.markdown("Two changes in your code ([guide](https://github.com/priyamathur/kalytera-server"
                        "#add-kalytera-to-an-agent-in-production)):")
            st.code('import kalytera\nkalytera.configure(api_key="kly_live_...", agent_id="support-bot")\n\n'
                    '@kalytera.tool                    # checks your rules before each call\n'
                    'def refund_api(order_id, amount): ...\n\n'
                    'with kalytera.session(conversation_id, input=message) as s:\n'
                    '    s.output = run_my_agent(message)', language="python")
    if run:
        _run_sample_agent()


def _sample_hint() -> None:
    st.markdown(
        '<div style="background:#eef2ff;border:1px solid #c7d2fe;color:#3730a3;border-radius:10px;'
        'padding:10px 14px;font-size:14px;margin-bottom:6px">👇 Kalytera found this on its own from the '
        'conversations. Click <b>⚡ Make it a rule</b>, then <b>▶ Test it</b> and <b>Start blocking</b>.</div>',
        unsafe_allow_html=True,
    )


_own_agents = [a for a in (_all_agents or []) if a != "demo-agent"]
_has_sample = any(a.startswith(SAMPLE_PREFIX) for a in _own_agents)


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════════════
_search_bar()
_open_sid = st.session_state.get("open_session")
if _open_sid:
    _show_trace(agent_id, str(_open_sid))
elif st.session_state.pop("_want_sample", False):
    _run_sample_agent()
elif _stored_key and not _own_agents:
    _welcome_panel()  # a new account: nothing of its own to show yet
elif "Overview" in view:
    _show_overview(agent_id)
elif "Failure" in view:
    _show_failure_feed(agent_id)
elif "Rules" in view:
    show_rules(agent_id)
