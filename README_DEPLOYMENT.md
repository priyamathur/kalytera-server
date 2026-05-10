# AgentIQ Deployment Guide

This guide covers deploying AgentIQ to production using Railway (recommended) or other cloud platforms.

## 🚀 Railway Deployment (Recommended)

### Prerequisites
- Railway account ([railway.app](https://railway.app))
- GitHub repository with AgentIQ code
- Anthropic API key (optional, for full evaluation features)

### Quick Deploy

1. **One-Click Deploy**:
   [![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/agentiq)

2. **Manual Deploy**:
   ```bash
   # Install Railway CLI
   npm install -g @railway/cli
   
   # Login to Railway
   railway login
   
   # Deploy from repository
   railway deploy
   ```

### Environment Configuration

Set these environment variables in Railway dashboard:

```bash
# Required
ANTHROPIC_API_KEY=your_anthropic_api_key_here
DATABASE_URL=postgresql://user:pass@host:port/db

# Optional (with defaults)
EVALUATION_BATCH_SIZE=10
EVALUATION_INTERVAL_MINUTES=30
AGENTIQ_TOPIC_KEYWORDS={"billing":["charge","bill"],"refunds":["refund","return"]}
```

### Services Configuration

AgentIQ deploys as two services:

**API Service** (`railway.toml`):
```toml
[[services]]
name = "agentiq-api"
startCommand = "uvicorn api.ingest_endpoints:app --host 0.0.0.0 --port $PORT"
```

**Dashboard Service**:
```toml
[[services]] 
name = "agentiq-dashboard"
startCommand = "streamlit run dashboard/main.py --server.port $PORT --server.address 0.0.0.0"
```

## 🔧 Alternative Deployment Options

### Docker Deployment

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# API
EXPOSE 8000
CMD ["uvicorn", "api.ingest_endpoints:app", "--host", "0.0.0.0", "--port", "8000"]

# Dashboard (separate container)
EXPOSE 8501  
CMD ["streamlit", "run", "dashboard/main.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
```

### Vercel Deployment

```json
{
  "builds": [
    {
      "src": "api/ingest_endpoints.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/(.*)",
      "dest": "api/ingest_endpoints.py"
    }
  ]
}
```

### Heroku Deployment

```bash
# Procfile
web: uvicorn api.ingest_endpoints:app --host 0.0.0.0 --port $PORT
dashboard: streamlit run dashboard/main.py --server.port $PORT --server.address 0.0.0.0
```

## 📊 Post-Deployment Setup

### 1. Initialize Database
```bash
# Run migrations
python -c "from api.database import create_tables; create_tables()"

# Or use alembic
alembic upgrade head
```

### 2. Load Demo Data
```bash
# Generate and upload 500 realistic sessions
python create_production_demo_data.py https://your-deployment-url.com 500
```

### 3. Verify Deployment
```bash
# Run integration tests against deployed instance
python test_integration.py https://your-deployment-url.com
```

### 4. Configure Monitoring
```bash
# Start background evaluation job
curl -X POST "https://your-deployment-url.com/evaluation/start-background?interval_minutes=30"
```

## 🔍 Health Checks & Monitoring

### API Health
```bash
curl https://your-deployment-url.com/health
```

Expected response:
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:00:00",
  "services": {
    "intent_classifier": true,
    "database": true
  }
}
```

### Evaluation System Health
```bash
curl https://your-deployment-url.com/evaluation/health
```

### Pattern Analysis Health
```bash
curl https://your-deployment-url.com/patterns/health
```

## 🚦 Production Checklist

### Security
- [ ] Set strong database passwords
- [ ] Configure CORS origins appropriately
- [ ] Use HTTPS for all endpoints
- [ ] Secure API key storage
- [ ] Enable request rate limiting

### Performance
- [ ] Database connection pooling configured
- [ ] Background job monitoring enabled
- [ ] API response time monitoring
- [ ] Auto-scaling policies set

### Monitoring
- [ ] Application logs configured
- [ ] Error tracking enabled (Sentry recommended)
- [ ] Performance monitoring (APM)
- [ ] Uptime monitoring

### Data Management
- [ ] Database backups automated
- [ ] Data retention policies defined
- [ ] GDPR compliance measures
- [ ] Export capabilities tested

## 🔧 Troubleshooting

### Common Issues

**API 500 Errors**:
```bash
# Check database connection
python -c "from api.database import SessionLocal; db = SessionLocal(); print('DB OK')"

# Check logs
railway logs --service agentiq-api
```

**Evaluation System Unavailable**:
```bash
# Verify API key
curl -X GET "https://your-deployment-url.com/evaluation/health"

# Check environment variable
railway variables --service agentiq-api
```

**Dashboard Connection Issues**:
```bash
# Update API base URL in dashboard
export AGENTIQ_API_URL=https://your-api-url.com

# Check dashboard logs
railway logs --service agentiq-dashboard
```

### Performance Optimization

**High Memory Usage**:
- Increase Railway service memory limit
- Optimize batch processing sizes
- Enable database query optimization

**Slow Response Times**:
- Enable database indexing
- Implement response caching
- Optimize evaluation batch sizes

**API Rate Limiting**:
- Configure Anthropic API rate limits
- Implement request queuing
- Add retry logic with exponential backoff

## 🔄 Continuous Deployment

### GitHub Actions
```yaml
name: Deploy to Railway
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Deploy to Railway
        uses: railway/deploy@v1
        with:
          token: ${{ secrets.RAILWAY_TOKEN }}
```

### Automated Testing
```yaml
- name: Run Integration Tests
  run: |
    python test_integration.py ${{ secrets.DEPLOYMENT_URL }}
```

## 📈 Scaling Considerations

### Database Scaling
- **SQLite**: Development only, max ~1000 sessions/day
- **PostgreSQL**: Production ready, scales to millions of interactions
- **Distributed**: Consider database sharding for enterprise scale

### API Scaling
- **Single instance**: Up to 1000 requests/minute
- **Load balanced**: Horizontal scaling with multiple Railway services
- **Enterprise**: Kubernetes deployment with auto-scaling

### Background Jobs
- **Single worker**: Processes ~100 evaluations/minute
- **Multiple workers**: Parallel evaluation processing
- **Queue system**: Redis/RabbitMQ for enterprise deployments

---

## 🎯 Quick Start Commands

```bash
# Deploy to Railway
railway deploy

# Load demo data
python create_production_demo_data.py https://your-url.com

# Run integration tests
python test_integration.py https://your-url.com

# Check health
curl https://your-url.com/health
```

Your AgentIQ deployment should be live and processing agent interactions within 5 minutes! 🚀