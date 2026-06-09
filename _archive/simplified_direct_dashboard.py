"""
AgentIQ Coding Agent Dashboard - Direct Data Query Version
Shows real metrics directly from agent_logs for immediate insights
"""

import streamlit as st
import requests
import pandas as pd
import plotly.express as px
from datetime import datetime

st.set_page_config(page_title="AgentIQ - Coding Agent Analytics", page_icon="👨‍💻", layout="wide")

API_BASE_URL = "https://agentiq-api-z9it.onrender.com"

def get_data(endpoint):
    """Fetch data from AgentIQ API with error handling"""
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

def get_raw_data(endpoint, json_data=None):
    """Get raw data with POST request"""
    try:
        if json_data:
            response = requests.post(f"{API_BASE_URL}{endpoint}", json=json_data, timeout=30)
        else:
            response = requests.get(f"{API_BASE_URL}{endpoint}", timeout=30)
        
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"API Error {response.status_code}: {response.text}")
            return None
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
        return None

# Header
st.markdown("# 👨‍💻 Coding Agent Performance Dashboard")
st.markdown("**Real-time monitoring of AI coding assistant performance**")

# System Status
col1, col2, col3 = st.columns(3)
with col1:
    health = get_data("/health")
    st.metric("🔌 System Status", "Online" if health else "Offline")

with col2:
    db_status = get_data("/admin/database-status") 
    if db_status:
        tables = len(db_status.get("existing_tables", []))
        st.metric("🗄️ Database", f"{tables} tables ready")

with col3:
    eval_health = get_data("/evaluation/health")
    eval_status = "Ready" if eval_health and eval_health.get("status") == "healthy" else "Issues"
    st.metric("🧠 AI Evaluation", eval_status)

st.markdown("---")

# Raw Data from Agent Logs
st.subheader("📊 Live Coding Agent Activity")

# Get recent agent logs
raw_logs = get_raw_data("/ingest/recent-logs", {"limit": 1000})

if raw_logs and raw_logs.get("logs"):
    logs = raw_logs["logs"]
    df = pd.DataFrame(logs)
    
    # Process coding intents
    coding_intents = ["code_generation", "debugging", "code_review", "api_development", "test_generation", "git_help"]
    coding_logs = df[df["intent"].isin(coding_intents)] if "intent" in df.columns else df
    
    if len(coding_logs) > 0:
        # Key metrics
        total_sessions = coding_logs["session_id"].nunique()
        total_interactions = len(coding_logs)
        avg_response_time = coding_logs["response_time_ms"].mean() if "response_time_ms" in coding_logs.columns else 0
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("🎯 Coding Sessions", f"{total_sessions:,}")
        with col2: 
            st.metric("💬 Total Interactions", f"{total_interactions:,}")
        with col3:
            st.metric("⏱️ Avg Response Time", f"{avg_response_time:.0f}ms")
        with col4:
            unique_intents = coding_logs["intent"].nunique() if "intent" in coding_logs.columns else 1
            st.metric("🛠️ Task Types", f"{unique_intents}")
        
        # Intent Distribution
        st.markdown("---")
        st.subheader("🎯 Coding Task Distribution")
        
        if "intent" in coding_logs.columns:
            intent_counts = coding_logs["intent"].value_counts()
            
            # Create meaningful names
            intent_names = {
                "code_generation": "Code Generation",
                "debugging": "Debugging & Troubleshooting", 
                "code_review": "Code Review & Quality",
                "api_development": "API Development",
                "test_generation": "Test Writing",
                "git_help": "Version Control Help"
            }
            
            intent_display = intent_counts.rename(intent_names).reset_index()
            intent_display.columns = ["Task Type", "Count"]
            
            col1, col2 = st.columns([2, 1])
            
            with col1:
                fig = px.bar(intent_display, x="Count", y="Task Type", orientation='h',
                           title="Distribution of Coding Tasks",
                           color="Count", color_continuous_scale="viridis")
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                st.markdown("### 📈 Task Breakdown")
                for _, row in intent_display.iterrows():
                    percentage = (row["Count"] / total_interactions) * 100
                    st.markdown(f"**{row['Task Type']}**: {row['Count']} ({percentage:.1f}%)")
        
        # Response Time Analysis
        st.markdown("---")
        st.subheader("⏱️ Performance Analysis")
        
        if "response_time_ms" in coding_logs.columns and "intent" in coding_logs.columns:
            # Response time by intent
            response_by_intent = coding_logs.groupby("intent")["response_time_ms"].agg(['mean', 'count', 'std']).reset_index()
            response_by_intent.columns = ["Intent", "Avg_Response_ms", "Count", "Std_Dev"]
            response_by_intent["Avg_Response_sec"] = response_by_intent["Avg_Response_ms"] / 1000
            
            # Map to display names
            response_by_intent["Task Type"] = response_by_intent["Intent"].map(intent_names).fillna(response_by_intent["Intent"])
            
            col1, col2 = st.columns(2)
            
            with col1:
                fig = px.bar(response_by_intent, x="Task Type", y="Avg_Response_sec",
                           title="Average Response Time by Task Type",
                           color="Avg_Response_sec", color_continuous_scale="RdYlGn_r")
                fig.update_layout(xaxis_tickangle=-45)
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                fig = px.scatter(response_by_intent, x="Avg_Response_sec", y="Count", 
                               size="Count", hover_name="Task Type",
                               title="Response Time vs Volume",
                               labels={"Avg_Response_sec": "Avg Response Time (sec)", "Count": "Number of Interactions"})
                st.plotly_chart(fig, use_container_width=True)
        
        # Recent Activity Timeline
        st.markdown("---")
        st.subheader("📈 Recent Activity Timeline")
        
        if "timestamp" in coding_logs.columns:
            coding_logs["timestamp"] = pd.to_datetime(coding_logs["timestamp"])
            coding_logs["hour"] = coding_logs["timestamp"].dt.floor("H")
            
            hourly_activity = coding_logs.groupby("hour").size().reset_index()
            hourly_activity.columns = ["Hour", "Interactions"]
            
            fig = px.line(hourly_activity, x="Hour", y="Interactions",
                         title="Coding Agent Activity Over Time",
                         markers=True)
            st.plotly_chart(fig, use_container_width=True)
        
        # Recent Sessions Table
        st.markdown("---")
        st.subheader("🔍 Recent Coding Sessions")
        
        # Show recent sessions with key info
        recent_sessions = coding_logs.head(20)[["session_id", "intent", "user_input", "response_time_ms", "timestamp"]].copy()
        
        if not recent_sessions.empty:
            # Truncate long user inputs for display
            recent_sessions["user_input"] = recent_sessions["user_input"].str[:100] + "..."
            recent_sessions["Response Time (ms)"] = recent_sessions["response_time_ms"]
            recent_sessions["Task Type"] = recent_sessions["intent"].map(intent_names).fillna(recent_sessions["intent"])
            
            display_df = recent_sessions[["session_id", "Task Type", "user_input", "Response Time (ms)", "timestamp"]]
            display_df.columns = ["Session ID", "Task Type", "User Request", "Response Time (ms)", "Timestamp"]
            
            st.dataframe(display_df, use_container_width=True)
        
        # Insights Section
        st.markdown("---")
        st.subheader("💡 Key Insights")
        
        # Calculate some insights
        fastest_intent = response_by_intent.loc[response_by_intent["Avg_Response_ms"].idxmin()] if not response_by_intent.empty else None
        slowest_intent = response_by_intent.loc[response_by_intent["Avg_Response_ms"].idxmax()] if not response_by_intent.empty else None
        most_popular = intent_counts.index[0] if not intent_counts.empty else "N/A"
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### ⚡ Performance Highlights")
            if fastest_intent is not None:
                st.markdown(f"• **Fastest responses**: {fastest_intent['Task Type']} ({fastest_intent['Avg_Response_sec']:.1f}s avg)")
            if slowest_intent is not None:
                st.markdown(f"• **Needs optimization**: {slowest_intent['Task Type']} ({slowest_intent['Avg_Response_sec']:.1f}s avg)")
            st.markdown(f"• **Most popular task**: {intent_names.get(most_popular, most_popular)}")
        
        with col2:
            st.markdown("### 📊 Activity Summary")
            st.markdown(f"• **Active sessions**: {total_sessions:,}")
            st.markdown(f"• **Total interactions**: {total_interactions:,}")
            st.markdown(f"• **Avg interactions per session**: {total_interactions/total_sessions:.1f}")
    
    else:
        st.warning("No coding agent data found in recent logs. Try loading some coding sessions first.")

else:
    st.error("Unable to fetch agent log data. Check API connection.")

# Footer
st.markdown("---")
st.markdown(f"**Live AgentIQ Analytics** | API: {API_BASE_URL} | Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
st.markdown("💡 **Data Source**: Direct queries from agent_logs table for real-time insights")