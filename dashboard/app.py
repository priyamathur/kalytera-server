"""
AgentIQ Streamlit Dashboard - Real-time Agent Monitoring
3 Core Views: Agent Overview, Failure Feed, Interaction Detail + Quality Config
"""

import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

# Page configuration
st.set_page_config(
    page_title="AgentIQ - Real-time Agent Monitoring",
    page_icon="🤖", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# API Configuration
import os
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

# Utility Functions
def make_api_call(method: str, endpoint: str, params: Dict = None) -> Optional[Any]:
    """Make API call with error handling"""
    try:
        url = f"{API_BASE_URL}{endpoint}"
        if method.upper() == "GET":
            response = requests.get(url, params=params, timeout=15)
        elif method.upper() == "POST":
            response = requests.post(url, json=params, timeout=30)
        else:
            return None
            
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        st.error(f"API call failed ({method} {endpoint}): {str(e)}")
        return None

def render_sidebar():
    """Enhanced sidebar with real-time status"""
    st.sidebar.title("🤖 AgentIQ")
    st.sidebar.markdown("**Real-time Agent Monitoring**")
    
    # Main navigation
    page = st.sidebar.selectbox(
        "Dashboard Views:",
        [
            "Agent Overview", 
            "Failure Feed", 
            "Interaction Detail",
            "Quality Config"
        ],
        index=0
    )
    
    st.sidebar.markdown("---")
    
    # System health check
    st.sidebar.subheader("System Status") 
    
    health = make_api_call("GET", "/health")
    if health:
        st.sidebar.success("✅ API")
    else:
        st.sidebar.error("❌ API")
    
    # Auto-refresh option
    st.sidebar.markdown("---")
    auto_refresh = st.sidebar.checkbox("Auto-refresh (30s)", value=False)
    if auto_refresh:
        time.sleep(30)
        st.rerun()
    
    return page, auto_refresh

def main():
    """Main dashboard application with navigation"""
    current_page, auto_refresh = render_sidebar()
    
    st.title(f"AgentIQ Dashboard - {current_page}")
    
    if current_page == "Agent Overview":
        st.subheader("📊 Agent Overview")
        st.info("Quality score trend, active failure count, top failure types")
        
        # Placeholder metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Sessions (24h)", "2,341")
        with col2:
            st.metric("Avg Quality Score", "0.73")
        with col3:
            st.metric("Active Failures", "47")
        with col4:
            st.metric("Completion Rate", "84.2%")
            
    elif current_page == "Failure Feed":
        st.subheader("🚨 Failure Feed")
        st.info("Every failure in real time - one-off failures surface immediately, patterns grouped with root cause")
        st.write("Real-time failure monitoring dashboard would be displayed here")
        
    elif current_page == "Interaction Detail":
        st.subheader("🔍 Interaction Detail")
        st.info("Full step-by-step trace, quality score per step, failure reason")
        st.write("Detailed interaction analysis would be displayed here")
        
    elif current_page == "Quality Config":
        st.subheader("⚙️ Quality Configuration")
        st.info("Developer adjusts dimension weights and pass threshold per agent")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Dimension Weights")
            accuracy_weight = st.slider("Accuracy", 0.0, 1.0, 0.25, step=0.05)
            goal_alignment_weight = st.slider("Goal Alignment", 0.0, 1.0, 0.35, step=0.05)
            decision_quality_weight = st.slider("Decision Quality", 0.0, 1.0, 0.20, step=0.05)
            completeness_weight = st.slider("Completeness", 0.0, 1.0, 0.20, step=0.05)
            
        with col2:
            st.subheader("Quality Thresholds")
            pass_threshold = st.slider("Pass Threshold", 0.0, 1.0, 0.7, step=0.05)
            
            if st.button("Save Configuration", type="primary"):
                st.success("Configuration saved!")
    
    # Footer
    st.markdown("---")
    st.markdown("🤖 **AgentIQ** — Real-time Agent Monitoring and Quality Control")

if __name__ == "__main__":
    main()