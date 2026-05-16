"""
Simple AgentIQ Dashboard - Quick deployment to any hosting service
View session analytics and evaluation results in real-time
"""

import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

st.set_page_config(
    page_title="AgentIQ Dashboard", 
    page_icon="🤖",
    layout="wide"
)

# API Configuration
API_BASE_URL = "https://agentiq-api-z9it.onrender.com"

def get_data(endpoint):
    """Fetch data from AgentIQ API"""
    try:
        response = requests.get(f"{API_BASE_URL}{endpoint}", timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"API Error {response.status_code}: {response.text}")
            return None
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
        return None

# Dashboard Header
st.markdown("# 🤖 AgentIQ - Agent Performance Dashboard")
st.markdown("**Real-time monitoring of agent conversations, evaluations, and analytics**")

# System Health Check
col1, col2, col3 = st.columns(3)

with col1:
    health = get_data("/health")
    if health:
        st.success("✅ API Online")
    else:
        st.error("❌ API Offline")

with col2:
    eval_health = get_data("/evaluation/health")
    if eval_health and eval_health.get("status") == "healthy":
        st.success("✅ Evaluation System")
    else:
        st.warning("⚠️ Evaluation Issues")

with col3:
    db_status = get_data("/admin/database-status")
    if db_status and db_status.get("database_connected"):
        st.success("✅ Database Connected")
    else:
        st.error("❌ Database Issues")

st.markdown("---")

# Main Metrics
st.subheader("📊 Key Metrics")

col1, col2, col3, col4 = st.columns(4)

# Session Volume
session_data = get_data("/analytics/session-volume")
if session_data:
    total_sessions = sum(point["session_count"] for point in session_data)
    total_interactions = sum(point["interaction_count"] for point in session_data)
    avg_completion = sum(point["completion_rate"] for point in session_data) / len(session_data) if session_data else 0
    
    with col1:
        st.metric("Total Sessions", total_sessions)
    with col2:
        st.metric("Total Interactions", total_interactions)
    with col3:
        st.metric("Avg Completion Rate", f"{avg_completion:.1%}")
    with col4:
        if session_data:
            st.metric("Last Updated", session_data[-1]["timestamp"][:10])

# Analytics Charts
st.markdown("---")
col1, col2 = st.columns(2)

with col1:
    st.subheader("📈 Session Volume Over Time")
    if session_data:
        df = pd.DataFrame(session_data)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        fig = px.line(df, x='timestamp', y='session_count', 
                     title="Sessions per Hour",
                     labels={'session_count': 'Sessions', 'timestamp': 'Time'})
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("No session volume data available")

with col2:
    st.subheader("🎯 Intent Performance")
    intent_data = get_data("/analytics/intent-performance")
    if intent_data:
        df_intent = pd.DataFrame(intent_data)
        
        fig = px.bar(df_intent, x='intent', y='completion_rate',
                    title="Completion Rate by Intent",
                    labels={'completion_rate': 'Completion Rate', 'intent': 'Intent'})
        fig.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("No intent performance data available")

# Quality Analytics
st.markdown("---")
st.subheader("⭐ Quality Analysis")

quality_data = get_data("/analytics/quality-by-intent")
if quality_data:
    df_quality = pd.DataFrame(quality_data)
    
    col1, col2 = st.columns(2)
    
    with col1:
        fig = px.scatter(df_quality, x='sample_size', y='pass_rate',
                        hover_name='intent', size='avg_quality_score',
                        title="Quality vs Sample Size by Intent")
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.subheader("Quality Metrics Table")
        display_df = df_quality[['intent', 'pass_rate', 'avg_quality_score', 'sample_size']].copy()
        display_df['pass_rate'] = display_df['pass_rate'].apply(lambda x: f"{x:.1%}")
        display_df['avg_quality_score'] = display_df['avg_quality_score'].apply(lambda x: f"{x:.2f}")
        st.dataframe(display_df, use_container_width=True)
else:
    st.warning("No quality data available")

# Raw Data Explorer
st.markdown("---")
st.subheader("🔍 API Explorer")

endpoint_options = [
    "/analytics/session-volume",
    "/analytics/intent-performance", 
    "/analytics/quality-by-intent",
    "/analytics/dropoff-analysis",
    "/analytics/tool-performance",
    "/evaluation/health",
    "/admin/database-status"
]

selected_endpoint = st.selectbox("Select API endpoint to explore:", endpoint_options)

if st.button("Fetch Data"):
    raw_data = get_data(selected_endpoint)
    if raw_data:
        st.json(raw_data)
    else:
        st.error("Failed to fetch data")

# Footer
st.markdown("---")
st.markdown(f"**AgentIQ Dashboard** | API: {API_BASE_URL} | Last refresh: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")