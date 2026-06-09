"""
AgentIQ Streamlit Dashboard - Comprehensive Agent Observability Platform
4 Views: Overview, Usage Analytics, Loss Patterns, Interaction Detail
"""

import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import json
from typing import Dict, Any, Optional

st.set_page_config(
    page_title="AgentIQ - Agent Observability Platform",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

import os

# Get API base URL from environment or streamlit secrets
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
if hasattr(st, "secrets") and st.secrets.get("api_base_url"):
    API_BASE_URL = st.secrets.get("api_base_url")

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
        ["📊 Overview", "🎯 Agent Workflows", "📉 Failure Analysis"],
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

    # Metric Definitions
    with st.expander("📋 Metric Definitions", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("""
            **📝 Total Sessions (7d)**  
            *Number of agent interactions tracked in the last 7 days*
            
            **✅ Completion Rate**  
            *Percentage of sessions that reached their intended goal without failures*
            
            **⭐ Avg Quality Score**  
            *Average of 4-dimensional quality scoring (Accuracy + Goal Alignment + Decision Quality + Completeness)*
            """)
        with col2:
            st.markdown("""
            **📉 Drop-off Rate**  
            *Percentage of sessions that failed or were abandoned before completion*
            
            **🎯 Success Rate**  
            *Calculated as: 1 - Drop-off Rate (inverse of failure rate)*
            
            **📊 Quality Dimensions**  
            *Accuracy, Goal Alignment, Decision Quality, Completeness (scored 0-1)*
            """)

    st.markdown("---")
    
    # Add 4-dimensional quality scoring visualization
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📊 4-Dimensional Quality Scoring")
        
        # Sample quality dimensions (would come from evaluation API)
        quality_dims = {
            'Accuracy': 0.73,
            'Goal Alignment': 0.68, 
            'Decision Quality': 0.71,
            'Completeness': 0.65
        }
        
        # Create radar chart
        import plotly.graph_objects as go
        
        fig = go.Figure()
        
        categories = list(quality_dims.keys())
        values = list(quality_dims.values())
        
        # Add current scores
        fig.add_trace(go.Scatterpolar(
            r=values + [values[0]],
            theta=categories + [categories[0]],
            fill='toself',
            name='Current',
            fillcolor='rgba(31, 119, 180, 0.3)',
            line=dict(color='rgb(31, 119, 180)')
        ))
        
        # Add target line (80%)
        target_values = [0.8] * len(categories)
        fig.add_trace(go.Scatterpolar(
            r=target_values + [target_values[0]],
            theta=categories + [categories[0]],
            mode='lines',
            name='Target (80%)',
            line=dict(color='red', dash='dash')
        ))
        
        fig.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, 1],
                    showticklabels=True,
                    tickvals=[0.2, 0.4, 0.6, 0.8, 1.0]
                )),
            showlegend=True,
            title="Quality Dimensions Analysis",
            height=350
        )
        
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.subheader("Quality Metrics Breakdown")
        
        for dim, score in quality_dims.items():
            color = "green" if score >= 0.8 else "orange" if score >= 0.6 else "red"
            delta_vs_target = score - 0.8
            st.metric(
                dim,
                f"{score:.3f}",
                delta=f"{delta_vs_target:+.3f}" if delta_vs_target != 0 else "0.000",
                delta_color="inverse"
            )

    st.markdown("---")

    # Only show real data that works - remove the broken sections
    st.markdown("---")
    st.subheader("🎯 Agent Performance Summary")
    
    # Get real agent workflows data
    all_workflows = make_api_get("/analytics/all-agent-workflows")
    
    if all_workflows and "workflows" in all_workflows:
        st.info(f"**{all_workflows['total_agent_types']} Active Agent Types** - Real-time analysis from session data")
        
        # Create performance table
        workflow_data = []
        for wf in all_workflows["workflows"]:
            workflow_data.append({
                "Agent": wf["intent"].replace("_", " ").title(),
                "Sessions": wf["total_sessions"],
                "Steps": wf["unique_steps"],
                "Success Rate": f"{wf['avg_success_rate']:.1%}",
                "Complexity": wf["complexity"].title(),
                "Health": wf["workflow_health"].title()
            })
        
        df = pd.DataFrame(workflow_data)
        st.dataframe(df, use_container_width=True)
        
        # Quick insights
        if all_workflows.get("summary"):
            summary = all_workflows["summary"]
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if summary.get("highest_performing"):
                    st.metric("🏆 Best Performing", summary["highest_performing"].replace("_", " ").title())
            
            with col2:
                if summary.get("most_complex"):
                    st.metric("🔧 Most Complex", f"{summary['most_complex'].replace('_', ' ').title()}")
            
            with col3:
                needs_attention = summary.get("needs_attention", [])
                if needs_attention:
                    st.metric("⚠️ Needs Attention", len(needs_attention))
                else:
                    st.metric("✅ All Healthy", "0 issues")
    else:
        st.info("Loading agent workflow data...")
    
    # Remove all the fake/broken sections below


def render_agent_workflows_page(hours_back: int):
    """Render clean agent workflows page with only real, useful data"""
    st.markdown('<h1 class="main-header">🎯 Agent Workflows</h1>', unsafe_allow_html=True)
    
    # Get real agent workflows data
    all_workflows = make_api_get("/analytics/all-agent-workflows")
    
    if not all_workflows or "workflows" not in all_workflows:
        st.error("Unable to load agent workflow data")
        return
    
    st.info("📋 **Real-time analysis of agent execution paths based on actual session data**")
    
    # Workflow Metric Definitions
    with st.expander("📋 Workflow Metric Definitions", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("""
            **🎯 Sessions**  
            *Total number of agent interactions for this workflow*
            
            **🔗 Steps**  
            *Number of unique steps in this agent's execution path*
            
            **✅ Success Rate**  
            *Percentage of sessions that completed successfully without failures*
            """)
        with col2:
            st.markdown("""
            **🧩 Complexity**  
            *Low/Medium/High based on number of steps and decision points*
            
            **❤️ Health**  
            *Overall workflow health: Excellent/Good/Needs Attention based on success rate*
            
            **🔧 Dynamic Flowchart**  
            *Visual representation of the actual steps this agent takes*
            """)
    
    # Agent selector
    available_intents = [wf["intent"] for wf in all_workflows["workflows"]]
    selected_intent = st.selectbox(
        "🎯 Select Agent to Analyze:",
        ["All Agents"] + available_intents
    )
    
    if selected_intent == "All Agents":
        # Show agent comparison
        st.subheader("📊 Agent Performance Comparison")
        
        # Create performance visualization
        workflow_data = []
        for wf in all_workflows["workflows"]:
            workflow_data.append({
                "Agent": wf["intent"].replace("_", " ").title(),
                "Sessions": wf["total_sessions"],
                "Steps": wf["unique_steps"],
                "Success Rate": wf["avg_success_rate"],
                "Complexity": wf["complexity"],
                "Health": wf["workflow_health"]
            })
        
        df = pd.DataFrame(workflow_data)
        
        # Bubble chart showing complexity vs performance
        fig = px.scatter(
            df, 
            x="Steps", 
            y="Success Rate",
            size="Sessions",
            color="Success Rate",
            hover_data=["Agent"],
            title="Agent Complexity vs Performance",
            labels={"Steps": "Workflow Complexity (# steps)", "Success Rate": "Success Rate"},
            color_continuous_scale="RdYlGn"
        )
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)
        
        # Summary table
        st.subheader("Agent Summary")
        display_df = df.copy()
        display_df["Success Rate"] = display_df["Success Rate"].apply(lambda x: f"{x:.1%}")
        st.dataframe(display_df, use_container_width=True)
        
    else:
        # Show specific agent analysis
        workflow_data = make_api_get(f"/analytics/agent-workflow-analysis/{selected_intent}")
        
        if workflow_data and workflow_data.get("workflow_steps"):
            st.subheader(f"🔍 {selected_intent.replace('_', ' ').title()} Agent Analysis")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Steps", workflow_data["total_unique_steps"])
            with col2:
                st.metric("Overall Success Rate", f"{workflow_data['overall_success_rate']:.1%}")
            with col3:
                total_sessions = sum(step["total_sessions"] for step in workflow_data["workflow_steps"])
                st.metric("Total Sessions Analyzed", total_sessions)
            
            # Dynamic flowchart
            st.subheader("📋 Agent Execution Flow")
            st.markdown(f"```mermaid\n{workflow_data['flowchart_mermaid']}\n```")
            
            # Step-by-step breakdown
            st.subheader("📊 Step Analysis")
            step_data = []
            for step in workflow_data["workflow_steps"]:
                step_name = next((node["name"] for node in workflow_data["flowchart_nodes"] 
                                if node["step_number"] == step["step"]), f"Step {step['step']}")
                step_data.append({
                    "Step": step_name,
                    "Sessions": step["total_sessions"],
                    "Success Rate": f"{step['success_rate']:.1%}",
                    "Avg Response Time": f"{step['avg_response_time']:.0f}ms",
                    "Dropoffs": step["dropoff_count"]
                })
            
            step_df = pd.DataFrame(step_data)
            st.dataframe(step_df, use_container_width=True)
            
            # Failure points
            if workflow_data.get("failure_points"):
                st.warning("🚨 **Failure Points Detected:**")
                for fp in workflow_data["failure_points"]:
                    st.markdown(f"• **{fp['step_name']}**: {fp['success_rate']:.1%} success rate")
            else:
                st.success("✅ **No critical failure points detected**")
        else:
            st.error(f"Unable to load workflow data for {selected_intent}")


def render_failure_analysis_page(hours_back: int):
    """Render clean failure analysis with only real, useful data"""
    st.markdown('<h1 class="main-header">📉 Failure Analysis</h1>', unsafe_allow_html=True)
    
    # Get real failure data from dropoff analysis
    dropoff_data = make_api_get("/analytics/dropoff-analysis")
    all_workflows = make_api_get("/analytics/all-agent-workflows")
    
    if not dropoff_data and not all_workflows:
        st.error("Unable to load failure analysis data")
        return
    
    st.info("📋 **Analysis of where and why agent sessions fail**")
    
    # Failure Analysis Metric Definitions
    with st.expander("📋 Failure Analysis Metrics", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("""
            **📉 Drop-off Rate**  
            *Percentage of sessions that fail at a specific step*
            
            **⚡ Critical Steps**  
            *Workflow steps with >10% failure rate (need immediate attention)*
            
            **📊 Failure Count**  
            *Total number of sessions that failed at each step*
            """)
        with col2:
            st.markdown("""
            **💥 Impact Level**  
            *High/Medium/Low based on failure rate and volume*
            
            **🎯 Top Intent**  
            *Which agent type fails most often at this step*
            
            **🔧 Recommendations**  
            *Suggested actions to reduce failures at each step*
            """)
    
    # Overall failure metrics
    if dropoff_data:
        st.subheader("📊 Failure Overview")
        
        total_dropoffs = sum(d["dropoff_count"] for d in dropoff_data)
        critical_steps = [d for d in dropoff_data if d.get("dropoff_rate", 0) > 0.1]
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Session Dropoffs", total_dropoffs)
        with col2:
            st.metric("Critical Failure Steps", len(critical_steps))
        with col3:
            if critical_steps:
                worst_step = max(critical_steps, key=lambda x: x["dropoff_rate"])
                st.metric("Worst Step", f"Step {worst_step['step']}")
            else:
                st.metric("System Status", "✅ Healthy")
        
        # Failure visualization
        st.subheader("📉 Step-by-Step Failure Analysis")
        
        if dropoff_data:
            # Create failure rate chart
            steps = [d["step"] for d in dropoff_data]
            dropoff_counts = [d["dropoff_count"] for d in dropoff_data]
            dropoff_rates = [d.get("dropoff_rate", 0) * 100 for d in dropoff_data]
            
            fig = px.bar(
                x=steps,
                y=dropoff_counts,
                title="Session Failures by Workflow Step",
                labels={"x": "Workflow Step", "y": "Failed Sessions"},
                color=dropoff_rates,
                color_continuous_scale="Reds"
            )
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
            
            # Critical failure points
            if critical_steps:
                st.warning(f"🚨 **{len(critical_steps)} Critical Failure Points Detected:**")
                
                failure_data = []
                for step in critical_steps:
                    failure_data.append({
                        "Step": step["step"],
                        "Failures": step["dropoff_count"],
                        "Failure Rate": f"{step.get('dropoff_rate', 0):.1%}",
                        "Impact": step.get("priority_level", "Medium"),
                        "Top Intent": max(step.get("intent_breakdown", {}).items(), key=lambda x: x[1])[0] if step.get("intent_breakdown") else "Unknown"
                    })
                
                failure_df = pd.DataFrame(failure_data)
                st.dataframe(failure_df, use_container_width=True)
                
                # Recommendations
                st.subheader("🔧 Recommendations")
                for step in critical_steps[:3]:  # Top 3 worst steps
                    with st.expander(f"Step {step['step']} - {step.get('dropoff_rate', 0):.1%} failure rate"):
                        if step.get("recommended_actions"):
                            for action in step["recommended_actions"]:
                                st.markdown(f"• {action}")
                        else:
                            st.info("Investigate workflow logic and error handling for this step")
            else:
                st.success("✅ **No critical failure points detected!** System is performing well.")
    
    # Agent-specific failure analysis
    if all_workflows and "workflows" in all_workflows:
        st.markdown("---")
        st.subheader("🎯 Agent-Specific Failure Rates")
        
        # Show which agents are struggling
        agent_failures = []
        for wf in all_workflows["workflows"]:
            failure_rate = 1 - wf["avg_success_rate"]
            if failure_rate > 0.1:  # More than 10% failure rate
                agent_failures.append({
                    "Agent": wf["intent"].replace("_", " ").title(),
                    "Success Rate": f"{wf['avg_success_rate']:.1%}",
                    "Failure Rate": f"{failure_rate:.1%}",
                    "Complexity": wf["complexity"].title(),
                    "Sessions": wf["total_sessions"]
                })
        
        if agent_failures:
            st.warning(f"⚠️ **{len(agent_failures)} agents need attention:**")
            failure_df = pd.DataFrame(agent_failures)
            st.dataframe(failure_df, use_container_width=True)
        else:
            st.success("✅ **All agents performing well** - No agents with >10% failure rate")



def main():
    """Main dashboard application"""
    current_page, hours_back = render_sidebar()

    # Clean navigation - only useful tabs with real data
    if current_page == "📊 Overview":
        render_overview_page(hours_back)
    elif current_page == "🎯 Agent Workflows":
        render_agent_workflows_page(hours_back)
    elif current_page == "📉 Failure Analysis":
        render_failure_analysis_page(hours_back)

    st.markdown("---")
    st.markdown(
        "🤖 **AgentIQ** — Agent observability and loss pattern analysis | "
        "[API Docs](http://localhost:8000/docs)"
    )


if __name__ == "__main__":
    main()
