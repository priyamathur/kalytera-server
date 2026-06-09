"""
Enterprise AgentIQ Dashboard
Professional agent performance monitoring for enterprise AI deployments

Key Features:
- Clear agent identification and evaluation coverage
- Key metrics prominently displayed at the top
- Actionable developer insights with specific recommendations
- Enterprise-grade design and data presentation
"""

import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

st.set_page_config(
    page_title="AgentIQ Enterprise Dashboard", 
    page_icon="🏢", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

API_BASE_URL = "https://agentiq-api-z9it.onrender.com"

def get_data(endpoint):
    """Fetch data from AgentIQ API with enterprise error handling"""
    try:
        response = requests.get(f"{API_BASE_URL}{endpoint}", timeout=15)
        return response.json() if response.status_code == 200 else None
    except Exception:
        return None

def get_agent_summary():
    """Get comprehensive agent performance summary"""
    # Get all required data
    intent_data = get_data("/analytics/intent-performance") or []
    quality_data = get_data("/analytics/quality-by-intent") or []
    session_data = get_data("/analytics/session-volume") or []
    dropoff_data = get_data("/analytics/dropoff-analysis") or []
    
    # Calculate key metrics
    total_sessions = sum(i['session_count'] for i in intent_data) if intent_data else 0
    total_interactions = sum(s['interaction_count'] for s in session_data) if session_data else 0
    total_evaluations = sum(q['sample_size'] for q in quality_data) if quality_data else 0
    
    # Calculate weighted average quality
    weighted_quality = 0
    if quality_data and total_evaluations > 0:
        weighted_quality = sum(q['avg_quality_score'] * q['sample_size'] for q in quality_data) / total_evaluations
    
    # Calculate completion rate
    avg_completion_rate = sum(i['completion_rate'] for i in intent_data) / len(intent_data) if intent_data else 0
    
    # Identify agent types
    agent_types = list(set(i['intent'] for i in intent_data)) if intent_data else []
    
    return {
        'agent_types': agent_types,
        'total_sessions': total_sessions,
        'total_interactions': total_interactions,
        'total_evaluations': total_evaluations,
        'evaluation_coverage': (total_evaluations / total_interactions * 100) if total_interactions > 0 else 0,
        'weighted_quality': weighted_quality,
        'completion_rate': avg_completion_rate,
        'intent_data': intent_data,
        'quality_data': quality_data,
        'session_data': session_data,
        'dropoff_data': dropoff_data
    }

# Get comprehensive data
summary = get_agent_summary()

# Enterprise Header
st.markdown("""
<div style="background: linear-gradient(90deg, #1e3a8a 0%, #3730a3 50%, #1e40af 100%); 
            padding: 2.5rem; border-radius: 8px; margin-bottom: 2rem; 
            border-left: 6px solid #60a5fa;">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <div>
            <h1 style="color: white; font-size: 2.8rem; margin: 0; font-weight: 700;">
                🏢 AgentIQ Enterprise Dashboard
            </h1>
            <p style="color: #e0e7ff; font-size: 1.3rem; margin: 0.8rem 0 0 0; font-weight: 500;">
                Professional AI Agent Performance Intelligence & Loss Pattern Analysis
            </p>
        </div>
        <div style="text-align: right; color: #e0e7ff;">
            <div style="font-size: 0.9rem;">Last Updated</div>
            <div style="font-size: 1.1rem; font-weight: 600;">{}</div>
        </div>
    </div>
</div>
""".format(datetime.now().strftime('%Y-%m-%d %H:%M:%S')), unsafe_allow_html=True)

# Agent Identification Section
st.markdown("### 🤖 **Agent Portfolio Overview**")

if summary['agent_types']:
    # Display which agents are being evaluated
    col1, col2 = st.columns([3, 1])
    
    with col1:
        agent_display = ", ".join([agent.replace('_', ' ').title() for agent in summary['agent_types']])
        st.markdown(f"""
        <div style="background: #f8fafc; padding: 1.5rem; border-radius: 6px; border-left: 4px solid #3b82f6;">
            <h4 style="margin: 0; color: #1e40af;">Agents Under Evaluation:</h4>
            <p style="font-size: 1.1rem; margin: 0.5rem 0 0 0; color: #374151; font-weight: 600;">
                {agent_display}
            </p>
            <p style="font-size: 0.9rem; color: #6b7280; margin: 0.5rem 0 0 0;">
                Total: {len(summary['agent_types'])} agent types | {summary['total_sessions']:,} sessions monitored
            </p>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        # Evaluation coverage percentage
        coverage = summary['evaluation_coverage']
        coverage_color = "#10b981" if coverage > 80 else "#f59e0b" if coverage > 50 else "#ef4444"
        
        st.markdown(f"""
        <div style="background: white; padding: 1.5rem; border-radius: 6px; border: 2px solid {coverage_color}; text-align: center;">
            <h4 style="margin: 0; color: {coverage_color};">Evaluation Coverage</h4>
            <h2 style="margin: 0.5rem 0; color: {coverage_color}; font-size: 2.5rem;">{coverage:.1f}%</h2>
            <p style="margin: 0; color: #6b7280; font-size: 0.9rem;">
                {summary['total_evaluations']:,} of {summary['total_interactions']:,} interactions
            </p>
        </div>
        """, unsafe_allow_html=True)

else:
    st.error("❌ **No Agent Data Available** - No agents currently being monitored")
    st.stop()

# Key Metrics at the Top
st.markdown("### 📊 **Key Performance Metrics**")

# Top-level KPIs
kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)

with kpi_col1:
    quality_grade = "A+" if summary['weighted_quality'] > 0.9 else "A" if summary['weighted_quality'] > 0.8 else "B" if summary['weighted_quality'] > 0.7 else "C" if summary['weighted_quality'] > 0.6 else "F"
    quality_color = "#10b981" if summary['weighted_quality'] > 0.7 else "#f59e0b" if summary['weighted_quality'] > 0.5 else "#ef4444"
    
    st.markdown(f"""
    <div style="background: white; padding: 1.5rem; border-radius: 6px; border-top: 4px solid {quality_color}; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
        <h4 style="margin: 0; color: #374151;">Overall Quality Score</h4>
        <h2 style="margin: 0.5rem 0; color: {quality_color}; font-size: 2.2rem;">{summary['weighted_quality']:.2f}</h2>
        <p style="margin: 0; color: {quality_color}; font-weight: 600;">Grade: {quality_grade}</p>
    </div>
    """, unsafe_allow_html=True)

with kpi_col2:
    completion_color = "#10b981" if summary['completion_rate'] > 0.7 else "#f59e0b" if summary['completion_rate'] > 0.5 else "#ef4444"
    
    st.markdown(f"""
    <div style="background: white; padding: 1.5rem; border-radius: 6px; border-top: 4px solid {completion_color}; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
        <h4 style="margin: 0; color: #374151;">Success Rate</h4>
        <h2 style="margin: 0.5rem 0; color: {completion_color}; font-size: 2.2rem;">{summary['completion_rate']:.1%}</h2>
        <p style="margin: 0; color: #6b7280;">Task Completion</p>
    </div>
    """, unsafe_allow_html=True)

with kpi_col3:
    st.markdown(f"""
    <div style="background: white; padding: 1.5rem; border-radius: 6px; border-top: 4px solid #3b82f6; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
        <h4 style="margin: 0; color: #374151;">Total Sessions</h4>
        <h2 style="margin: 0.5rem 0; color: #3b82f6; font-size: 2.2rem;">{summary['total_sessions']:,}</h2>
        <p style="margin: 0; color: #6b7280;">Production Usage</p>
    </div>
    """, unsafe_allow_html=True)

with kpi_col4:
    interactions_per_session = summary['total_interactions'] / summary['total_sessions'] if summary['total_sessions'] > 0 else 0
    complexity_color = "#ef4444" if interactions_per_session > 3 else "#f59e0b" if interactions_per_session > 2 else "#10b981"
    
    st.markdown(f"""
    <div style="background: white; padding: 1.5rem; border-radius: 6px; border-top: 4px solid {complexity_color}; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
        <h4 style="margin: 0; color: #374151;">Avg Complexity</h4>
        <h2 style="margin: 0.5rem 0; color: {complexity_color}; font-size: 2.2rem;">{interactions_per_session:.1f}</h2>
        <p style="margin: 0; color: #6b7280;">Interactions/Session</p>
    </div>
    """, unsafe_allow_html=True)

# Performance Analysis
st.markdown("---")
st.markdown("### 📈 **Agent Performance Analysis**")

if summary['intent_data']:
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Performance by agent type
        df_intent = pd.DataFrame(summary['intent_data'])
        
        fig = go.Figure()
        
        # Add bars for completion rate
        fig.add_trace(go.Bar(
            x=df_intent['intent'].str.replace('_', ' ').str.title(),
            y=df_intent['completion_rate'] * 100,
            name='Success Rate (%)',
            marker_color=['#10b981' if x > 0.7 else '#f59e0b' if x > 0.5 else '#ef4444' for x in df_intent['completion_rate']],
            text=[f"{x:.1%}" for x in df_intent['completion_rate']],
            textposition='outside'
        ))
        
        fig.update_layout(
            title='<b>Agent Success Rates by Type</b>',
            xaxis_title='Agent Type',
            yaxis_title='Success Rate (%)',
            height=400,
            showlegend=False,
            title_font_size=16,
            yaxis_range=[0, 100]
        )
        
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.markdown("**🎯 Performance Summary**")
        
        # Identify best and worst performing agents
        best_agent = max(summary['intent_data'], key=lambda x: x['completion_rate'])
        worst_agent = min(summary['intent_data'], key=lambda x: x['completion_rate'])
        
        st.markdown(f"""
        **🏆 Top Performer:**  
        {best_agent['intent'].replace('_', ' ').title()}  
        Success Rate: {best_agent['completion_rate']:.1%}  
        Sessions: {best_agent['session_count']:,}
        
        **⚠️ Needs Attention:**  
        {worst_agent['intent'].replace('_', ' ').title()}  
        Success Rate: {worst_agent['completion_rate']:.1%}  
        Sessions: {worst_agent['session_count']:,}
        """)
        
        # Performance distribution
        high_performers = len([i for i in summary['intent_data'] if i['completion_rate'] > 0.7])
        total_agents = len(summary['intent_data'])
        
        st.metric("High-Performing Agents", f"{high_performers}/{total_agents}")

# Loss Pattern Analysis
st.markdown("---")
st.markdown("### 🔍 **Loss Pattern Analysis & Actionable Insights**")

if summary['quality_data']:
    # Critical issues requiring immediate attention
    critical_issues = []
    medium_issues = []
    
    for quality in summary['quality_data']:
        if quality['avg_quality_score'] < 0.6:
            critical_issues.append({
                'agent': quality['intent'].replace('_', ' ').title(),
                'score': quality['avg_quality_score'],
                'sample_size': quality['sample_size'],
                'severity': 'Critical'
            })
        elif quality['avg_quality_score'] < 0.75:
            medium_issues.append({
                'agent': quality['intent'].replace('_', ' ').title(),
                'score': quality['avg_quality_score'],
                'sample_size': quality['sample_size'],
                'severity': 'Medium'
            })
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.markdown("**🚨 Critical Issues (Immediate Action Required)**")
        
        if critical_issues:
            for issue in critical_issues:
                st.error(f"""
                **Agent:** {issue['agent']}  
                **Quality Score:** {issue['score']:.2f} (Critical)  
                **Sample Size:** {issue['sample_size']} evaluations  
                **Action:** Urgent review and improvement needed
                """)
        else:
            st.success("✅ No critical quality issues detected")
        
        if medium_issues:
            st.markdown("**⚠️ Medium Priority Issues**")
            for issue in medium_issues:
                st.warning(f"""
                **Agent:** {issue['agent']}  
                **Quality Score:** {issue['score']:.2f}  
                **Recommended:** Schedule improvement within 2 weeks
                """)
    
    with col2:
        st.markdown("**🛠️ Specific Developer Actions**")
        
        # Generate specific, actionable recommendations
        action_count = 1
        
        if critical_issues:
            for issue in critical_issues:
                st.markdown(f"""
                **Action {action_count}:** Immediately review {issue['agent']} responses
                - Priority: 🔴 Critical
                - Timeline: This week
                - Focus: Response quality and accuracy
                - Expected Impact: +{(0.75 - issue['score'])*100:.0f}% quality improvement
                """)
                action_count += 1
        
        # Identify dropoff patterns
        if summary['dropoff_data']:
            high_dropoff = [d for d in summary['dropoff_data'] if d['dropoff_rate'] > 0.1]
            if high_dropoff:
                worst_dropoff = max(high_dropoff, key=lambda x: x['dropoff_rate'])
                st.markdown(f"""
                **Action {action_count}:** Fix workflow step {worst_dropoff['step']}
                - Priority: 🟡 High
                - Issue: {worst_dropoff['dropoff_rate']:.1%} user abandonment
                - Timeline: Next sprint
                - Expected Impact: Recover {worst_dropoff['dropoff_count']} sessions/month
                """)
                action_count += 1
        
        if action_count == 1:
            st.success("""
            ✅ **All agents performing well!**
            
            **Optimization Opportunities:**
            - A/B test response variations
            - Monitor for emerging patterns
            - Continue quality monitoring
            """)

# Enterprise Footer with System Status
st.markdown("---")

# System health indicators
col1, col2, col3 = st.columns(3)

with col1:
    health = get_data("/health")
    status_icon = "🟢" if health else "🔴"
    st.markdown(f"**System Status:** {status_icon} {'Online' if health else 'Offline'}")

with col2:
    st.markdown(f"**Data Freshness:** 🕐 {datetime.now().strftime('%H:%M:%S')}")

with col3:
    st.markdown(f"**API Endpoint:** 🌐 {API_BASE_URL}")

st.markdown("""
<div style="text-align: center; color: #6b7280; font-size: 0.9rem; margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #e5e7eb;">
    <strong>AgentIQ Enterprise Dashboard</strong> — Professional AI Agent Performance Intelligence<br>
    Enterprise-Grade Monitoring • Loss Pattern Detection • Actionable Developer Insights • Real-Time Analytics
</div>
""", unsafe_allow_html=True)