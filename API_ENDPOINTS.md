# AgentIQ API Endpoints

## Ingestion Endpoints

### Health Check
- **GET** `/health` - System health check

### Data Ingestion  
- **POST** `/ingest/json` - Ingest JSON format logs
- **POST** `/ingest/csv` - Ingest CSV files
- **GET** `/ingest/status/{task_id}` - Check background processing status
- **GET** `/ingest/tasks` - List all ingestion tasks

### Test Endpoints
- **POST** `/ingest/test/langsmith` - Test LangSmith format ingestion
- **POST** `/ingest/test/generic` - Test generic JSON ingestion

## Analytics Endpoints

### 1. Session Volume Analysis
- **GET** `/analytics/session-volume`
  - Query params: `hours_back` (default: 168), `granularity` (hour/day/week)
  - **Insight**: Session trends, peak usage times, capacity planning

### 2. Intent Performance  
- **GET** `/analytics/intent-performance`
  - Query params: `limit` (default: 10)
  - **Insight**: Which user intents work well vs poorly, completion rates by intent

### 3. Workflow Paths
- **GET** `/analytics/workflow-paths`
  - Query params: `intent_filter` (optional), `min_frequency` (default: 5) 
  - **Insight**: How users actually navigate conversations vs intended flows

### 4. Drop-off Analysis ⭐ MOST IMPACTFUL
- **GET** `/analytics/dropoff-analysis`
  - **Insight**: Exactly where users abandon conversations and why
  - **Impact**: Most actionable insight for improving agent performance

### 5. Tool Performance
- **GET** `/analytics/tool-performance`
  - **Insight**: Which integrations/tools work well vs cause problems

### 6. Quality by Intent 
- **GET** `/analytics/quality-by-intent`
  - **Insight**: Pass rates vs benchmarks, bridge to loss patterns

### 7. Dashboard Summary
- **GET** `/analytics/dashboard-summary`
  - **Insight**: High-level metrics for executive overview

## Key Insights Provided

### Most Impactful Single Insight: Drop-off Analysis
The `/analytics/dropoff-analysis` endpoint shows:
- **Where**: Exact conversation step where users drop off
- **Why**: Common failure reasons and error patterns  
- **Who**: Intent breakdown for each drop-off point
- **Priority**: Impact scores for focusing improvement efforts
- **Actions**: Specific recommendations to fix each issue

Example response shows "Step 1 has 50 drop-offs (10% rate) with billing intent being most affected by API timeout errors" - this tells you exactly what to fix first.

### Usage → Loss Pattern Bridge
The quality endpoints connect usage patterns (what users want) with loss patterns (where agents fail), enabling targeted improvements based on both volume and impact.

## Response Format

All endpoints return structured JSON with:
- **Core metrics**: Counts, rates, scores
- **Actionable insights**: Performance grades, priority levels
- **Recommendations**: Specific next actions
- **Context**: Confidence levels, sample sizes