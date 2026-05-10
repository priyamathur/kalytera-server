"""
AgentIQ Streamlit Dashboard - Comprehensive Agent Observability Platform
4 Views: Overview, Usage Analytics, Loss Patterns, Interaction Detail
"""

import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json
from typing import Dict, List, Any, Optional

st.set_page_config(
    page_title="AgentIQ - Agent Observability Platform",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

API_BASE_URL = st.secrets.get("api_base_url", "http://localhost:8000") if hasattr(st, "secrets") else "http://localhost:8000"

st.markdown("""
<style>
    .main-header { font-size: 2.5rem; color: #1f77b4; text-align: center; margin-bottom: 2rem; }
    .metric-card { background-color: #f0f2f6; padding: 1rem; border-radius: 0.5rem; margin: 0.5rem 0; }
    .status-success { color: #28a745; }
    .status-warning { color: #ffc107; }
    .status-danger { color: #dc3545; }
    .pattern-card { border-left: 4px solid #1f77b4; padding: 1rem; margin: 1rem 0; background-color: #f8f9fa; }
</style>
""", unsafe_allow_html=True)


def make_api_get(endpoint: str, params: Dict = None) -> Optional[Any]:
    """Make GET request"""
    try:
        response = requests.get(f"{API_BASE_URL}{endpoint}", params=params, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        st.error(f"GET {endpoint} failed: {str(e)}")
        return None


def make_api_post(endpoint: str, params: Dict = None) -> Optional[Any]:
    """Make POST request"""
    try:
        response = requests.post(f"{API_BASE_URL}{endpoint}", params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        st.error(f"POST {endpoint} failed: {str(e)}")
        return None


def render_sidebar():
    """Render sidebar navigation and controls"""
    st.sidebar.title("🤖 AgentIQ")
    st.sidebar.markdown("**Agent Observability Platform**")

    page = st.sidebar.selectbox(
        "Navigate to:",
        ["📊 Overview", "📈 Usage Analytics", "🎯 Loss Patterns", "💬 Interaction Detail"],
        index=0
    )

    st.sidebar.markdown("---")

    st.sidebar.subheader("⏰ Time Range")
    time_range = st.sidebar.selectbox(
        "Select period:",
        ["Last 24 hours", "Last 7 days", "Last 30 days"],
        index=1
    )
    hours_map = {"Last 24 hours": 24, "Last 7 days": 168, "Last 30 days": 720}
    hours_back = hours_map[time_range]

    st.sidebar.markdown("---")
    st.sidebar.subheader("🚦 System Status")

    health_data = make_api_get("/health")
    if health_data:
        st.sidebar.success("✅ API Online")
    else:
        st.sidebar.error("❌ API Offline")

    eval_health = make_api_get("/evaluation/health")
    if eval_health and eval_health.get("evaluation_system") == "online":
        st.sidebar.success("✅ Evaluation System")
    else:
        st.sidebar.warning("⚠️ Evaluation Limited")

    pattern_health = make_api_get("/patterns/health")
    if pattern_health and pattern_health.get("pattern_analysis") == "online":
        st.sidebar.success("✅ Pattern Analysis")
    else:
        st.sidebar.warning("⚠️ Pattern Analysis Limited")

    return page.split(" ", 1)[1], hours_back


def render_overview_page(hours_back: int):
    """Render overview dashboard with key metrics"""
    st.markdown('<h1 class="main-header">📊 AgentIQ Overview</h1>', unsafe_allow_html=True)

    # Key metrics from dashboard-summary (returns a dict)
    summary = make_api_get("/analytics/dashboard-summary")

    col1, col2, col3, col4 = st.columns(4)

    if summary:
        with col1:
            st.metric("📝 Total Sessions (7d)", f"{summary.get('total_sessions', 0):,}")
        with col2:
            completion = summary.get("overall_completion_rate", 0)
            st.metric("✅ Completion Rate", f"{completion:.1%}")
        with col3:
            quality = summary.get("avg_quality_score", 0)
            st.metric("⭐ Avg Quality Score", f"{quality:.2f}")
        with col4:
            dropoff = summary.get("dropoff_rate", 0)
            st.metric("📉 Drop-off Rate", f"{dropoff:.1%}")
    else:
        st.warning("Could not load dashboard summary.")

    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🎯 Top Failure Intents")
        insights_data = make_api_get("/patterns/insights/top-intents", {"limit": 5})

        if insights_data and insights_data.get("top_intents"):
            st.info(f"**Key Insight:** {insights_data['key_insight']}")
            for intent in insights_data["top_intents"][:3]:
                st.markdown(f"""
                <div class="pattern-card">
                    <strong>{intent['intent'].replace('_',' ').title()}</strong><br>
                    {intent['failure_count']} failures ({intent['pct_of_all_failures']:.1f}% of total)<br>
                    Quality Score: {intent['avg_quality_score']:.2f}
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No failure patterns detected yet. Upload agent logs to get insights.")

    with col2:
        st.subheader("📈 Session Volume (Recent)")
        # session-volume returns a list of time-bucketed points
        volume_list = make_api_get("/analytics/session-volume", {"hours_back": hours_back, "granularity": "day"})

        if volume_list:
            df = pd.DataFrame(volume_list)
            if not df.empty:
                fig = px.area(
                    df, x="timestamp", y="session_count",
                    title=f"Session Volume (last {hours_back}h)",
                    labels={"session_count": "Sessions", "timestamp": "Time"}
                )
                fig.update_layout(height=300)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No volume data for this period.")
        else:
            st.info("No activity data available.")

    st.markdown("---")
    st.subheader("🚀 Quick Actions")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("📤 Test JSON Ingest", type="secondary", use_container_width=True):
            result = make_api_post("/ingest/test/generic")
            if result and result.get("success"):
                st.success(f"✅ Ingested {result.get('sessions_processed', 0)} sessions")
            else:
                st.warning("Ingest test returned no result")

    with col2:
        if st.button("🧪 Run Evaluation", type="secondary", use_container_width=True):
            with st.spinner("Running evaluation..."):
                result = make_api_post("/evaluation/evaluate-batch", {"hours_back": 0.5})
                if result and result.get("success"):
                    st.success(f"✅ Evaluated {result.get('evaluations_completed', 0)} interactions")
                else:
                    st.warning("⚠️ Evaluation system not available or no new logs")

    with col3:
        if st.button("🔍 Analyze Patterns", type="secondary", use_container_width=True):
            with st.spinner("Analyzing patterns..."):
                result = make_api_post("/patterns/analyze", {"hours_back": hours_back, "min_pattern_count": 3})
                if result and result.get("success"):
                    st.success(f"✅ Detected {result.get('patterns_detected', 0)} patterns")
                else:
                    st.warning("⚠️ Pattern analysis failed or no eval data")


def render_usage_analytics_page(hours_back: int):
    """Render usage analytics dashboard"""
    st.markdown('<h1 class="main-header">📈 Usage Analytics</h1>', unsafe_allow_html=True)

    # Session volume (list of time points)
    st.subheader("📊 Session Volume Over Time")
    volume_list = make_api_get("/analytics/session-volume", {"hours_back": hours_back, "granularity": "day"})

    if volume_list:
        df = pd.DataFrame(volume_list)
        if not df.empty:
            fig = px.area(
                df, x="timestamp", y="session_count",
                title=f"Session Volume (last {hours_back}h)",
                labels={"session_count": "Sessions", "timestamp": "Time"}
            )
            fig.update_traces(fill="tonexty")
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No session data for the selected time range.")
    else:
        st.info("Session volume data not available.")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🎯 Intent Performance")
        # intent-performance returns a list directly
        intent_list = make_api_get("/analytics/intent-performance", {"limit": 10})

        if intent_list:
            intent_df = pd.DataFrame(intent_list)

            fig = px.pie(
                intent_df, values="session_count", names="intent",
                title="Intent Distribution"
            )
            fig.update_layout(height=350)
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("**Intent Performance:**")
            for intent in intent_list:
                cr = intent.get("completion_rate", 0)
                color = "success" if cr > 0.8 else "warning" if cr > 0.6 else "danger"
                st.markdown(f"""
                <div class="metric-card">
                    <strong>{intent['intent'].replace('_',' ').title()}</strong><br>
                    Sessions: {intent['session_count']} |
                    Completion: <span class="status-{color}">{cr:.1%}</span> |
                    Avg Steps: {intent['avg_steps']:.1f} |
                    Grade: <b>{intent['performance_grade']}</b>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No intent data available.")

    with col2:
        st.subheader("📉 Drop-off Analysis")
        # dropoff-analysis returns a list directly
        dropoff_list = make_api_get("/analytics/dropoff-analysis")

        if dropoff_list:
            dropoff_df = pd.DataFrame(dropoff_list)

            fig = px.bar(
                dropoff_df, x="step", y="dropoff_count",
                title="Drop-off Count by Workflow Step",
                labels={"dropoff_count": "Sessions Dropped Off", "step": "Workflow Step"},
                color="impact_score",
                color_continuous_scale="Reds"
            )
            fig.update_layout(height=350)
            st.plotly_chart(fig, use_container_width=True)

            critical = [d for d in dropoff_list if d.get("dropoff_rate", 0) > 0.05]
            if critical:
                st.warning(f"⚠️ High drop-off at steps: {', '.join(str(d['step']) for d in critical[:3])}")
        else:
            st.info("No drop-off data available.")

    # Tool usage
    st.subheader("🔧 Tool Usage & Performance")
    tool_list = make_api_get("/analytics/tool-performance")

    if tool_list:
        col1, col2 = st.columns(2)
        tool_df = pd.DataFrame(tool_list)

        with col1:
            fig = px.bar(
                tool_df, x="usage_count", y="tool_name",
                orientation="h", title="Tool Usage Frequency"
            )
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            fig = px.scatter(
                tool_df, x="usage_count", y="success_rate",
                size="avg_response_time_ms",
                hover_data=["tool_name"],
                title="Tool Performance (Size = Response Time)",
                labels={"success_rate": "Success Rate", "usage_count": "Usage Count"}
            )
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No tool usage data available.")


def render_loss_patterns_page(hours_back: int):
    """Render loss patterns analysis dashboard"""
    st.markdown('<h1 class="main-header">🎯 Loss Patterns</h1>', unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)

    with col1:
        min_pattern_count = st.slider("Min Pattern Count", 1, 10, 3)
    with col2:
        pattern_type_filter = st.selectbox("Pattern Type", ["All", "Intent", "Step", "Tool", "Topic"])
    with col3:
        if st.button("🔄 Refresh Analysis", type="primary"):
            st.rerun()

    # patterns/analyze is POST
    pattern_data = make_api_post("/patterns/analyze", {
        "hours_back": hours_back,
        "min_pattern_count": min_pattern_count
    })

    if not pattern_data or not pattern_data.get("success"):
        st.info("No pattern analysis results. Run evaluations first to generate eval data.")
        if pattern_data:
            st.error(f"Error: {pattern_data.get('detail', 'Unknown error')}")
        return

    total_failures = pattern_data.get("total_failures", 0)
    patterns = pattern_data.get("top_failure_patterns", [])

    if total_failures == 0:
        st.info("No failures detected. Upload agent logs and run evaluations to see patterns.")
        return

    insights = pattern_data.get("key_insights", {})

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Failures Analyzed", f"{total_failures:,}", delta=f"{len(patterns)} patterns found")
    with col2:
        top_intent_pct = insights.get("top_3_intents_failure_pct", 0)
        st.metric("Top 3 Intents Coverage", f"{top_intent_pct:.1f}%")
    with col3:
        problematic = insights.get("most_problematic_intent", "None") or "None"
        st.metric("Most Problematic Intent", problematic.replace("_", " ").title())

    st.markdown("---")

    if pattern_type_filter != "All":
        patterns = [p for p in patterns if p["pattern_type"].lower() == pattern_type_filter.lower()]

    if not patterns:
        st.info(f"No {pattern_type_filter.lower()} patterns found with minimum count of {min_pattern_count}.")
        return

    st.subheader("📊 Detected Patterns")
    pattern_df = pd.DataFrame([
        {
            "Pattern": p["pattern_value"],
            "Type": p["pattern_type"].title(),
            "Failures": p["failure_count"],
            "Failure Rate": f"{p['failure_rate']:.1%}",
            "% of All Failures": f"{p['pct_of_all_failures']:.1f}%",
            "Avg Quality": f"{p['avg_quality_score']:.2f}",
        }
        for p in patterns[:10]
    ])
    st.dataframe(pattern_df, use_container_width=True)

    col1, col2 = st.columns(2)

    with col1:
        fig = px.bar(
            x=[p["pattern_value"] for p in patterns[:8]],
            y=[p["failure_count"] for p in patterns[:8]],
            title="Failure Count by Pattern",
            labels={"x": "Pattern", "y": "Failure Count"}
        )
        fig.update_xaxes(tickangle=45)
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        type_counts = {}
        for p in patterns:
            ptype = p["pattern_type"].title()
            type_counts[ptype] = type_counts.get(ptype, 0) + p["failure_count"]
        if type_counts:
            fig = px.pie(
                values=list(type_counts.values()),
                names=list(type_counts.keys()),
                title="Failure Distribution by Pattern Type"
            )
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("🔍 Pattern Details")
    selected_pattern = st.selectbox(
        "Select pattern for detailed analysis:",
        [f"{p['pattern_type'].title()}: {p['pattern_value']}" for p in patterns]
    )

    if selected_pattern:
        pattern_idx = next(
            i for i, p in enumerate(patterns)
            if f"{p['pattern_type'].title()}: {p['pattern_value']}" == selected_pattern
        )
        pattern = patterns[pattern_idx]

        col1, col2 = st.columns([2, 1])

        with col1:
            st.markdown(f"""
            **Pattern:** {pattern['pattern_value']}
            **Type:** {pattern['pattern_type'].title()}
            **Impact:** {pattern['failure_count']} failures ({pattern['pct_of_all_failures']:.1f}% of total)
            **Failure Rate:** {pattern['failure_rate']:.1%}
            **Quality Score:** {pattern['avg_quality_score']:.2f}/1.0
            """)

            if pattern.get("root_cause"):
                st.success(f"**Root Cause:** {pattern['root_cause']}")
            if pattern.get("suggested_fix"):
                st.info(f"**Suggested Fix:** {pattern['suggested_fix']}")

        with col2:
            severity = "High" if pattern["pct_of_all_failures"] > 20 else "Medium" if pattern["pct_of_all_failures"] > 10 else "Low"
            severity_color = "🔴" if severity == "High" else "🟡" if severity == "Medium" else "🟢"
            st.markdown(f"""
            <div class="metric-card">
                <h4>{severity_color} Severity: {severity}</h4>
                <p>Priority: {'Immediate' if severity == 'High' else 'High' if severity == 'Medium' else 'Normal'}</p>
            </div>
            """, unsafe_allow_html=True)


def render_interaction_detail_page(hours_back: int):
    """Render interaction detail view"""
    st.markdown('<h1 class="main-header">💬 Interaction Detail</h1>', unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)

    with col1:
        intent_filter = st.selectbox(
            "Filter by Intent:",
            ["All", "billing", "refunds", "subscriptions", "account_recovery", "general_enquiry"]
        )

    with col2:
        quality_filter = st.selectbox(
            "Quality Filter:",
            ["All", "High Quality (>0.8)", "Good Quality (0.6-0.8)", "Poor Quality (<0.6)", "Failures Only (<0.7)"]
        )

    with col3:
        limit = st.slider("Max Results", 10, 100, 20)

    # quality-by-intent returns a list
    quality_list = make_api_get("/analytics/quality-by-intent")

    if quality_list:
        st.subheader("📊 Quality by Intent")
        quality_df = pd.DataFrame(quality_list)

        fig = px.bar(
            quality_df, x="intent", y="pass_rate",
            title="Pass Rate by Intent (threshold: 0.7)",
            labels={"pass_rate": "Pass Rate", "intent": "Intent"},
            color="pass_rate",
            color_continuous_scale="RdYlGn",
            range_color=[0, 1]
        )
        fig.add_hline(y=0.7, line_dash="dash", line_color="red", annotation_text="Pass threshold")
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)

        for q in quality_list:
            color = "success" if q["pass_rate"] > 0.8 else "warning" if q["pass_rate"] > 0.6 else "danger"
            st.markdown(f"""
            <div class="metric-card">
                <strong>{q['intent'].replace('_',' ').title()}</strong><br>
                Pass Rate: <span class="status-{color}">{q['pass_rate']:.1%}</span> |
                Avg Score: {q['avg_quality_score']:.2f} |
                Sample: {q['sample_size']} sessions |
                vs Benchmark: <b>{q['benchmark_comparison'].title()}</b>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No quality data available yet.")

    st.markdown("---")
    st.subheader("📤 Export Options")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("🎯 Export Pattern Fixes", type="secondary", use_container_width=True):
            pattern_export = make_api_get("/patterns/export/developer", {"hours_back": hours_back})
            if pattern_export:
                st.download_button(
                    "⬇️ Download Pattern Data",
                    data=json.dumps(pattern_export, indent=2),
                    file_name="agentiq_patterns.json",
                    mime="application/json"
                )

    with col2:
        if st.button("🤖 Export for RL Training", type="secondary", use_container_width=True):
            rl_export = make_api_get("/patterns/export/developer", {
                "format": "reinforcement_learning",
                "hours_back": hours_back
            })
            if rl_export:
                st.download_button(
                    "⬇️ Download RL Training Data",
                    data=json.dumps(rl_export, indent=2),
                    file_name="agentiq_training_data.json",
                    mime="application/json"
                )


def main():
    """Main dashboard application"""
    current_page, hours_back = render_sidebar()

    if current_page == "Overview":
        render_overview_page(hours_back)
    elif current_page == "Usage Analytics":
        render_usage_analytics_page(hours_back)
    elif current_page == "Loss Patterns":
        render_loss_patterns_page(hours_back)
    elif current_page == "Interaction Detail":
        render_interaction_detail_page(hours_back)

    st.markdown("---")
    st.markdown(
        "🤖 **AgentIQ** — Agent observability and loss pattern analysis | "
        "[API Docs](http://localhost:8000/docs)"
    )


if __name__ == "__main__":
    main()
