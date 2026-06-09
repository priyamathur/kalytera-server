# AgentIQ Universal Dashboard Deployment

## 🤖 Universal Agent Performance Dashboard

AgentIQ now features a **universal dashboard** that works with **any AI agent type**:

- 👨‍💻 **Coding Assistants**: GitHub Copilot, CodeWhisperer, custom dev tools
- 🎧 **Customer Service**: Support bots, help desk agents, FAQ assistants  
- 📊 **Data Science**: Analytics assistants, ML model helpers, research tools
- 📞 **Sales & BDR**: Lead qualification bots, prospecting assistants
- 📈 **Marketing**: Content creation bots, campaign managers, SEO tools
- 🤖 **General Purpose**: ChatGPT integrations, multi-domain assistants

## Quick Dashboard Access

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

## Universal Dashboard Features

✅ **Auto-Agent Detection** - Automatically detects your agent type (coding, customer service, etc.)
✅ **Universal Metrics** - Success rates, response times, task performance for any domain
✅ **Interpretable Analytics** - Clear explanations of what each metric means
✅ **Real-time System Health** - API, Evaluation, Database status
✅ **Session Analytics** - Volume trends, completion rates across all agent types
✅ **Intent Performance** - Success rates by task type with domain-specific context
✅ **Quality Analysis** - AI-evaluated response quality scores
✅ **Performance Grading** - A-F grades for each task type
✅ **Visual Analytics** - Charts, trends, and insights for any agent specialization

## Live API Endpoints

Your dashboard connects to: **https://agentiq-api-z9it.onrender.com**

All analytics endpoints are working:
- `/analytics/session-volume` - Session activity over time
- `/analytics/intent-performance` - Success rates by task type
- `/analytics/quality-by-intent` - Quality scores and pass rates
- `/evaluation/health` - Evaluation pipeline status
- `/admin/database-status` - Database health check

## Testing with Sample Data

Load sample data for different agent types:

```bash
# Load diverse agent data (coding, customer service, data science, sales, marketing)
python3 load_diverse_agent_data.py

# Load coding-specific data
python3 load_massive_coding_data.py
```

## Dashboard Capabilities

The universal dashboard automatically adapts to show relevant insights for your specific agent type:

- **Coding Agents**: Shows metrics for code generation, debugging, code review, API development
- **Customer Service**: Displays billing, refund, technical support, complaint resolution performance
- **Data Science**: Analytics for data analysis, visualization, model training tasks
- **Sales/BDR**: Metrics for lead qualification, prospecting, meeting scheduling
- **Marketing**: Performance for content creation, campaign analysis, audience research