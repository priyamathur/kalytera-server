"""
AgentIQ Dashboard - The Real Vision
Shows developers exactly how their agents are performing and what to fix

Core Focus:
1. Usage Analytics - Intent classification, workflow paths, drop-off analysis  
2. Loss Pattern Analysis - Automated failure detection, root cause analysis
3. Autonomous LLM Evaluation - Continuous accuracy scoring
4. Developer Insights - Structured data for RL improvement loops
5. Business Impact - Causal proof of improvements
"""

import streamlit as st
import requests
import pandas as pd
import plotly.express as px
from datetime import datetime

st.set_page_config(page_title="AgentIQ - Agent Performance Intelligence", page_icon="🧠", layout="wide")

API_BASE_URL = "https://agentiq-api-z9it.onrender.com"

def get_data(endpoint):
    """Fetch data from AgentIQ API"""
    try:
        response = requests.get(f"{API_BASE_URL}{endpoint}", timeout=15)
        return response.json() if response.status_code == 200 else None
    except:
        return None

# Header with AgentIQ branding
st.markdown("""
<div style="background: linear-gradient(135deg, #0a0d10 0%, #1a1d20 100%); padding: 2rem; border-radius: 12px; margin-bottom: 2rem; border: 1px solid rgba(0,200,232,0.2);">
    <h1 style="color: #00c8e8; font-size: 2.5rem; margin: 0; font-weight: 800;">🧠 AgentIQ</h1>
    <p style="color: rgba(232,236,240,0.8); font-size: 1.2rem; margin: 0.5rem 0 0 0;">
        <strong>Agent Performance Intelligence</strong> — Understand usage patterns, find loss patterns, prove business impact
    </p>
</div>
""", unsafe_allow_html=True)

# Quick health check
health = get_data("/health")
if not health:
    st.error("🔴 **AgentIQ API Offline** - Cannot fetch agent performance data")
    st.stop()

# Get core analytics data
intent_data = get_data("/analytics/intent-performance") or []
quality_data = get_data("/analytics/quality-by-intent") or []
dropoff_data = get_data("/analytics/dropoff-analysis") or []
session_data = get_data("/analytics/session-volume") or []

# Main Dashboard
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("🎯 Agent Performance Overview")
    
    if intent_data:
        # Performance by Intent
        df_intent = pd.DataFrame(intent_data)
        
        # Performance chart
        fig = px.bar(
            df_intent, 
            x='intent', 
            y='completion_rate',
            title="Agent Success Rate by Intent",
            labels={'completion_rate': 'Success Rate', 'intent': 'User Intent'},
            color='completion_rate',
            color_continuous_scale=['#e85555', '#ffcc00', '#a8e060'],
            text='completion_rate'
        )
        fig.update_traces(texttemplate='%{text:.1%}', textposition='outside')
        fig.update_layout(
            xaxis_tickangle=-45,
            yaxis_tickformat=',.1%',
            height=400,
            showlegend=False
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # Key metrics
        total_sessions = sum(i['session_count'] for i in intent_data)
        avg_success_rate = sum(i['completion_rate'] for i in intent_data) / len(intent_data)
        
        metrics_col1, metrics_col2, metrics_col3 = st.columns(3)
        with metrics_col1:
            st.metric("📊 Total Sessions", f"{total_sessions:,}")
        with metrics_col2:
            st.metric("✅ Overall Success Rate", f"{avg_success_rate:.1%}")
        with metrics_col3:
            failing_intents = len([i for i in intent_data if i['completion_rate'] < 0.7])
            st.metric("⚠️ Intents Needing Help", f"{failing_intents}")
    else:
        st.warning("No intent performance data available")

with col2:
    st.subheader("🔍 Loss Pattern Analysis")
    
    if quality_data:
        st.markdown("**📈 Quality Scores by Intent**")
        for quality in quality_data:
            intent = quality['intent']
            score = quality['avg_quality_score']
            sample_size = quality['sample_size']
            
            # Color based on quality
            if score > 0.8:
                color = "🟢"
                status = "Excellent"
            elif score > 0.6:
                color = "🟡" 
                status = "Good"
            else:
                color = "🔴"
                status = "Needs Improvement"
                
            st.markdown(f"""
            **{color} {intent.replace('_', ' ').title()}**  
            Quality Score: {score:.2f} ({status})  
            Sample Size: {sample_size} evaluations  
            Confidence: {quality['confidence_level']}
            """)
            
            if quality['top_failure_patterns']:
                st.markdown("**Common Failures:**")
                for pattern in quality['top_failure_patterns'][:3]:
                    st.markdown(f"• {pattern}")
    
    if dropoff_data:
        st.markdown("**📉 Drop-off Points**")
        for dropoff in dropoff_data:
            if dropoff['priority_level'] != 'Low':
                st.markdown(f"""
                **Step {dropoff['step']}**: {dropoff['dropoff_rate']:.1%} drop-off  
                Impact: {dropoff['priority_level']} Priority  
                Sessions Lost: {dropoff['dropoff_count']}
                """)

# Loss Pattern Deep Dive
st.markdown("---")
st.subheader("🔍 Loss Pattern Deep Dive")

if dropoff_data:
    col1, col2 = st.columns(2)
    
    with col1:
        # Drop-off analysis chart
        df_dropoff = pd.DataFrame(dropoff_data)
        
        fig = px.bar(
            df_dropoff,
            x='step',
            y='dropoff_rate', 
            title="Drop-off Rate by Workflow Step",
            labels={'dropoff_rate': 'Drop-off Rate', 'step': 'Workflow Step'},
            color='impact_score',
            color_continuous_scale=['#a8e060', '#ffcc00', '#e85555']
        )
        fig.update_traces(texttemplate='%{y:.1%}', textposition='outside')
        fig.update_layout(yaxis_tickformat=',.1%')
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.markdown("**🚨 Critical Loss Patterns**")
        
        high_impact_dropoffs = [d for d in dropoff_data if d['priority_level'] in ['High', 'Critical']]
        if high_impact_dropoffs:
            for dropoff in high_impact_dropoffs:
                st.error(f"""
                **Step {dropoff['step']} - {dropoff['priority_level']} Priority**  
                {dropoff['dropoff_count']} sessions lost ({dropoff['dropoff_rate']:.1%})  
                Impact Score: {dropoff['impact_score']:.2f}
                """)
                
                if dropoff['recommended_actions']:
                    st.markdown("**Recommended Actions:**")
                    for action in dropoff['recommended_actions']:
                        st.markdown(f"• {action}")
        else:
            st.success("✅ No critical loss patterns detected")

# Developer Action Items
st.markdown("---")
st.subheader("🛠️ Developer Action Items")

if quality_data or dropoff_data:
    # Generate actionable insights
    action_items = []
    
    # From quality analysis
    for quality in quality_data:
        if quality['avg_quality_score'] < 0.7:
            action_items.append({
                'priority': 'High' if quality['avg_quality_score'] < 0.5 else 'Medium',
                'category': 'Quality',
                'intent': quality['intent'],
                'issue': f"Low quality score ({quality['avg_quality_score']:.2f})",
                'action': f"Review and improve {quality['intent']} responses",
                'impact': f"Could improve {quality['sample_size']} interactions"
            })
    
    # From dropoff analysis  
    for dropoff in dropoff_data:
        if dropoff['priority_level'] in ['High', 'Critical']:
            action_items.append({
                'priority': dropoff['priority_level'],
                'category': 'Drop-off',
                'intent': 'Multi-intent',
                'issue': f"{dropoff['dropoff_rate']:.1%} drop-off at step {dropoff['step']}",
                'action': dropoff['recommended_actions'][0] if dropoff['recommended_actions'] else "Investigate workflow step",
                'impact': f"Could recover {dropoff['dropoff_count']} sessions"
            })
    
    if action_items:
        # Sort by priority
        priority_order = {'Critical': 0, 'High': 1, 'Medium': 2, 'Low': 3}
        action_items.sort(key=lambda x: priority_order.get(x['priority'], 4))
        
        # Display as cards
        for item in action_items[:6]:  # Show top 6 items
            priority_color = {
                'Critical': '#e85555',
                'High': '#ff6b35', 
                'Medium': '#ffcc00',
                'Low': '#4e5a68'
            }.get(item['priority'], '#4e5a68')
            
            st.markdown(f"""
            <div style="border-left: 4px solid {priority_color}; padding: 1rem; margin: 0.5rem 0; background: rgba(255,255,255,0.03); border-radius: 4px;">
                <strong style="color: {priority_color};">{item['priority']} Priority - {item['category']}</strong><br>
                <strong>Intent:</strong> {item['intent']}<br>
                <strong>Issue:</strong> {item['issue']}<br>
                <strong>Recommended Action:</strong> {item['action']}<br>
                <strong>Potential Impact:</strong> {item['impact']}
            </div>
            """, unsafe_allow_html=True)
    else:
        st.success("✅ No critical action items - your agent is performing well!")

# Evaluation Insights
st.markdown("---")
st.subheader("🧠 Autonomous Evaluation Insights") 

col1, col2 = st.columns(2)

with col1:
    if quality_data:
        st.markdown("**📊 Quality Score Distribution**")
        
        quality_scores = [q['avg_quality_score'] for q in quality_data]
        intents = [q['intent'] for q in quality_data]
        
        fig = px.box(
            y=quality_scores,
            title="Agent Response Quality Distribution",
            labels={'y': 'Quality Score'}
        )
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("**🎯 Evaluation Summary**")
    total_evaluations = sum(q['sample_size'] for q in quality_data)
    avg_quality = sum(q['avg_quality_score'] * q['sample_size'] for q in quality_data) / max(total_evaluations, 1)
    
    st.metric("Total Evaluations", f"{total_evaluations:,}")
    st.metric("Average Quality Score", f"{avg_quality:.2f}")
    
    # Quality grade
    if avg_quality > 0.9:
        grade = "A+"
        color = "#a8e060"
    elif avg_quality > 0.8:
        grade = "A"
        color = "#a8e060" 
    elif avg_quality > 0.7:
        grade = "B"
        color = "#ffcc00"
    elif avg_quality > 0.6:
        grade = "C"
        color = "#ff6b35"
    else:
        grade = "F"
        color = "#e85555"
    
    st.markdown(f'<h3 style="color: {color};">Overall Grade: {grade}</h3>', unsafe_allow_html=True)

with col2:
    st.markdown("**🚀 Improvement Recommendations**")
    
    # Generate specific recommendations
    recommendations = []
    
    if quality_data:
        low_quality_intents = [q for q in quality_data if q['avg_quality_score'] < 0.7]
        if low_quality_intents:
            worst_intent = min(low_quality_intents, key=lambda x: x['avg_quality_score'])
            recommendations.append(f"🔴 **Priority 1**: Improve {worst_intent['intent']} responses (quality: {worst_intent['avg_quality_score']:.2f})")
    
    if dropoff_data:
        high_dropoff = [d for d in dropoff_data if d['dropoff_rate'] > 0.1]
        if high_dropoff:
            worst_dropoff = max(high_dropoff, key=lambda x: x['dropoff_rate'])
            recommendations.append(f"⚠️ **Priority 2**: Fix step {worst_dropoff['step']} workflow ({worst_dropoff['dropoff_rate']:.1%} drop-off)")
    
    # Generic recommendations based on data
    if total_evaluations < 100:
        recommendations.append("📊 **Data Collection**: Need more evaluation data for reliable insights")
    
    if not recommendations:
        recommendations = [
            "✅ **Performing Well**: No critical issues detected",
            "📈 **Optimization**: Consider A/B testing response variations",
            "🔍 **Monitoring**: Continue monitoring for emerging patterns"
        ]
    
    for rec in recommendations[:5]:
        st.markdown(rec)

# Footer
st.markdown("---")
st.markdown(f"""
<div style="text-align: center; color: rgba(232,236,240,0.5); font-size: 0.9rem;">
    <strong>AgentIQ</strong> — Agent Performance Intelligence<br>
    Usage Analytics • Loss Pattern Analysis • Autonomous Evaluation • Developer Insights<br>
    Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | API: {API_BASE_URL}
</div>
""", unsafe_allow_html=True)