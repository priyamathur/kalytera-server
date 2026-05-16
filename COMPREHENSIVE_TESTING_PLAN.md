# AgentIQ Comprehensive Testing Plan

## 🎯 Objective
Test the complete AgentIQ platform end-to-end to validate enterprise readiness, focusing on:
1. **Full LLM Evaluation** (with Claude API key)
2. **Autonomous Pattern Detection** 
3. **Complete Production Deployment**

---

## 🧪 Phase 1: LLM Evaluation Engine Testing

### Test 1.1: Claude API Integration
**Goal**: Verify Claude Sonnet 4 is properly integrated and responding

**Steps for You:**
1. Restart the API server to pick up new API key
2. Run: `curl http://localhost:8000/evaluation/health`
3. Verify response shows: `"evaluation_system": "online"`

**Steps for Me:**
1. Fix any remaining endpoint issues
2. Test single interaction evaluation
3. Validate 7-category failure taxonomy

**Expected Results:**
- ✅ API key authentication working
- ✅ Health endpoint returns 200
- ✅ Model shows "claude-sonnet-4"

### Test 1.2: Single Interaction Evaluation
**Goal**: Test LLM judge on real agent conversations

**Test Cases:**
```bash
# Test Case 1: Good Response
curl -X POST http://localhost:8000/evaluation/evaluate-interaction \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "I need to cancel my subscription",
    "agent_response": "I can help you cancel your subscription. Let me process that for you right away.",
    "context": "customer support"
  }'

# Test Case 2: Poor Response  
curl -X POST http://localhost:8000/evaluation/evaluate-interaction \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "I have a billing dispute",
    "agent_response": "Sorry, I cannot help with that. Please try again later.",
    "context": "customer support"
  }'
```

**Expected Results:**
- ✅ Good response: Overall score > 0.8, failure_category = null
- ✅ Poor response: Overall score < 0.5, failure_category = "incomplete"
- ✅ Response includes all 5 score dimensions
- ✅ Reasoning and suggestions provided

### Test 1.3: Batch Evaluation
**Goal**: Test autonomous evaluation of existing logs

**Steps:**
```bash
# Load test data first
python3 populate_sophisticated_data.py

# Trigger batch evaluation
curl -X POST http://localhost:8000/evaluation/batch-evaluate

# Check evaluation results
sqlite3 agentiq.db "SELECT COUNT(*) FROM eval_results WHERE failure_category IS NOT NULL;"
```

**Expected Results:**
- ✅ Evaluations created for all unevaluated logs
- ✅ failure_category populated using 7-category taxonomy
- ✅ Scores distributed realistically (not all perfect)

---

## 🔍 Phase 2: Autonomous Pattern Detection Testing

### Test 2.1: Intent Pattern Analysis
**Goal**: Verify pattern detection algorithms find meaningful insights

**Steps:**
```bash
# Trigger pattern analysis
curl -X POST http://localhost:8000/patterns/analyze

# Check intent patterns
curl http://localhost:8000/patterns/insights/top-intents

# Check failure patterns  
curl http://localhost:8000/patterns/insights/failure-analysis
```

**Expected Results:**
- ✅ Intent patterns discovered (> 0 patterns)
- ✅ Top intents show actual data (not empty)
- ✅ Failure patterns identified with root causes
- ✅ Key insights provided for each pattern

### Test 2.2: Drop-off Analysis Validation
**Goal**: Ensure drop-off analysis provides actionable insights

**Test:**
```bash
curl http://localhost:8000/analytics/drop-off-analysis
```

**Validation Criteria:**
- ✅ Multiple step drop-off points identified
- ✅ Intent breakdown shows distribution
- ✅ Drop rates are realistic (5%-30% range)
- ✅ Common failure reasons provided

### Test 2.3: Quality by Intent Analysis
**Goal**: Verify intent-specific quality analysis

**Test:**
```bash
curl http://localhost:8000/analytics/quality-by-intent
```

**Expected Results:**
- ✅ Different intents show different quality scores
- ✅ Sample sizes are reasonable (> 5 per intent)
- ✅ Pass rates vary meaningfully between intents
- ✅ Top failure patterns identified per intent

---

## 🚀 Phase 3: Production Deployment Testing

### Test 3.1: Local Production Readiness
**Goal**: Validate all systems work together locally

**Comprehensive Test Script:**
```bash
# Run the updated comprehensive test
python3 comprehensive_agentiq_test.py
```

**Success Criteria:**
- ✅ Overall success rate ≥ 85%
- ✅ DAY 4 LLM Judge: 100% working
- ✅ Enterprise Vision: 85%+ validation
- ✅ All analytics endpoints functional

### Test 3.2: Production Deployment Update
**Goal**: Deploy latest changes to production

**Steps for You:**
1. Commit latest changes to GitHub
2. Update production environment variables with API key
3. Trigger Render deployment
4. Verify production health

**Steps for Me:**
1. Update production deployment scripts
2. Test production API endpoints
3. Validate production database schema
4. Monitor performance metrics

### Test 3.3: Production Integration Test
**Goal**: Test complete flow on production

**Test Data Flow:**
```bash
# 1. Send test data to production
curl -X POST https://agentiq-api-z9it.onrender.com/ingest/json \
  -H "Content-Type: application/json" \
  -d @sophisticated_test_data.json

# 2. Trigger production evaluation
curl -X POST https://agentiq-api-z9it.onrender.com/evaluation/batch-evaluate

# 3. Verify production analytics
curl https://agentiq-api-z9it.onrender.com/analytics/dashboard-summary

# 4. Test production pattern detection
curl https://agentiq-api-z9it.onrender.com/patterns/insights/top-intents
```

**Expected Results:**
- ✅ Production API responds < 3 seconds
- ✅ Data ingestion works end-to-end
- ✅ LLM evaluation runs in production
- ✅ Analytics show real-time updates
- ✅ Pattern detection provides insights

---

## 🎪 Phase 4: Enterprise Demonstration Validation

### Test 4.1: Customer Success Scenario
**Goal**: Simulate enterprise customer using AgentIQ

**Scenario**: SaaS company with 100 customer service agents
```python
# Load enterprise demo data
python3 enterprise_demo_data.py

# Simulate 1 week of agent activity  
# 500 sessions, 2000 interactions, 5 intent types
```

**Demo Flow:**
1. **Data Ingestion**: Show agents sending data to AgentIQ
2. **Real-time Analytics**: Display live usage patterns
3. **LLM Evaluation**: Show autonomous quality scoring
4. **Pattern Detection**: Reveal failure modes and root causes
5. **Business Impact**: Demonstrate ROI insights

### Test 4.2: Developer Integration Test  
**Goal**: Validate SDK and API integration experience

**Integration Test:**
```python
# Test AgentIQ SDK
from agentiq_sdk import AgentIQ

client = AgentIQ(api_url="http://localhost:8000")

# Single line integration
client.trace(
    session_id="demo_session",
    step_name="customer_support",
    input="Customer complaint about billing",
    output="Resolved billing issue with refund",
    metadata={"intent": "billing", "success": True}
)

# Verify data appears in dashboard immediately
```

### Test 4.3: Executive Dashboard Demo
**Goal**: Show C-level insights and reporting

**Dashboard Validation:**
- ✅ High-level metrics: completion rates, quality scores
- ✅ Trend analysis: usage patterns over time  
- ✅ ROI indicators: cost savings, efficiency gains
- ✅ Risk alerts: failure patterns, SLA breaches
- ✅ Actionable insights: specific improvement recommendations

---

## 📊 Success Metrics & Validation Criteria

### Overall Platform Readiness
- **Infrastructure**: 100% uptime, < 2s response times
- **Functionality**: 90%+ test pass rate across all phases
- **Data Quality**: Real patterns discovered, not dummy data
- **User Experience**: Intuitive dashboard, clear insights

### Enterprise Sales Readiness
- **Value Demonstration**: Clear business impact shown
- **Technical Credibility**: Real LLM evaluation, not mock-ups
- **Integration Simplicity**: One-line code integration
- **Scalability Evidence**: Handles 1000+ sessions smoothly

### Production Deployment Readiness  
- **API Stability**: All endpoints respond correctly
- **Data Pipeline**: Ingestion → Analysis → Insights working
- **Security**: Proper authentication and error handling
- **Monitoring**: Health checks and performance metrics

---

## 🎯 Final Validation Checklist

### For You to Test:
- [ ] API server starts without errors
- [ ] Health endpoints return 200
- [ ] Can trigger evaluations manually
- [ ] Dashboard shows real data
- [ ] Production deployment accessible

### For Me to Validate:
- [ ] LLM evaluation returns realistic scores
- [ ] Failure taxonomy categorizes correctly  
- [ ] Pattern detection finds actual insights
- [ ] Analytics show meaningful trends
- [ ] Enterprise demo tells compelling story

### Joint Testing:
- [ ] End-to-end workflow: Agent → AgentIQ → Insights
- [ ] Performance under load (100+ concurrent requests)
- [ ] Error handling and recovery scenarios
- [ ] Business value demonstration for prospects

---

## 🚀 Next Steps After Testing

**If Tests Pass (90%+ success):**
1. **Customer Demonstrations**: Ready for enterprise sales calls
2. **Developer Adoption**: Publish integration guides
3. **Production Launch**: Open API for customer usage
4. **Launch Post**: Share AgentIQ publicly

**If Tests Need Work:**
1. **Focus Areas**: Address specific failing test categories  
2. **Iteration**: Fix → Test → Validate cycle
3. **Timeline**: Target 90%+ success within 2-3 iterations

This comprehensive testing plan ensures AgentIQ meets enterprise standards and delivers on the vision from your one-pager: **sophisticated agent monitoring that proves business impact**.

---

**Testing Status**: Ready to execute Phase 1 (LLM Evaluation) immediately
**Estimated Timeline**: 2-3 hours for complete validation
**Success Target**: 90%+ pass rate across all test phases