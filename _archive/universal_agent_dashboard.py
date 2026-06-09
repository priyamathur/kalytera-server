"""
AgentIQ Universal Agent Performance Dashboard
Works with all agent types: coding, customer service, data science, BDR, marketing, etc.
Shows clear, interpretable metrics that matter for any AI agent deployment
"""

import streamlit as st
import requests
import pandas as pd
import plotly.express as px
from datetime import datetime

st.set_page_config(page_title="AgentIQ - Universal Agent Analytics", page_icon="🤖", layout="wide")

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

def get_agent_type_context(intent_data):
    """Determine the primary agent type based on intents"""
    if not intent_data:
        return "general", {}
    
    intent_counts = {item["intent"]: item["session_count"] for item in intent_data}
    
    # Agent type classification
    coding_intents = ["code_generation", "debugging", "code_review", "api_development", "test_generation", "git_help"]
    customer_service_intents = ["billing", "refunds", "account_recovery", "technical_support", "complaints", "general_inquiry"]
    data_science_intents = ["data_analysis", "model_training", "data_cleaning", "visualization", "statistical_analysis"]
    sales_bdr_intents = ["lead_qualification", "prospecting", "meeting_scheduling", "follow_up", "objection_handling"]
    marketing_intents = ["content_creation", "campaign_analysis", "audience_research", "seo_optimization", "social_media"]
    
    type_scores = {
        "coding": sum(intent_counts.get(intent, 0) for intent in coding_intents),
        "customer_service": sum(intent_counts.get(intent, 0) for intent in customer_service_intents),
        "data_science": sum(intent_counts.get(intent, 0) for intent in data_science_intents),
        "sales_bdr": sum(intent_counts.get(intent, 0) for intent in sales_bdr_intents),
        "marketing": sum(intent_counts.get(intent, 0) for intent in marketing_intents)
    }
    
    primary_type = max(type_scores, key=type_scores.get)
    if type_scores[primary_type] == 0:
        primary_type = "general"
    
    # Intent explanations for any agent type
    universal_explanations = {
        # Coding
        "code_generation": "Writing new code, functions, algorithms",
        "debugging": "Finding and fixing bugs, error analysis", 
        "code_review": "Code quality assessment, optimization",
        "api_development": "REST/GraphQL API creation, endpoints",
        "test_generation": "Writing unit tests, test automation",
        "git_help": "Version control, merge conflicts, branching",
        
        # Customer Service
        "billing": "Payment issues, invoice questions, charges",
        "refunds": "Refund requests, cancellation processing",
        "account_recovery": "Password resets, account access issues",
        "technical_support": "Product troubleshooting, technical help",
        "complaints": "Service issues, complaint resolution",
        "general_inquiry": "General questions, information requests",
        
        # Data Science
        "data_analysis": "Statistical analysis, data insights",
        "model_training": "ML model development and training",
        "data_cleaning": "Data preprocessing, quality checks",
        "visualization": "Charts, graphs, data presentation",
        "statistical_analysis": "Hypothesis testing, statistical models",
        
        # Sales/BDR
        "lead_qualification": "Qualifying prospects, lead scoring",
        "prospecting": "Finding new leads, research",
        "meeting_scheduling": "Booking calls, calendar management",
        "follow_up": "Following up with prospects, nurturing",
        "objection_handling": "Addressing concerns, overcoming objections",
        
        # Marketing
        "content_creation": "Writing copy, creating content",
        "campaign_analysis": "Measuring campaign performance",
        "audience_research": "Target audience analysis",
        "seo_optimization": "Search optimization, keyword research",
        "social_media": "Social media management, posting"
    }
    
    return primary_type, universal_explanations

# Header
st.markdown("# 🤖 AgentIQ - Universal Agent Analytics")
st.markdown("**Monitor any AI agent's performance: coding, customer service, data science, sales, marketing, and more**")

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

# Get core analytics data
session_data = get_data("/analytics/session-volume")
intent_data = get_data("/analytics/intent-performance")
quality_data = get_data("/analytics/quality-by-intent")

if session_data and intent_data:
    # Determine agent type and get context
    agent_type, intent_explanations = get_agent_type_context(intent_data)
    
    # Agent type indicator
    type_emojis = {
        "coding": "👨‍💻",
        "customer_service": "🎧", 
        "data_science": "📊",
        "sales_bdr": "📞",
        "marketing": "📈",
        "general": "🤖"
    }
    
    type_names = {
        "coding": "Coding Assistant",
        "customer_service": "Customer Service",
        "data_science": "Data Science", 
        "sales_bdr": "Sales & BDR",
        "marketing": "Marketing",
        "general": "General Purpose"
    }
    
    st.info(f"{type_emojis[agent_type]} **Detected Agent Type**: {type_names[agent_type]}")
    
    # Calculate key metrics
    total_sessions = sum(point["session_count"] for point in session_data)
    total_interactions = sum(point["interaction_count"] for point in session_data)
    avg_success_rate = sum(i["completion_rate"] for i in intent_data) / len(intent_data) if intent_data else 0
    
    # Key Metrics Overview  
    st.subheader("📊 Performance Overview")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("🎯 Total Sessions", f"{total_sessions:,}")
    with col2: 
        st.metric("💬 Total Interactions", f"{total_interactions:,}")
    with col3:
        st.metric("✅ Average Success Rate", f"{avg_success_rate:.1%}")
    with col4:
        st.metric("🎭 Task Types Handled", f"{len(intent_data)}")

    # Task Performance Analysis
    st.markdown("---")
    st.subheader("🎯 Performance by Task Type")
    
    df_intent = pd.DataFrame(intent_data)
    
    # Add explanations to the dataframe
    df_intent['task_description'] = df_intent['intent'].map(intent_explanations).fillna("Other tasks")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Performance chart
        fig = px.bar(df_intent, 
                    x='completion_rate', 
                    y='intent',
                    orientation='h',
                    title="Task Success Rates",
                    labels={'completion_rate': 'Success Rate (%)', 'intent': 'Task Type'},
                    color='completion_rate',
                    color_continuous_scale='RdYlGn')
        
        # Format as percentages
        fig.update_traces(texttemplate='%{x:.1%}', textposition='outside')
        fig.update_layout(xaxis_tickformat=',.1%')
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.markdown("### 📈 Performance Guide")
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

    # Session Volume and Quality Analysis
    st.markdown("---")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📈 Activity Over Time")
        if session_data:
            df_volume = pd.DataFrame(session_data)
            df_volume['timestamp'] = pd.to_datetime(df_volume['timestamp'])
            df_volume['date'] = df_volume['timestamp'].dt.date
            
            daily_volume = df_volume.groupby('date').agg({
                'session_count': 'sum',
                'interaction_count': 'sum'
            }).reset_index()
            
            fig = px.line(daily_volume, x='date', y='session_count',
                         title="Daily Agent Sessions",
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

    # Quality Analysis (if available)
    if quality_data:
        st.markdown("---")
        st.subheader("🏆 Quality Analysis")
        
        df_quality = pd.DataFrame(quality_data)
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Quality by intent
            if not df_quality.empty:
                fig = px.bar(df_quality, x='intent', y='pass_rate',
                           title="Quality Pass Rates by Task Type",
                           labels={'pass_rate': 'Quality Pass Rate', 'intent': 'Task Type'},
                           color='pass_rate',
                           color_continuous_scale='RdYlGn')
                fig.update_layout(xaxis_tickangle=-45)
                st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            st.markdown("### 🎯 Quality Insights")
            for _, row in df_quality.iterrows():
                intent = row['intent']
                pass_rate = row['pass_rate']
                sample_size = row.get('sample_size', 0)
                
                color = "🟢" if pass_rate > 0.8 else "🟡" if pass_rate > 0.6 else "🔴"
                
                st.markdown(f"""
                **{color} {intent.replace('_', ' ').title()}**  
                Quality: {pass_rate:.1%} ({sample_size} samples)  
                __{intent_explanations.get(intent, 'N/A')}__
                """)

    # Detailed Performance Table
    st.markdown("---")
    st.subheader("📋 Detailed Performance Table")
    
    if intent_data:
        df_display = df_intent[['intent', 'session_count', 'completion_rate', 'avg_steps', 'avg_success_score', 'performance_grade']].copy()
        df_display.columns = ['Task Type', 'Sessions', 'Success Rate', 'Avg Steps', 'Quality Score', 'Grade']
        
        # Format for display
        df_display['Success Rate'] = df_display['Success Rate'].apply(lambda x: f"{x:.1%}")
        df_display['Quality Score'] = df_display['Quality Score'].apply(lambda x: f"{x:.2f}")
        df_display['Avg Steps'] = df_display['Avg Steps'].apply(lambda x: f"{x:.1f}")
        
        st.dataframe(df_display, use_container_width=True)
        
        # Universal Insights
        best_task = intent_data[0]['intent'] if intent_data else "N/A" 
        worst_task = min(intent_data, key=lambda x: x['completion_rate'])['intent'] if intent_data else "N/A"
        
        st.markdown(f"""
        ### 💡 Key Insights for {type_names[agent_type]} Agent
        - **Best performing task**: {best_task.replace('_', ' ').title()}
        - **Needs improvement**: {worst_task.replace('_', ' ').title()}
        - **Total interactions processed**: {total_interactions:,}
        - **Average workflow complexity**: {df_intent['avg_steps'].mean():.1f} steps per session
        - **Agent specialization**: {type_names[agent_type]} ({len([i for i in intent_data if i['completion_rate'] > 0.7])} out of {len(intent_data)} task types performing well)
        """)

else:
    st.warning("No agent performance data available. Please check your API connection or ingest some agent sessions.")
    
    st.markdown("""
    ### 📝 How to Get Started
    
    AgentIQ works with any type of AI agent. Simply start ingesting your agent interactions:
    
    **Supported Agent Types:**
    - 👨‍💻 **Coding Assistants**: GitHub Copilot, CodeWhisperer, custom dev tools
    - 🎧 **Customer Service**: Support bots, help desk agents, FAQ assistants  
    - 📊 **Data Science**: Analytics assistants, ML model helpers, research tools
    - 📞 **Sales & BDR**: Lead qualification bots, prospecting assistants
    - 📈 **Marketing**: Content creation bots, campaign managers, SEO tools
    - 🤖 **General Purpose**: ChatGPT integrations, multi-domain assistants
    
    **Universal Metrics:**
    - **Success Rate**: % of conversations that achieve their goal
    - **Response Quality**: AI-evaluated response quality scores  
    - **Response Time**: How quickly your agent responds
    - **Task Complexity**: Average workflow steps per session
    - **Drop-off Analysis**: Where users abandon conversations
    """)

# Footer
st.markdown("---")
st.markdown(f"**AgentIQ Universal Analytics** | API: {API_BASE_URL} | Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
st.markdown("💡 **Universal Platform**: Works with coding, customer service, data science, sales, marketing, and any AI agent type")