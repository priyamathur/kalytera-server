"""
AgentIQ Coding Agent Dashboard - Clear, Interpretable Analytics
Shows real metrics that matter for coding assistant performance
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

# Header
st.markdown("# 👨‍💻 Coding Agent Performance Dashboard")
st.markdown("**Monitor your AI coding assistant's effectiveness across different programming tasks**")

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

# Key Metrics Overview  
st.subheader("📊 Coding Assistant Overview")

session_data = get_data("/analytics/session-volume")
intent_data = get_data("/analytics/intent-performance")

if session_data and intent_data:
    total_sessions = sum(point["session_count"] for point in session_data)
    total_interactions = sum(point["interaction_count"] for point in session_data)
    
    # Calculate meaningful metrics
    coding_sessions = len([i for i in intent_data if i["intent"] in ["code_generation", "debugging", "code_review", "api_development"]])
    avg_success_rate = sum(i["completion_rate"] for i in intent_data) / len(intent_data) if intent_data else 0
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("🎯 Total Coding Sessions", f"{total_sessions:,}")
    with col2: 
        st.metric("💬 Developer Interactions", f"{total_interactions:,}")
    with col3:
        st.metric("✅ Average Success Rate", f"{avg_success_rate:.1%}")
    with col4:
        st.metric("🛠️ Task Types Handled", f"{len(intent_data)} types")

# Task Performance Analysis
st.markdown("---")
st.subheader("🎯 Performance by Coding Task Type")

if intent_data:
    df_intent = pd.DataFrame(intent_data)
    
    # Create meaningful explanations for each intent
    intent_explanations = {
        "code_generation": "Writing new functions, classes, algorithms",
        "debugging": "Finding and fixing bugs, error analysis", 
        "code_review": "Code quality assessment, optimization suggestions",
        "api_development": "REST/GraphQL API creation, endpoint design",
        "test_generation": "Writing unit tests, integration tests",
        "git_help": "Version control, merge conflicts, branching"
    }
    
    # Add explanations to the dataframe
    df_intent['task_description'] = df_intent['intent'].map(intent_explanations).fillna("Other coding tasks")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Performance chart
        fig = px.bar(df_intent, 
                    x='completion_rate', 
                    y='intent',
                    orientation='h',
                    title="Task Completion Rates",
                    labels={'completion_rate': 'Success Rate (%)', 'intent': 'Task Type'},
                    color='completion_rate',
                    color_continuous_scale='RdYlGn')
        
        # Format as percentages
        fig.update_traces(texttemplate='%{x:.1%}', textposition='outside')
        fig.update_layout(xaxis_tickformat=',.1%')
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.markdown("### 📈 Task Performance Guide")
        for _, row in df_intent.iterrows():
            intent = row['intent']
            rate = row['completion_rate'] 
            grade = row.get('performance_grade', 'N/A')
            
            # Color code by performance
            color = "🟢" if rate > 0.8 else "🟡" if rate > 0.6 else "🔴"
            
            st.markdown(f"""
            **{color} {intent.replace('_', ' ').title()}**  
            Success Rate: {rate:.1%} (Grade: {grade})  
            Sessions: {row['session_count']}  
            __{intent_explanations.get(intent, 'N/A')}__
            """)

# Session Volume Trends
st.markdown("---")
col1, col2 = st.columns(2)

with col1:
    st.subheader("📈 Coding Activity Over Time")
    if session_data:
        df_volume = pd.DataFrame(session_data)
        df_volume['timestamp'] = pd.to_datetime(df_volume['timestamp'])
        df_volume['date'] = df_volume['timestamp'].dt.date
        
        daily_volume = df_volume.groupby('date').agg({
            'session_count': 'sum',
            'interaction_count': 'sum'
        }).reset_index()
        
        fig = px.line(daily_volume, x='date', y='session_count',
                     title="Daily Coding Sessions",
                     labels={'session_count': 'Sessions', 'date': 'Date'})
        st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("⏱️ Response Time Analysis")
    if intent_data:
        # Convert response times to interpretable metrics
        df_intent['avg_response_seconds'] = df_intent['avg_duration_seconds'] / 1000
        
        fig = px.scatter(df_intent, 
                        x='avg_response_seconds', 
                        y='completion_rate',
                        size='session_count',
                        hover_name='intent',
                        title="Response Time vs Success Rate",
                        labels={'avg_response_seconds': 'Avg Response Time (sec)', 
                               'completion_rate': 'Success Rate'})
        st.plotly_chart(fig, use_container_width=True)

# Detailed Task Analysis
st.markdown("---")
st.subheader("🔍 Detailed Task Analysis")

if intent_data:
    df_display = df_intent[['intent', 'session_count', 'completion_rate', 'avg_steps', 'avg_success_score', 'performance_grade']].copy()
    df_display.columns = ['Task Type', 'Sessions', 'Success Rate', 'Avg Steps', 'Quality Score', 'Grade']
    
    # Format for display
    df_display['Success Rate'] = df_display['Success Rate'].apply(lambda x: f"{x:.1%}")
    df_display['Quality Score'] = df_display['Quality Score'].apply(lambda x: f"{x:.2f}")
    df_display['Avg Steps'] = df_display['Avg Steps'].apply(lambda x: f"{x:.1f}")
    
    st.dataframe(df_display, use_container_width=True)
    
    # Insights
    best_task = intent_data[0]['intent'] if intent_data else "N/A" 
    worst_task = min(intent_data, key=lambda x: x['completion_rate'])['intent'] if intent_data else "N/A"
    
    st.markdown(f"""
    ### 💡 Key Insights
    - **Best performing task**: {best_task.replace('_', ' ').title()}
    - **Needs improvement**: {worst_task.replace('_', ' ').title()}
    - **Total developer interactions**: {total_interactions:,}
    - **Average session complexity**: {df_intent['avg_steps'].mean():.1f} steps per session
    """)

# Footer
st.markdown("---")
st.markdown(f"**Live AgentIQ Analytics** | API: {API_BASE_URL} | Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
st.markdown("💡 **How to interpret**: Success Rate = % of tasks completed successfully | Quality Score = AI-evaluated response quality (0-1) | Grade = Overall performance rating")