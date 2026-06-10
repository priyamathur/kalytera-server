"""
AgentIQ Streamlit Dashboard - Real-time Agent Monitoring
3 Core Views: Agent Overview, Failure Feed, Interaction Detail + Quality Config
"""

import streamlit as st
import requests
from typing import Dict, Any, Optional

# Page configuration
st.set_page_config(
    page_title="AgentIQ - Real-time Agent Monitoring",
    page_icon=">", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# API Configuration
import os
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
if hasattr(st, "secrets") and st.secrets.get("api_base_url"):
    API_BASE_URL = st.secrets.get("api_base_url")

# Custom CSS for modern UI
st.markdown("""
<style>
    .main-header { 
        font-size: 2.5rem; 
        color: #1f77b4; 
        text-align: center; 
        margin-bottom: 2rem; 
        font-weight: 600;
    }
    
    .metric-card { 
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 1.5rem; 
        border-radius: 10px; 
        margin: 0.5rem 0; 
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    
    .failure-card { 
        border-left: 4px solid #dc3545; 
        padding: 1rem; 
        margin: 0.5rem 0; 
        background-color: #fff5f5;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
    }
    
    .pattern-card { 
        border-left: 4px solid #ffc107; 
        padding: 1rem; 
        margin: 0.5rem 0; 
        background-color: #fffbf0;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
    }
    
    .success-card { 
        border-left: 4px solid #28a745; 
        padding: 1rem; 
        margin: 0.5rem 0; 
        background-color: #f8fff9;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
    }
    
    .status-success { color: #28a745; font-weight: bold; }
    .status-warning { color: #ffc107; font-weight: bold; }
    .status-danger { color: #dc3545; font-weight: bold; }
    
    .quality-score {
        display: inline-block;
        padding: 0.25rem 0.5rem;
        border-radius: 15px;
        font-weight: bold;
        font-size: 0.9rem;
    }
    
    .quality-high { background-color: #d4edda; color: #155724; }
    .quality-medium { background-color: #fff3cd; color: #856404; }
    .quality-low { background-color: #f8d7da; color: #721c24; }
    
    .step-indicator {
        display: inline-block;
        width: 30px;
        height: 30px;
        border-radius: 50%;
        text-align: center;
        line-height: 30px;
        color: white;
        font-weight: bold;
        margin-right: 0.5rem;
    }
    
    .step-success { background-color: #28a745; }
    .step-warning { background-color: #ffc107; }
    .step-failure { background-color: #dc3545; }
</style>
""", unsafe_allow_html=True)

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

def format_quality_score(score: float) -> str:
    """Format quality score with colored badge"""
    if score >= 0.8:
        return f'<span class="quality-score quality-high">{score:.2f}</span>'
    elif score >= 0.6:
        return f'<span class="quality-score quality-medium">{score:.2f}</span>'
    else:
        return f'<span class="quality-score quality-low">{score:.2f}</span>'

def format_step_indicator(step: int, score: float) -> str:
    """Format workflow step indicator with color"""
    if score >= 0.8:
        css_class = "step-success"
    elif score >= 0.6:
        css_class = "step-warning"
    else:
        css_class = "step-failure"
    
    return f'<span class="step-indicator {css_class}">{step}</span>'

# Sidebar Navigation
