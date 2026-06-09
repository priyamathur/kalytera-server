"""
AgentIQ Working Dashboard - Simplified version that actually displays data
"""

import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

st.set_page_config(page_title="AgentIQ - Working Dashboard", page_icon="🚀", layout="wide")

API_BASE_URL = "https://agentiq-api-z9it.onrender.com"

def get_data(endpoint):
    """Fetch data from API with error handling"""
    try:
        response = requests.get(f"{API_BASE_URL}{endpoint}", timeout=15)
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"API Error {response.status_code}: {response.text[:200]}")
            return None
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
        return None

# Header
st.markdown("# 🚀 AgentIQ - Working Dashboard")
st.markdown("**Live Agent Performance Monitoring**")

# Debug section to show what we're getting
with st.expander("🔍 Debug Info - API Responses"):
    st.write("**API Base URL:**", API_BASE_URL)
    
    # Test each endpoint
    health_data = get_data("/health")
    st.write("**Health Data:**", health_data)
    
    session_data = get_data("/analytics/session-volume")
    st.write("**Session Volume Data:**", session_data)
    
    db_data = get_data("/admin/database-status")
    st.write("**Database Status:**", db_data)

st.markdown("---")

# System Status
st.subheader("🔌 System Status")
col1, col2, col3 = st.columns(3)

with col1:
    health = get_data("/health")
    if health:
        st.success(f"✅ API Online - {health['status']}")
    else:
        st.error("❌ API Offline")

with col2:
    db_status = get_data("/admin/database-status")
    if db_status and db_status.get("tables_ready"):
        tables = len(db_status.get("existing_tables", []))
        st.success(f"✅ Database Ready - {tables} tables")
    else:
        st.error("❌ Database Issues")

with col3:
    st.info(f"🕐 Last Check: {datetime.now().strftime('%H:%M:%S')}")

# Get session data and display it
st.subheader("📊 Session Analytics")

session_data = get_data("/analytics/session-volume")

if session_data:
    st.success(f"✅ Found {len(session_data)} data points")
    
    # Convert to DataFrame
    df = pd.DataFrame(session_data)
    
    # Calculate totals
    total_sessions = df['session_count'].sum()
    total_interactions = df['interaction_count'].sum()
    
    # Display key metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("🎯 Total Sessions", f"{total_sessions:,}")
    
    with col2:
        st.metric("💬 Total Interactions", f"{total_interactions:,}")
    
    with col3:
        if total_sessions > 0:
            interactions_per_session = total_interactions / total_sessions
            st.metric("📊 Interactions/Session", f"{interactions_per_session:.1f}")
        else:
            st.metric("📊 Interactions/Session", "0")
    
    with col4:
        # Get today's data
        today_data = df[df['timestamp'].str.contains('2026-05-17')]
        today_interactions = today_data['interaction_count'].sum() if len(today_data) > 0 else 0
        st.metric("📈 Today's Activity", f"{today_interactions:,}")
    
    # Show the raw data table
    st.subheader("📋 Session Data Table")
    
    # Format for display
    display_df = df.copy()
    display_df['completion_rate'] = pd.to_numeric(display_df['completion_rate'], errors='coerce').fillna(0)
    display_df['completion_rate_pct'] = (display_df['completion_rate'] * 100).round(1)
    
    # Rename columns for better display
    display_cols = {
        'timestamp': 'Time',
        'session_count': 'Sessions',
        'interaction_count': 'Interactions', 
        'completion_rate_pct': 'Success Rate (%)',
        'avg_duration_seconds': 'Avg Duration (s)'
    }
    
    display_df = display_df.rename(columns=display_cols)
    st.dataframe(display_df[list(display_cols.values())], use_container_width=True)
    
    # Create activity chart
    st.subheader("📈 Activity Timeline")
    
    # Prepare data for chart
    chart_df = df.copy()
    chart_df['timestamp'] = pd.to_datetime(chart_df['timestamp'])
    chart_df['hour'] = chart_df['timestamp'].dt.strftime('%m/%d %H:00')
    
    # Create the chart
    fig = go.Figure()
    
    # Add sessions as bars
    fig.add_trace(go.Bar(
        x=chart_df['hour'],
        y=chart_df['session_count'],
        name='Sessions',
        marker_color='lightblue'
    ))
    
    # Add interactions as line
    fig.add_trace(go.Scatter(
        x=chart_df['hour'],
        y=chart_df['interaction_count'],
        mode='lines+markers',
        name='Interactions',
        line=dict(color='red', width=3),
        yaxis='y2'
    ))
    
    # Update layout
    fig.update_layout(
        title='Agent Activity Over Time',
        xaxis_title='Time',
        yaxis=dict(title='Sessions', side='left'),
        yaxis2=dict(title='Interactions', side='right', overlaying='y'),
        height=400
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Performance insights
    st.subheader("🎯 Performance Insights")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Activity level
        if today_interactions > 100:
            st.info("🔥 **High Activity Day** - Over 100 interactions today")
        elif today_interactions > 50:
            st.info("📈 **Moderate Activity** - Good interaction volume")
        elif today_interactions > 10:
            st.info("📊 **Low Activity** - Light usage today")
        else:
            st.warning("💤 **Very Low Activity** - Minimal usage detected")
    
    with col2:
        # Completion rate analysis
        avg_completion = display_df['Success Rate (%)'].mean()
        if avg_completion > 70:
            st.success(f"✅ **Good Performance** - {avg_completion:.1f}% average success rate")
        elif avg_completion > 30:
            st.warning(f"⚠️ **Moderate Performance** - {avg_completion:.1f}% average success rate")
        else:
            st.error(f"❌ **Poor Performance** - {avg_completion:.1f}% average success rate")

else:
    st.error("❌ No session data available")
    
    # Troubleshooting section
    st.subheader("🔧 Troubleshooting")
    st.write("**Possible issues:**")
    st.write("- API connection problem")
    st.write("- No agent data ingested yet") 
    st.write("- Database connectivity issues")
    
    if st.button("🧪 Send Test Data"):
        try:
            test_data = {
                "data": [{
                    "user_input": f"Test at {datetime.now().strftime('%H:%M:%S')}",
                    "agent_response": "Test response",
                    "session_id": f"test-{int(datetime.now().timestamp())}",
                    "response_time_ms": 1000,
                    "workflow_step": 1,
                    "intent": "testing",
                    "tool_calls": "[]"
                }]
            }
            
            response = requests.post(f"{API_BASE_URL}/ingest/json", json=test_data, timeout=10)
            if response.status_code == 200:
                st.success("✅ Test data sent! Refresh page in 30 seconds to see updates.")
            else:
                st.error(f"❌ Failed to send test data: {response.status_code}")
        except Exception as e:
            st.error(f"❌ Error sending test data: {e}")

# Footer
st.markdown("---")
st.markdown(f"**AgentIQ Dashboard** | {API_BASE_URL} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# Auto-refresh
st.sidebar.subheader("🔄 Auto-Refresh")
if st.sidebar.button("🔄 Refresh Now"):
    st.rerun()
    
refresh_interval = st.sidebar.selectbox(
    "Refresh Interval", 
    [10, 30, 60, 120], 
    index=1,
    help="Seconds between auto-refresh"
)

if st.sidebar.checkbox("Enable Auto-refresh", value=False):
    st.sidebar.write(f"⏰ Refreshing every {refresh_interval} seconds")
    # Note: In production, you'd implement proper auto-refresh
    st.sidebar.write("📝 Manual refresh for now - click 'Refresh Now' to update")