# How to Test the Real-Time Kalytera Dashboard

## 🚀 **Real-Time Dashboard is Live!**

**Dashboard URL:** http://localhost:8506

The dashboard shows **live agent performance data** with auto-refresh capabilities.

---

## 📊 **Current Dashboard Features**

### **Live Metrics Display:**
- ✅ **Total Sessions**: 89 (live count)
- ✅ **Total Interactions**: 158 (real-time updates)
- ✅ **Completion Rate**: Shows actual performance %
- ✅ **Response Times**: Real average response times
- ✅ **Interactions/Hour**: Live activity rate
- ✅ **Interactions/Session**: Real conversation complexity

### **Real-Time Visualizations:**
- ✅ **Live Activity Timeline**: Dual-axis chart showing sessions (bars) and interactions (line)
- ✅ **Performance Analysis**: Auto-updating performance indicators
- ✅ **Real-Time Insights**: Dynamic alerts based on current performance
- ✅ **Recent Activity Table**: Shows latest hourly data with success rates

### **Auto-Refresh Capabilities:**
- ✅ **Configurable refresh interval** (10-120 seconds)
- ✅ **Auto-refresh toggle**
- ✅ **Manual refresh button**
- ✅ **Live timestamp updates**

---

## 🧪 **How to Test the Dashboard**

### **Method 1: Run the Test Script** (Recommended)
```bash
python3 test_real_time_dashboard.py
```

This script sends 5 different agent interactions across multiple domains:
- 🐛 **Debugging**: Python error troubleshooting
- 👨‍💻 **Code Generation**: React component creation
- 🔐 **Account Recovery**: Password reset assistance
- 📊 **Data Analysis**: Customer data insights
- 📞 **Lead Qualification**: Sales prospect evaluation

**Expected Results:**
- Dashboard metrics update in real-time
- New sessions appear in the timeline
- Performance indicators adjust automatically
- Recent activity table shows new entries

### **Method 2: Manual API Testing**
```bash
# Send a single test interaction
curl -X POST https://kalytera-api-z9it.onrender.com/ingest/json \
  -H "Content-Type: application/json" \
  -d '{
    "data": [{
      "user_input": "Test query at '$(date +%H:%M:%S)'",
      "agent_response": "Test response",
      "session_id": "test-'$(date +%s)'",
      "response_time_ms": 1200,
      "workflow_step": 1,
      "intent": "testing",
      "tool_calls": "[]"
    }]
  }'
```

### **Method 3: Built-in Dashboard Testing**
1. Open http://localhost:8506
2. Look for the sidebar **"🧪 Real-Time Testing"** section
3. Click **"💉 Inject Test Data"** button
4. Watch metrics update immediately

---

## 📈 **What to Watch For**

### **Real-Time Updates (Every 30 seconds by default):**
1. **Session counts increase** as new interactions are sent
2. **Timeline chart updates** with new data points
3. **Performance metrics recalculate** automatically
4. **Activity level changes** based on volume
5. **Insights update** with current performance alerts

### **Performance Indicators:**
- 🟢 **Green**: Excellent performance (>70% completion)
- 🟡 **Yellow**: Good performance (50-70% completion)
- 🔴 **Red**: Needs improvement (<50% completion)

### **Activity Levels:**
- 🔥 **Very High**: >100 interactions today
- 🚀 **High**: 50-100 interactions today  
- 📊 **Moderate**: 10-50 interactions today
- 💤 **Low**: <10 interactions today

### **Real-Time Insights Examples:**
- "🔥 High volume day - monitor response times"
- "⚠️ Low completion rate - investigate common failures"
- "🐌 Slow responses - check system performance"
- "💬 Complex conversations - users need multiple interactions"

---

## 🔍 **Current System Status**

**Live Data Available:**
- ✅ **89 total sessions** across multiple time periods
- ✅ **158 total interactions** with real response times
- ✅ **Real completion rates** showing actual agent performance
- ✅ **Timeline data** from May 11-17, 2026
- ✅ **Live API connectivity** to https://kalytera-api-z9it.onrender.com

**Recent Activity (Live):**
- **Today (May 17)**: 89 sessions, 158 interactions
- **Performance**: 1.1% average completion rate (needs improvement)
- **Activity Level**: 🚀 High (158 interactions today)

---

## 🎯 **Testing Scenarios**

### **Scenario 1: High-Performance Agent**
Send interactions with:
- Fast response times (< 1000ms)
- Clear, helpful responses
- Successful tool calls

**Expected Result**: Dashboard shows green indicators, high completion rates

### **Scenario 2: Struggling Agent**
Send interactions with:
- Slow response times (> 3000ms)
- Incomplete responses
- Error conditions

**Expected Result**: Dashboard shows red indicators, alerts for poor performance

### **Scenario 3: Mixed Workload**
Send diverse agent types:
- Coding assistants
- Customer service
- Data science
- Sales/BDR

**Expected Result**: Dashboard adapts to show universal metrics for all agent types

---

## 📊 **Real-Time Data Flow**

```
Agent Interaction → API Ingest → Database → Analytics → Dashboard
     (Instant)      (< 1s)       (< 1s)     (< 5s)     (30s refresh)
```

**Total latency**: New interactions appear in dashboard within ~30-35 seconds

---

## 🔧 **Troubleshooting**

### **No Data Updates:**
1. Check API health: `curl https://kalytera-api-z9it.onrender.com/health`
2. Verify auto-refresh is enabled in sidebar
3. Try manual refresh button

### **Slow Updates:**
1. Check internet connection
2. Increase refresh interval
3. Check API response times

### **Dashboard Errors:**
1. Refresh the page
2. Check browser console for errors
3. Verify dashboard URL: http://localhost:8506

---

## 🎉 **Success Criteria**

The dashboard is working correctly if you see:

1. ✅ **Real-time metrics** that update every 30 seconds
2. ✅ **Live activity timeline** showing recent data
3. ✅ **Performance indicators** that change with new data  
4. ✅ **System health** showing all green status
5. ✅ **Recent activity table** with latest interactions
6. ✅ **Auto-refresh countdown** in the sidebar

**The dashboard successfully demonstrates real-time agent performance monitoring for any AI agent type!**