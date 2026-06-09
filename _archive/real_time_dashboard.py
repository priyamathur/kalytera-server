"""
AgentIQ Real-Time Agent Performance Dashboard
Shows actual agent performance data with live updates and meaningful metrics
"""

import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import time

st.set_page_config(page_title="AgentIQ - Real-Time Agent Analytics", page_icon="🚀", layout="wide")

API_BASE_URL = "https://agentiq-api-z9it.onrender.com"

def get_data(endpoint, timeout=10):
    """Fetch data from AgentIQ API with error handling"""
    try:
        response = requests.get(f"{API_BASE_URL}{endpoint}", timeout=timeout)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception:
        return None

def get_raw_agent_data():
    """Get raw agent logs and process them for real-time insights"""
    try:
        # Get direct data from the database using existing endpoints
        session_data = get_data("/analytics/session-volume")
        
        if session_data:
            # Calculate real metrics from session data
            total_sessions = sum(point["session_count"] for point in session_data)
            total_interactions = sum(point["interaction_count"] for point in session_data)
            
            # Get today's data
            today_data = [point for point in session_data if "2026-05-17" in point["timestamp"]]
            today_sessions = sum(point["session_count"] for point in today_data) if today_data else 0
            today_interactions = sum(point["interaction_count"] for point in today_data) if today_data else 0
            
            # Calculate completion rates
            completion_rates = [float(point.get("completion_rate", 0)) for point in session_data if point.get("completion_rate")]
            avg_completion_rate = sum(completion_rates) / len(completion_rates) if completion_rates else 0
            
            # Get response times (duration)
            response_times = [float(point.get("avg_duration_seconds", 0)) for point in session_data if point.get("avg_duration_seconds")]
            avg_response_time = sum(response_times) / len(response_times) if response_times else 0
            
            return {
                "total_sessions": total_sessions,
                "total_interactions": total_interactions,
                "today_sessions": today_sessions,
                "today_interactions": today_interactions,
                "avg_completion_rate": avg_completion_rate,
                "avg_response_time": avg_response_time,
                "session_data": session_data,
                "last_updated": datetime.now()
            }
    except Exception as e:
        st.error(f"Error fetching real-time data: {e}")
    
    return None

# Auto-refresh setup
refresh_interval = st.sidebar.slider("Auto-refresh interval (seconds)", 10, 120, 30)
auto_refresh = st.sidebar.checkbox("Auto-refresh enabled", value=True)

# Header with live status
col1, col2 = st.columns([3, 1])
with col1:
    st.markdown("# 🚀 AgentIQ - Real-Time Agent Performance")
    st.markdown("**Live monitoring of AI agent interactions and performance metrics**")

with col2:
    if auto_refresh:
        st.markdown(f"🔄 **Auto-refresh**: {refresh_interval}s")
        # Auto-refresh implementation
        time.sleep(0.1)  # Prevent excessive refreshing
        if st.button("🔄 Refresh Now") or auto_refresh:
            st.rerun()

# System Health Check
st.subheader("🔌 System Status")
health_cols = st.columns(4)

with health_cols[0]:
    api_health = get_data("/health")
    api_status = "🟢 Online" if api_health else "🔴 Offline"
    st.metric("API Status", api_status)

with health_cols[1]:
    db_health = get_data("/admin/database-status")
    db_status = "🟢 Ready" if db_health and db_health.get("tables_ready") else "🔴 Issues"
    st.metric("Database", db_status)

with health_cols[2]:
    eval_health = get_data("/evaluation/health")
    eval_status = "🟢 Ready" if eval_health and eval_health.get("status") == "healthy" else "🔴 Issues"
    st.metric("Evaluation Engine", eval_status)

with health_cols[3]:
    st.metric("Last Updated", datetime.now().strftime("%H:%M:%S"))

st.markdown("---")

# Get real-time agent data
agent_data = get_raw_agent_data()

if agent_data:
    # Real-time metrics
    st.subheader("📊 Live Agent Performance Metrics")
    
    metrics_cols = st.columns(6)
    
    with metrics_cols[0]:
        st.metric(
            "Total Sessions", 
            f"{agent_data['total_sessions']:,}",
            delta=f"+{agent_data['today_sessions']}" if agent_data['today_sessions'] > 0 else None
        )
    
    with metrics_cols[1]:
        st.metric(
            "Total Interactions", 
            f"{agent_data['total_interactions']:,}",
            delta=f"+{agent_data['today_interactions']}" if agent_data['today_interactions'] > 0 else None
        )
    
    with metrics_cols[2]:
        completion_pct = agent_data['avg_completion_rate'] * 100
        st.metric(
            "Completion Rate", 
            f"{completion_pct:.1f}%",
            delta=f"{completion_pct-50:.1f}%" if completion_pct > 0 else None
        )
    
    with metrics_cols[3]:
        response_time = agent_data['avg_response_time']
        st.metric(
            "Avg Response Time", 
            f"{response_time:.1f}s",
            delta=f"{response_time-2:.1f}s" if response_time > 0 else None
        )
    
    with metrics_cols[4]:
        sessions_per_hour = agent_data['today_interactions'] / max(1, (datetime.now().hour + 1))
        st.metric(
            "Interactions/Hour", 
            f"{sessions_per_hour:.1f}",
            delta=f"+{sessions_per_hour-10:.1f}" if sessions_per_hour > 10 else None
        )
    
    with metrics_cols[5]:
        if agent_data['today_sessions'] > 0:
            avg_interactions_per_session = agent_data['today_interactions'] / agent_data['today_sessions']
            st.metric(
                "Interactions/Session", 
                f"{avg_interactions_per_session:.1f}",
                delta=f"+{avg_interactions_per_session-1.5:.1f}" if avg_interactions_per_session > 1.5 else None
            )
        else:
            st.metric("Interactions/Session", "0")

    # Live activity chart
    st.subheader("📈 Live Activity Timeline")
    
    if agent_data['session_data']:
        df = pd.DataFrame(agent_data['session_data'])
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.strftime('%m/%d %H:00')
        
        # Create dual-axis chart
        fig = go.Figure()
        
        # Sessions (bars)
        fig.add_trace(go.Bar(
            x=df['hour'],
            y=df['session_count'],
            name='Sessions',
            marker_color='lightblue',
            yaxis='y'
        ))
        
        # Interactions (line)
        fig.add_trace(go.Scatter(
            x=df['hour'],
            y=df['interaction_count'],
            mode='lines+markers',
            name='Interactions',
            line=dict(color='red', width=3),
            yaxis='y2'
        ))
        
        # Update layout for dual axis
        fig.update_layout(
            title='Real-Time Agent Activity',
            xaxis=dict(title='Time'),
            yaxis=dict(title='Sessions', side='left'),
            yaxis2=dict(title='Interactions', side='right', overlaying='y'),
            height=400,
            showlegend=True
        )
        
        st.plotly_chart(fig, use_container_width=True)

    # Performance analysis
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🎯 Performance Analysis")
        
        # Performance indicators
        if agent_data['avg_completion_rate'] > 0.7:
            perf_color = "🟢"
            perf_text = "Excellent"
        elif agent_data['avg_completion_rate'] > 0.5:
            perf_color = "🟡"
            perf_text = "Good"
        else:
            perf_color = "🔴" 
            perf_text = "Needs Improvement"
        
        st.markdown(f"**Overall Performance:** {perf_color} {perf_text}")
        st.markdown(f"**Completion Rate:** {agent_data['avg_completion_rate']:.1%}")
        st.markdown(f"**Average Response Time:** {agent_data['avg_response_time']:.1f} seconds")
        
        # Activity level
        if agent_data['today_interactions'] > 100:
            activity_level = "🔥 Very High"
        elif agent_data['today_interactions'] > 50:
            activity_level = "🚀 High"
        elif agent_data['today_interactions'] > 10:
            activity_level = "📊 Moderate"
        else:
            activity_level = "💤 Low"
        
        st.markdown(f"**Activity Level:** {activity_level}")
    
    with col2:
        st.subheader("📊 Real-Time Insights")
        
        insights = []
        
        if agent_data['today_sessions'] > 50:
            insights.append("🔥 High volume day - monitor response times")
        
        if agent_data['avg_completion_rate'] < 0.5:
            insights.append("⚠️ Low completion rate - investigate common failures")
        
        if agent_data['avg_response_time'] > 5:
            insights.append("🐌 Slow responses - check system performance")
        
        if agent_data['today_interactions'] / max(1, agent_data['today_sessions']) > 3:
            insights.append("💬 Complex conversations - users need multiple interactions")
        
        if not insights:
            insights = [
                "✅ System running smoothly",
                "📈 Performance within normal ranges",
                "🎯 No immediate action required"
            ]
        
        for insight in insights:
            st.markdown(f"- {insight}")

    # Recent activity details
    st.subheader("🕐 Recent Activity Details")
    
    if agent_data['session_data']:
        recent_df = df.tail(10).copy()
        recent_df['completion_rate'] = recent_df['completion_rate'].astype(float)
        recent_df['completion_rate_pct'] = (recent_df['completion_rate'] * 100).round(1)
        
        # Format for display
        display_df = recent_df[['hour', 'session_count', 'interaction_count', 'completion_rate_pct']].copy()
        display_df.columns = ['Time', 'Sessions', 'Interactions', 'Success Rate (%)']
        
        st.dataframe(
            display_df.style.format({
                'Sessions': '{:,}',
                'Interactions': '{:,}',
                'Success Rate (%)': '{:.1f}%'
            }),
            use_container_width=True
        )

else:
    # No data available
    st.error("❌ Unable to fetch real-time agent data")
    
    st.markdown("""
    ### 🔧 Troubleshooting
    
    **Possible issues:**
    - API connection problem
    - No agent data ingested yet
    - Database connectivity issues
    
    **Quick fixes:**
    1. Check API status: `curl https://agentiq-api-z9it.onrender.com/health`
    2. Load sample data: Run data loading scripts
    3. Verify database: Check `/admin/database-status` endpoint
    """)

# Real-time testing section
st.sidebar.markdown("---")
st.sidebar.subheader("🧪 Real-Time Testing")

if st.sidebar.button("💉 Inject Test Data"):
    with st.spinner("Injecting test agent session..."):
        test_data = {
            "data": [{
                "user_input": f"Test query at {datetime.now().strftime('%H:%M:%S')}",
                "agent_response": f"Test response generated at {datetime.now().strftime('%H:%M:%S')}",
                "session_id": f"test-{int(time.time())}",
                "response_time_ms": 1200,
                "workflow_step": 1,
                "intent": "testing",
                "tool_calls": "[]"
            }]
        }
        
        try:
            response = requests.post(f"{API_BASE_URL}/ingest/json", json=test_data, timeout=10)
            if response.status_code == 200:
                st.sidebar.success("✅ Test data injected!")
                st.rerun()
            else:
                st.sidebar.error("❌ Failed to inject data")
        except Exception as e:
            st.sidebar.error(f"❌ Error: {e}")

# Footer with real-time status
st.markdown("---")
col1, col2, col3 = st.columns(3)

with col1:
    st.markdown(f"**🔄 Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

with col2:
    st.markdown(f"**🌐 API:** {API_BASE_URL}")

with col3:
    if auto_refresh:
        st.markdown(f"**⏰ Next refresh:** {refresh_interval}s")
    else:
        st.markdown("**⏸️ Auto-refresh:** Disabled")