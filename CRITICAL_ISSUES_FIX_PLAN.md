# Kalytera Critical Issues Fix Plan

## 🎯 Overview
This plan addresses the critical issues identified in the comprehensive test suite that prevent Kalytera from reaching enterprise readiness. Current status: **50% functional, needs focused fixes to reach 90%+ production readiness.**

---

## 🔴 PHASE 1: DAY 4 LLM Judge System (PRIORITY 1)

### Issue: DAY 4 LLM Judge (0% Ready)

#### Step 1.1: Configure Claude API Key
- **Problem**: Claude API key not configured despite being provided previously
- **Action**: 
  ```bash
  # Find and set the API key in environment
  export ANTHROPIC_API_KEY=sk-ant-api03-[provided_key]
  # Add to .env file for persistence
  echo "ANTHROPIC_API_KEY=sk-ant-api03-[provided_key]" >> .env
  ```
- **Files to check**: 
  - `evaluation/agent_judge.py` - verify API key loading
  - `api/evaluation_endpoints.py` - check initialization
- **Test**: `curl http://localhost:8000/evaluation/health`

#### Step 1.2: Fix Database Schema for Failure Categories
- **Problem**: Database missing `failure_category` column
- **Action**:
  ```sql
  ALTER TABLE eval_results ADD COLUMN failure_category TEXT;
  ```
- **Files to update**: 
  - `db/models.py` - add failure_category to EvalResult model
  - Create migration script if using Alembic
- **Test**: Check column exists with `sqlite3 kalytera.db ".schema eval_results"`

#### Step 1.3: Implement 7-Category Failure Taxonomy
- **Problem**: Taxonomy not implemented
- **Categories**: wrong_answer, tool_failure, goal_drift, incomplete, hallucination, context_loss, loop
- **Files to update**:
  - `evaluation/agent_judge.py` - add taxonomy classification logic
  - `evaluation/prompts.py` - create system prompts for each category
- **Test**: Single evaluation should return one of the 7 categories

#### Step 1.4: Restore Missing Evaluation Endpoints
- **Problem**: 404 errors on `/evaluation/evaluate-interaction` and `/evaluation/batch-evaluate`
- **Action**: 
  - Fix route definitions in `api/evaluation_endpoints.py`
  - Ensure proper imports and function definitions
  - Add error handling for missing API keys
- **Test**: Both endpoints should return 200 or proper error messages

---

## 🏢 PHASE 2: Enterprise Vision Gaps (PRIORITY 2)

### Issue: Usage Analytics Showing Empty Results

#### Step 2.1: Fix Top Intents Analysis
- **Problem**: Empty intents list despite data ingestion
- **Root Cause**: Intent classification not populating metadata correctly
- **Action**:
  - Check `patterns/intent_analyzer.py` for proper intent extraction
  - Ensure session metadata includes intent field
  - Verify database queries in analytics endpoints
- **Files**: `analytics/session_analytics.py`, `patterns/intent_analyzer.py`
- **Test**: `/patterns/insights/top-intents` should show actual intents

#### Step 2.2: Implement Missing Drop-off Analysis Endpoint
- **Problem**: `/analytics/drop-off-analysis` returns 404
- **Action**:
  - Create endpoint in `api/analytics_endpoints.py`
  - Implement logic to track where sessions abandon
  - Calculate drop-off rates by step number and intent
- **Expected Output**: 
  ```json
  {
    "drop_off_by_step": {
      "step_1": {"sessions": 100, "drop_rate": 0.15},
      "step_2": {"sessions": 85, "drop_rate": 0.22}
    }
  }
  ```

#### Step 2.3: Fix Quality by Intent Calculations
- **Problem**: Analytics returning malformed data structure
- **Action**:
  - Debug `analytics/quality_analyzer.py` 
  - Ensure proper aggregation of eval_results by intent
  - Fix data structure returned by endpoint
- **Test**: Should return quality metrics grouped by intent type

#### Step 2.4: Enable Autonomous LLM Evaluation
- **Problem**: No automatic evaluation of incoming interactions
- **Action**:
  - Fix background job in `api/background_jobs.py`
  - Ensure evaluation triggers on data ingestion
  - Add batch processing for existing uneva‌luated logs
- **Test**: New interactions should automatically get eval_results entries

---

## 🚀 PHASE 3: Production Deployment (PRIORITY 3)

### Issue: Render Production API Timing Out

#### Step 3.1: Debug Render Deployment Timeouts
- **Problem**: Production API unresponsive
- **Action**:
  - Check Render service logs for startup errors
  - Verify PostgreSQL connection string format
  - Ensure all dependencies in requirements.txt
  - Check Python version compatibility (force 3.11)
- **Files**: `render.yaml`, `requirements.txt`, `runtime.txt`

#### Step 3.2: Fix PostgreSQL Compatibility Issues
- **Problem**: SQLite queries failing on PostgreSQL
- **Action**:
  - Review all analytics queries for PostgreSQL syntax
  - Replace SQLite-specific functions (datetime() → NOW())
  - Test queries against local PostgreSQL instance
- **Files**: All files in `analytics/` and `patterns/` directories

#### Step 3.3: Deploy Missing Enterprise Endpoints
- **Problem**: Critical endpoints not deployed
- **Action**:
  - Ensure all endpoints from local are included in production
  - Add proper error handling for production environment
  - Test each endpoint individually after deployment

---

## 📋 PHASE 4: Integration and Validation (PRIORITY 4)

#### Step 4.1: Run Comprehensive Test Suite Again
- **Action**: `python3 comprehensive_kalytera_test.py`
- **Target**: 90%+ success rate across all test categories

#### Step 4.2: Load Enterprise Demo Data
- **Action**: 
  - Run `python3 populate_sophisticated_data.py`
  - Verify 500+ sessions with diverse intents
  - Trigger batch evaluation on all data

#### Step 4.3: Validate Enterprise Vision Requirements
- **Checklist**:
  - [ ] Usage analytics show real intent patterns
  - [ ] Drop-off analysis reveals session abandonment points
  - [ ] Quality by intent shows performance differences
  - [ ] Autonomous LLM evaluation runs on every interaction
  - [ ] Loss pattern analysis surfaces root causes
  - [ ] Structured RL data available for developers

---

## 🎯 Expected Outcomes

**After Phase 1**: DAY 4 LLM Judge fully operational (0% → 100%)
**After Phase 2**: Enterprise vision gaps resolved (17% → 85%+)
**After Phase 3**: Production deployment stable and responsive
**After Phase 4**: Platform ready for enterprise demonstrations

## 🔧 Implementation Priority Order

1. **Start Here**: Fix Claude API key configuration
2. **Database**: Add failure_category column and taxonomy
3. **Endpoints**: Restore missing evaluation routes
4. **Analytics**: Fix drop-off analysis and quality calculations
5. **Production**: Debug Render deployment issues
6. **Validation**: Run comprehensive tests

## 📊 Success Metrics

- Comprehensive test suite: 90%+ pass rate
- All 7 failure categories working
- Real usage analytics data populated
- Production API response time < 2 seconds
- Enterprise demo ready within 3-4 hours of focused work

---

**Notes**: 
- Claude API key was provided previously - locate and configure properly
- Focus on DAY 4 LLM Judge first - this unlocks enterprise evaluation capabilities
- Production deployment issues are secondary to core functionality
- Test frequently during implementation to catch regressions early