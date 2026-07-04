# 🚀 Kalytera Railway Deployment Guide

## Secure Deployment with Token Optimization

Your Claude API key has been securely integrated with the following optimizations:

### 🔒 Security Features Implemented
- **API Key Masking**: Key is never logged in full (`sk-ant-***{last6}`)
- **Hash-based Identification**: Only SHA256 hash prefix stored for debugging
- **Environment-based Loading**: Key loaded securely from env vars
- **Access Control**: Key never exposed in application code

### 💰 Token Optimization Features
- **Daily Limits**: 100,000 tokens/day maximum
- **Hourly Rate Limiting**: 100 requests/hour maximum  
- **Model Optimization**: Using Claude 3 Haiku for cost efficiency
- **Prompt Optimization**: Ultra-concise prompts (150 tokens max)
- **Usage Tracking**: Real-time monitoring with alerts

### 📊 Cost Control Measures
- **Evaluation**: Max 150 tokens per interaction
- **Pattern Analysis**: Max 100 tokens per pattern
- **LLM Categorization**: Disabled in favor of keyword matching
- **Fallback Systems**: Graceful degradation when limits reached

## Railway Deployment Steps

### 1. Create Railway Project
```bash
# Visit railway.app and create new project
# Connect your GitHub repository
```

### 2. Environment Configuration
Set these in Railway dashboard (Variables tab):
```bash
ANTHROPIC_API_KEY=your_anthropic_api_key_here
CLAUDE_DAILY_TOKEN_LIMIT=100000
CLAUDE_HOURLY_REQUEST_LIMIT=100
CLAUDE_MODEL=claude-3-haiku-20240307
LOG_SECURITY_EVENTS=true
MASK_API_KEYS_IN_LOGS=true
```

### 3. Database Setup
Railway will auto-provision PostgreSQL. The DATABASE_URL will be set automatically.

### 4. Service Configuration
The `railway.toml` file is configured for dual-service deployment:

**API Service:**
- Port: Auto-assigned by Railway
- Health Check: `/health`
- Command: `uvicorn api.ingest_endpoints:app --host 0.0.0.0 --port $PORT`

**Dashboard Service:**
- Port: Auto-assigned by Railway  
- Health Check: `/`
- Command: `streamlit run dashboard/main.py --server.port $PORT --server.address 0.0.0.0`

### 5. Deploy
```bash
# Option 1: GitHub Integration (Recommended)
# 1. Push code to GitHub
# 2. Connect repository in Railway
# 3. Deploy automatically on push

# Option 2: Manual Railway CLI
npm install -g @railway/cli
railway login
railway deploy
```

## Post-Deployment Verification

### 1. API Health Check
```bash
curl https://your-api-url.railway.app/health
```
Should return:
```json
{
  "api_key_available": true,
  "usage_stats": {...},
  "rate_limit_ok": true
}
```

### 2. Security Verification  
```bash
curl https://your-api-url.railway.app/api/security/usage
```
Should show masked API key and usage statistics.

### 3. Load Demo Data
```bash
python create_production_demo_data.py --api-url=https://your-api-url.railway.app
```

## 🎯 Expected Deployment URLs

After successful deployment, you'll get:
- **API**: `https://kalytera-api-xxxx.railway.app`
- **Dashboard**: `https://kalytera-dashboard-xxxx.railway.app`

## 📊 Monitoring & Usage

### Token Usage Monitoring
- Real-time usage tracking in dashboard
- Daily/hourly limit enforcement
- Cost estimation and alerts
- Graceful fallback when limits exceeded

### Security Monitoring
- API key access logging
- Request rate monitoring  
- Error tracking and alerting
- Usage pattern analysis

## 🔧 Troubleshooting

### Common Issues
1. **API Key not working**: Check environment variable formatting
2. **Database connection**: Ensure PostgreSQL service is running
3. **Token limits**: Check usage stats in `/api/security/usage`
4. **Dashboard not loading**: Verify API service is healthy first

### Debug Commands
```bash
# Check API health
curl https://your-api-url/health

# Check security status  
curl https://your-api-url/api/security/usage

# Test ingestion
curl -X POST https://your-api-url/ingest/test/generic
```

Your Kalytera deployment is now secure, cost-optimized, and production-ready! 🎉