# AgentIQ Dashboard Deployment

## Quick Dashboard Access

Your AgentIQ platform has two dashboard options:

### Option 1: Streamlit Cloud (Fastest)
1. Go to https://share.streamlit.io/
2. Connect your GitHub repo: `priyamathur/AgentIQ`
3. Set main file: `simple_dashboard.py`
4. Deploy - you'll get a URL like: `https://agentiq-dashboard-xyz.streamlit.app/`

### Option 2: Render Dashboard Service
1. Create new web service on Render
2. Connect GitHub repo: `priyamathur/AgentIQ`
3. Build command: `pip install -r dashboard_requirements.txt`
4. Start command: `streamlit run simple_dashboard.py --server.port $PORT --server.address 0.0.0.0`
5. Add environment variable: `API_BASE_URL = https://agentiq-api-z9it.onrender.com`

### Option 3: Local Testing
```bash
cd /Users/udayshankar/Documents/AgentIQ
pip install streamlit requests pandas plotly
streamlit run simple_dashboard.py
```

## Dashboard Features

✅ **Real-time System Health** - API, Evaluation, Database status
✅ **Session Analytics** - Volume trends, completion rates  
✅ **Intent Performance** - Success rates by user intent
✅ **Quality Metrics** - Pass rates and quality scores
✅ **API Explorer** - Raw data access for all endpoints

## Live API Endpoints

Your dashboard connects to: **https://agentiq-api-z9it.onrender.com**

All analytics endpoints are working:
- `/analytics/session-volume`
- `/analytics/intent-performance` 
- `/analytics/quality-by-intent`
- `/evaluation/health`
- `/admin/database-status`