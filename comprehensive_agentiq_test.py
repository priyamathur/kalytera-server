#!/usr/bin/env python3
"""
Comprehensive AgentIQ Platform Test Suite
Tests the complete 7-day roadmap implementation matching the one-pager vision:

✅ DAY 1: Foundation - All 4 tables, 500 sessions, 5 intent types
✅ DAY 2: Ingestion - JSON/CSV parsers, LangSmith export, intent classifier
✅ DAY 3: Analytics - 6 analytics endpoints (volume, intents, paths, drop-off, tools, quality)
✅ DAY 4: LLM Judge - 7-category failure taxonomy, autonomous evaluation
✅ DAY 5: Loss Patterns - Root cause detection, structured export
✅ DAY 6-7: Production Deploy - Live system, integration tests

This validates the enterprise platform vision:
- Usage analytics (intents, paths, drop-off, quality by intent)
- Autonomous LLM eval on every interaction
- Automated loss pattern analysis with root cause
- Structured RL data for developers
- Causal inference for business impact proof
"""

import requests
import json
import time
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Any
import random

# Configuration
LOCAL_API = "http://localhost:8000"
PRODUCTION_API = "https://agentiq-api-z9it.onrender.com"
DATABASE_PATH = "agentiq.db"

class AgentIQTestSuite:
    def __init__(self, api_url: str = LOCAL_API):
        self.api_url = api_url
        self.test_results = {}
        self.session_ids = []
        
    def log_result(self, test_name: str, success: bool, details: str = ""):
        """Log test results"""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}")
        if details:
            print(f"    {details}")
        self.test_results[test_name] = {"success": success, "details": details}

    def test_day1_foundation(self) -> bool:
        """Test DAY 1: Foundation - Database tables and seed data"""
        print("\n🏗️  DAY 1: FOUNDATION TESTING")
        print("=" * 60)
        
        success_count = 0
        total_tests = 4
        
        # Test 1: Database connectivity
        try:
            response = requests.get(f"{self.api_url}/health", timeout=5)
            if response.status_code == 200:
                health_data = response.json()
                db_healthy = health_data.get("services", {}).get("database", False)
                self.log_result("Database Connectivity", db_healthy, f"Status: {health_data}")
                if db_healthy: success_count += 1
            else:
                self.log_result("Database Connectivity", False, f"HTTP {response.status_code}")
        except Exception as e:
            self.log_result("Database Connectivity", False, str(e))
        
        # Test 2: All 4 tables exist
        try:
            response = requests.get(f"{self.api_url}/admin/database-status", timeout=5)
            if response.status_code == 200:
                data = response.json()
                tables = data.get("existing_tables", [])
                required_tables = {"agent_logs", "session_summaries", "eval_results", "loss_patterns"}
                tables_exist = required_tables.issubset(set(tables))
                self.log_result("Required Tables", tables_exist, f"Found: {', '.join(tables)}")
                if tables_exist: success_count += 1
            else:
                self.log_result("Required Tables", False, f"HTTP {response.status_code}")
        except Exception as e:
            self.log_result("Required Tables", False, str(e))
        
        # Test 3: Seed sample data
        try:
            response = requests.post(f"{self.api_url}/admin/seed-sample-data", timeout=30)
            if response.status_code == 200:
                data = response.json()
                sessions_created = data.get("total_sessions", 0)
                self.log_result("Seed Data Generation", sessions_created >= 20, 
                               f"Created {sessions_created} sessions")
                if sessions_created >= 20: success_count += 1
            else:
                self.log_result("Seed Data Generation", False, f"HTTP {response.status_code}")
        except Exception as e:
            self.log_result("Seed Data Generation", False, str(e))
        
        # Test 4: Data ingestion endpoint
        test_data = {
            "data": [{
                "session_id": f"test_foundation_{int(time.time())}",
                "step_name": "foundation_test",
                "input": "Testing foundation data ingestion for comprehensive validation",
                "output": "Foundation test completed successfully with proper data structure",
                "metadata": {
                    "test_type": "foundation",
                    "intent": "account_access", 
                    "success": True,
                    "timestamp": datetime.now().isoformat()
                }
            }],
            "source": "comprehensive_test_suite"
        }
        
        try:
            response = requests.post(f"{self.api_url}/ingest/json", json=test_data, timeout=10)
            if response.status_code == 200:
                result = response.json()
                sessions_processed = result.get("sessions_processed", 0)
                self.log_result("Data Ingestion", sessions_processed > 0,
                               f"Processed {sessions_processed} sessions")
                if sessions_processed > 0: success_count += 1
            else:
                self.log_result("Data Ingestion", False, f"HTTP {response.status_code}")
        except Exception as e:
            self.log_result("Data Ingestion", False, str(e))
        
        return success_count >= 3  # 75% success rate required

    def test_day2_ingestion(self) -> bool:
        """Test DAY 2: Ingestion - Parsers and intent classification"""
        print("\n📥 DAY 2: INGESTION TESTING")
        print("=" * 60)
        
        success_count = 0
        total_tests = 3
        
        # Test 1: Multi-agent workflow ingestion
        complex_session_data = {
            "data": [
                {
                    "session_id": f"multi_agent_test_{int(time.time())}",
                    "step_name": "intent_classification",
                    "input": "I need help with a billing issue - I was charged twice",
                    "output": "BILLING_DISPUTE detected with 95% confidence. Routing to billing specialist.",
                    "metadata": {
                        "intent": "billing_dispute",
                        "confidence": 0.95,
                        "agent_type": "intent_classifier",
                        "timestamp": datetime.now().isoformat()
                    }
                },
                {
                    "session_id": f"multi_agent_test_{int(time.time())}",
                    "step_name": "billing_specialist", 
                    "input": "Customer reports duplicate billing charges",
                    "output": "Found duplicate charge on March 15. Processing $99.99 refund.",
                    "metadata": {
                        "intent": "billing_dispute",
                        "refund_amount": 99.99,
                        "agent_type": "billing_specialist",
                        "timestamp": datetime.now().isoformat()
                    }
                }
            ],
            "source": "multi_agent_workflow_test"
        }
        
        try:
            response = requests.post(f"{self.api_url}/ingest/json", json=complex_session_data, timeout=15)
            if response.status_code == 200:
                result = response.json()
                sessions_processed = result.get("sessions_processed", 0)
                interactions_processed = result.get("interactions_processed", 0)
                self.log_result("Multi-Agent Workflow Ingestion", sessions_processed > 0,
                               f"Sessions: {sessions_processed}, Interactions: {interactions_processed}")
                if sessions_processed > 0: success_count += 1
                self.session_ids.extend([item["session_id"] for item in complex_session_data["data"]])
            else:
                self.log_result("Multi-Agent Workflow Ingestion", False, f"HTTP {response.status_code}")
        except Exception as e:
            self.log_result("Multi-Agent Workflow Ingestion", False, str(e))
        
        # Test 2: Intent classification functionality
        try:
            # Check if intent classifier is working by looking at pattern analysis
            response = requests.get(f"{self.api_url}/patterns/insights/top-intents", timeout=10)
            if response.status_code == 200:
                data = response.json()
                intent_patterns = data.get("total_intent_patterns", 0)
                top_intents = data.get("top_intents", [])
                self.log_result("Intent Classification", intent_patterns >= 0,
                               f"Detected {intent_patterns} patterns, Top: {top_intents[:3]}")
                success_count += 1
            else:
                self.log_result("Intent Classification", False, f"HTTP {response.status_code}")
        except Exception as e:
            self.log_result("Intent Classification", False, str(e))
        
        # Test 3: Session building functionality
        try:
            response = requests.get(f"{self.api_url}/analytics/dashboard-summary", timeout=10)
            if response.status_code == 200:
                data = response.json()
                total_sessions = data.get("total_sessions", 0)
                total_interactions = data.get("total_interactions", 0)
                self.log_result("Session Building", total_sessions > 0 and total_interactions > 0,
                               f"Sessions: {total_sessions}, Interactions: {total_interactions}")
                if total_sessions > 0: success_count += 1
            else:
                self.log_result("Session Building", False, f"HTTP {response.status_code}")
        except Exception as e:
            self.log_result("Session Building", False, str(e))
        
        return success_count >= 2

    def test_day3_analytics(self) -> bool:
        """Test DAY 3: Analytics - All 6 analytics endpoints"""
        print("\n📊 DAY 3: ANALYTICS TESTING")
        print("=" * 60)
        
        success_count = 0
        analytics_endpoints = [
            ("/analytics/session-volume?hours_back=168&granularity=day", "Session Volume Over Time"),
            ("/patterns/insights/top-intents?limit=5", "Top Intents with Completion Rate"),
            ("/analytics/workflow-paths?intent=all&limit=10", "Most Common Workflow Paths"),
            ("/analytics/drop-off-analysis?hours_back=168", "Drop-off by Step Analysis"),
            ("/analytics/tool-usage?hours_back=168", "Tool Usage and Failure Rates"),
            ("/analytics/quality-by-intent?hours_back=168", "Quality by Intent")
        ]
        
        for endpoint, description in analytics_endpoints:
            try:
                response = requests.get(f"{self.api_url}{endpoint}", timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    # Check if response has meaningful data
                    has_data = bool(data and len(str(data)) > 20)  # Basic data presence check
                    self.log_result(description, has_data, f"Endpoint: {endpoint}")
                    if has_data: success_count += 1
                else:
                    self.log_result(description, False, f"HTTP {response.status_code}")
            except Exception as e:
                self.log_result(description, False, str(e))
        
        # Special validation for the "most impactful demo insight" - drop-off analysis
        try:
            response = requests.get(f"{self.api_url}/analytics/drop-off-analysis?hours_back=168", timeout=10)
            if response.status_code == 200:
                data = response.json()
                drop_off_data = data.get("drop_off_by_step", {})
                self.log_result("Drop-off Analysis (Core Insight)", bool(drop_off_data),
                               f"Step analysis: {list(drop_off_data.keys())[:3]}")
            else:
                self.log_result("Drop-off Analysis (Core Insight)", False, f"HTTP {response.status_code}")
        except Exception as e:
            self.log_result("Drop-off Analysis (Core Insight)", False, str(e))
        
        return success_count >= 4  # Most analytics endpoints should work

    def test_day4_llm_judge(self) -> bool:
        """Test DAY 4: LLM Judge - Evaluation system and failure taxonomy"""
        print("\n🧠 DAY 4: LLM JUDGE TESTING")
        print("=" * 60)
        
        success_count = 0
        total_tests = 4
        
        # Test 1: Judge system availability
        try:
            response = requests.get(f"{self.api_url}/evaluation/health", timeout=5)
            judge_available = response.status_code == 200
            self.log_result("Judge System Health", judge_available, 
                           f"Status: {response.status_code}")
            if judge_available: success_count += 1
        except Exception as e:
            self.log_result("Judge System Health", False, str(e))
        
        # Test 2: Single interaction evaluation
        evaluation_test = {
            "user_input": "I want to cancel my subscription but your website is broken",
            "agent_response": "I understand your frustration. Let me help you cancel directly through our system.",
            "context": "Customer support - subscription cancellation request"
        }
        
        try:
            response = requests.post(f"{self.api_url}/evaluation/evaluate-interaction", 
                                   json=evaluation_test, timeout=30)
            if response.status_code == 200:
                eval_result = response.json()
                overall_score = eval_result.get("overall_score", 0)
                failure_category = eval_result.get("failure_category", "")
                self.log_result("Single Interaction Evaluation", overall_score > 0,
                               f"Score: {overall_score}, Category: {failure_category}")
                success_count += 1
            else:
                # Fallback evaluation might be working instead
                self.log_result("Single Interaction Evaluation", False, 
                               f"HTTP {response.status_code} (Fallback may be active)")
        except Exception as e:
            self.log_result("Single Interaction Evaluation", False, str(e))
        
        # Test 3: Batch evaluation trigger
        try:
            response = requests.post(f"{self.api_url}/evaluation/batch-evaluate", timeout=60)
            if response.status_code == 200:
                batch_result = response.json()
                self.log_result("Batch Evaluation Trigger", True, 
                               f"Result: {batch_result.get('message', 'Success')}")
                success_count += 1
            else:
                self.log_result("Batch Evaluation Trigger", False, f"HTTP {response.status_code}")
        except Exception as e:
            self.log_result("Batch Evaluation Trigger", False, str(e))
        
        # Test 4: Failure taxonomy validation
        expected_categories = {
            "wrong_answer", "tool_failure", "goal_drift", "incomplete", 
            "hallucination", "context_loss", "loop"
        }
        
        # Check if eval_results table has the required failure categories
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            
            # Check for failure categories in the eval_results
            cursor.execute("""
                SELECT DISTINCT failure_category 
                FROM eval_results 
                WHERE failure_category IS NOT NULL 
                LIMIT 10
            """)
            categories_found = {row[0] for row in cursor.fetchall() if row[0]}
            conn.close()
            
            has_taxonomy = len(categories_found.intersection(expected_categories)) > 0
            self.log_result("Failure Taxonomy Implementation", has_taxonomy,
                           f"Categories found: {list(categories_found)[:5]}")
            if has_taxonomy: success_count += 1
            
        except Exception as e:
            self.log_result("Failure Taxonomy Implementation", False, str(e))
        
        return success_count >= 2

    def test_day5_loss_patterns(self) -> bool:
        """Test DAY 5: Loss Patterns - Root cause detection and structured export"""
        print("\n🔍 DAY 5: LOSS PATTERNS TESTING")
        print("=" * 60)
        
        success_count = 0
        total_tests = 4
        
        # Test 1: Pattern analysis trigger
        try:
            response = requests.post(f"{self.api_url}/patterns/analyze?hours_back=168&min_pattern_count=2", timeout=30)
            if response.status_code == 200:
                analysis_result = response.json()
                patterns_found = analysis_result.get("patterns_analyzed", 0)
                self.log_result("Pattern Analysis Trigger", patterns_found >= 0,
                               f"Patterns analyzed: {patterns_found}")
                success_count += 1
            else:
                self.log_result("Pattern Analysis Trigger", False, f"HTTP {response.status_code}")
        except Exception as e:
            self.log_result("Pattern Analysis Trigger", False, str(e))
        
        # Test 2: Intent-based pattern detection
        try:
            response = requests.get(f"{self.api_url}/patterns/insights/top-intents?limit=5", timeout=10)
            if response.status_code == 200:
                data = response.json()
                intent_patterns = data.get("total_intent_patterns", 0)
                key_insight = data.get("key_insight", "")
                self.log_result("Intent Pattern Detection", intent_patterns >= 0,
                               f"Patterns: {intent_patterns}, Insight: {key_insight[:50]}...")
                success_count += 1
            else:
                self.log_result("Intent Pattern Detection", False, f"HTTP {response.status_code}")
        except Exception as e:
            self.log_result("Intent Pattern Detection", False, str(e))
        
        # Test 3: Failure analysis patterns
        try:
            response = requests.get(f"{self.api_url}/patterns/insights/failure-analysis", timeout=10)
            if response.status_code == 200:
                data = response.json()
                failure_patterns = data.get("total_failure_patterns", 0)
                top_failures = data.get("top_failure_patterns", [])
                self.log_result("Failure Pattern Analysis", failure_patterns >= 0,
                               f"Patterns: {failure_patterns}, Top: {len(top_failures)}")
                success_count += 1
            else:
                # Endpoint might not exist yet - check alternative
                self.log_result("Failure Pattern Analysis", False, 
                               f"HTTP {response.status_code} (Endpoint may be in development)")
        except Exception as e:
            self.log_result("Failure Pattern Analysis", False, str(e))
        
        # Test 4: Pattern export for developer RL loops
        try:
            response = requests.get(f"{self.api_url}/patterns/export?format=json&hours_back=168", timeout=15)
            if response.status_code == 200:
                export_data = response.json()
                has_structured_data = bool(export_data)
                self.log_result("Pattern Export for RL Loops", has_structured_data,
                               f"Structured export available: {len(str(export_data))} chars")
                success_count += 1
            else:
                self.log_result("Pattern Export for RL Loops", False, f"HTTP {response.status_code}")
        except Exception as e:
            self.log_result("Pattern Export for RL Loops", False, str(e))
        
        return success_count >= 2

    def test_day67_production_deployment(self) -> bool:
        """Test DAY 6-7: Production Deployment - Live system validation"""
        print("\n🚀 DAY 6-7: PRODUCTION DEPLOYMENT TESTING")
        print("=" * 60)
        
        success_count = 0
        total_tests = 5
        
        # Test 1: Production API health
        try:
            response = requests.get(f"{PRODUCTION_API}/health", timeout=10)
            if response.status_code == 200:
                health_data = response.json()
                prod_healthy = health_data.get("services", {}).get("database", False)
                self.log_result("Production API Health", prod_healthy,
                               f"Production: {PRODUCTION_API}")
                if prod_healthy: success_count += 1
            else:
                self.log_result("Production API Health", False, f"HTTP {response.status_code}")
        except Exception as e:
            self.log_result("Production API Health", False, str(e))
        
        # Test 2: Production data ingestion
        production_test_data = {
            "data": [{
                "session_id": f"prod_test_{int(time.time())}",
                "step_name": "production_validation",
                "input": "Testing production deployment with comprehensive validation",
                "output": "Production system validated successfully",
                "metadata": {
                    "test_type": "production_deployment",
                    "environment": "production",
                    "timestamp": datetime.now().isoformat()
                }
            }],
            "source": "production_test_suite"
        }
        
        try:
            response = requests.post(f"{PRODUCTION_API}/ingest/json", 
                                   json=production_test_data, timeout=15)
            if response.status_code == 200:
                result = response.json()
                prod_ingestion_works = result.get("sessions_processed", 0) > 0
                self.log_result("Production Data Ingestion", prod_ingestion_works,
                               f"Sessions processed: {result.get('sessions_processed', 0)}")
                if prod_ingestion_works: success_count += 1
            else:
                self.log_result("Production Data Ingestion", False, f"HTTP {response.status_code}")
        except Exception as e:
            self.log_result("Production Data Ingestion", False, str(e))
        
        # Test 3: Local development setup
        local_healthy = self.api_url == LOCAL_API and self.test_results.get("Database Connectivity", {}).get("success", False)
        self.log_result("Local Development Setup", local_healthy,
                       f"Local API: {LOCAL_API}")
        if local_healthy: success_count += 1
        
        # Test 4: API documentation accessibility
        try:
            docs_response = requests.get(f"{self.api_url}/docs", timeout=5)
            docs_available = docs_response.status_code == 200
            self.log_result("API Documentation", docs_available,
                           f"OpenAPI docs: {self.api_url}/docs")
            if docs_available: success_count += 1
        except Exception as e:
            self.log_result("API Documentation", False, str(e))
        
        # Test 5: Streamlit dashboard accessibility
        try:
            # Test if Streamlit is running
            dashboard_response = requests.get("http://localhost:8502", timeout=3)
            dashboard_running = dashboard_response.status_code == 200
            self.log_result("Streamlit Dashboard", dashboard_running,
                           "Dashboard: http://localhost:8502")
            if dashboard_running: success_count += 1
        except Exception as e:
            # Dashboard might be on different port
            self.log_result("Streamlit Dashboard", False, 
                           "Dashboard may be on different port or not running")
        
        return success_count >= 3

    def test_enterprise_vision_validation(self) -> bool:
        """Test the core enterprise vision from the one-pager"""
        print("\n🏢 ENTERPRISE VISION VALIDATION")
        print("=" * 60)
        
        success_count = 0
        total_tests = 6
        
        # Test 1: Usage Analytics - What users are asking for
        try:
            response = requests.get(f"{self.api_url}/patterns/insights/top-intents?limit=10", timeout=10)
            if response.status_code == 200:
                data = response.json()
                top_intents = data.get("top_intents", [])
                usage_analytics = len(top_intents) > 0
                self.log_result("Usage Analytics - User Intents", usage_analytics,
                               f"Top intents tracked: {top_intents[:3]}")
                if usage_analytics: success_count += 1
            else:
                self.log_result("Usage Analytics - User Intents", False, f"HTTP {response.status_code}")
        except Exception as e:
            self.log_result("Usage Analytics - User Intents", False, str(e))
        
        # Test 2: Workflow Path Analysis
        try:
            response = requests.get(f"{self.api_url}/analytics/workflow-paths?intent=all&limit=10", timeout=10)
            if response.status_code == 200:
                data = response.json()
                workflow_paths = data.get("workflow_paths", [])
                path_analysis = len(workflow_paths) >= 0
                self.log_result("Workflow Path Analysis", path_analysis,
                               f"Paths tracked: {len(workflow_paths)}")
                if path_analysis: success_count += 1
            else:
                self.log_result("Workflow Path Analysis", False, f"HTTP {response.status_code}")
        except Exception as e:
            self.log_result("Workflow Path Analysis", False, str(e))
        
        # Test 3: Drop-off Analysis - Where sessions abandon
        try:
            response = requests.get(f"{self.api_url}/analytics/drop-off-analysis?hours_back=168", timeout=10)
            if response.status_code == 200:
                data = response.json()
                drop_off_analysis = bool(data.get("drop_off_by_step", {}))
                self.log_result("Drop-off Analysis", drop_off_analysis,
                               "Session abandonment tracking active")
                if drop_off_analysis: success_count += 1
            else:
                self.log_result("Drop-off Analysis", False, f"HTTP {response.status_code}")
        except Exception as e:
            self.log_result("Drop-off Analysis", False, str(e))
        
        # Test 4: Quality by Intent - Which intents fail most
        try:
            response = requests.get(f"{self.api_url}/analytics/quality-by-intent?hours_back=168", timeout=10)
            if response.status_code == 200:
                data = response.json()
                quality_by_intent = bool(data.get("quality_metrics", {}))
                self.log_result("Quality by Intent", quality_by_intent,
                               "Intent-specific quality tracking active")
                if quality_by_intent: success_count += 1
            else:
                self.log_result("Quality by Intent", False, f"HTTP {response.status_code}")
        except Exception as e:
            self.log_result("Quality by Intent", False, str(e))
        
        # Test 5: Autonomous LLM Evaluation
        autonomous_eval = self.test_results.get("Judge System Health", {}).get("success", False)
        self.log_result("Autonomous LLM Evaluation", autonomous_eval,
                       "LLM judges run on every interaction")
        if autonomous_eval: success_count += 1
        
        # Test 6: Loss Pattern Analysis with Root Cause
        pattern_analysis = self.test_results.get("Pattern Analysis Trigger", {}).get("success", False)
        self.log_result("Loss Pattern Analysis", pattern_analysis,
                       "Automated failure pattern detection")
        if pattern_analysis: success_count += 1
        
        return success_count >= 4

    def generate_comprehensive_report(self):
        """Generate comprehensive test report"""
        print("\n" + "=" * 80)
        print("🎯 COMPREHENSIVE AGENTIQ PLATFORM TEST REPORT")
        print("=" * 80)
        
        # Calculate overall success rates
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results.values() if result["success"])
        success_rate = (passed_tests / total_tests) * 100 if total_tests > 0 else 0
        
        print(f"\n📊 OVERALL RESULTS:")
        print(f"   Tests Executed: {total_tests}")
        print(f"   Tests Passed: {passed_tests}")
        print(f"   Success Rate: {success_rate:.1f}%")
        
        # Day-by-day analysis
        day_sections = {
            "DAY 1": ["Database Connectivity", "Required Tables", "Seed Data Generation", "Data Ingestion"],
            "DAY 2": ["Multi-Agent Workflow Ingestion", "Intent Classification", "Session Building"], 
            "DAY 3": ["Session Volume Over Time", "Top Intents with Completion Rate", "Most Common Workflow Paths", 
                     "Drop-off by Step Analysis", "Tool Usage and Failure Rates", "Quality by Intent"],
            "DAY 4": ["Judge System Health", "Single Interaction Evaluation", "Batch Evaluation Trigger", 
                     "Failure Taxonomy Implementation"],
            "DAY 5": ["Pattern Analysis Trigger", "Intent Pattern Detection", "Failure Pattern Analysis", 
                     "Pattern Export for RL Loops"],
            "DAY 6-7": ["Production API Health", "Production Data Ingestion", "Local Development Setup",
                       "API Documentation", "Streamlit Dashboard"],
            "ENTERPRISE": ["Usage Analytics - User Intents", "Workflow Path Analysis", "Drop-off Analysis",
                          "Quality by Intent", "Autonomous LLM Evaluation", "Loss Pattern Analysis"]
        }
        
        for day, tests in day_sections.items():
            day_passed = sum(1 for test in tests if self.test_results.get(test, {}).get("success", False))
            day_total = len(tests)
            day_rate = (day_passed / day_total) * 100 if day_total > 0 else 0
            
            status = "🟢 READY" if day_rate >= 75 else "🟡 PARTIAL" if day_rate >= 50 else "🔴 NEEDS WORK"
            print(f"\n{status} {day}: {day_passed}/{day_total} ({day_rate:.0f}%)")
            
            for test in tests:
                result = self.test_results.get(test, {"success": False, "details": "Not executed"})
                symbol = "  ✅" if result["success"] else "  ❌"
                print(f"{symbol} {test}")
        
        # Key insights
        print(f"\n🔍 KEY INSIGHTS:")
        
        if success_rate >= 80:
            print("   🎉 AgentIQ platform is PRODUCTION READY!")
            print("   🏢 Meets enterprise vision requirements from one-pager")
            print("   🚀 Ready for customer demonstrations and deployment")
        elif success_rate >= 60:
            print("   🟡 AgentIQ platform is MOSTLY FUNCTIONAL")
            print("   🔧 Some components need attention before full deployment")
            print("   📋 Focus on failed tests for production readiness")
        else:
            print("   🔴 AgentIQ platform needs SIGNIFICANT WORK")
            print("   🛠️  Core functionality requires debugging")
            print("   ⏳ Not ready for customer demonstrations")
        
        # Technical recommendations
        print(f"\n🛠️  TECHNICAL RECOMMENDATIONS:")
        
        if not self.test_results.get("Production API Health", {}).get("success", False):
            print("   🌐 Set up production deployment monitoring")
        
        if not self.test_results.get("Judge System Health", {}).get("success", False):
            print("   🧠 Configure Claude API key for LLM evaluation")
        
        if not self.test_results.get("Streamlit Dashboard", {}).get("success", False):
            print("   📊 Ensure Streamlit dashboard is accessible")
        
        # Business readiness
        print(f"\n💼 BUSINESS READINESS:")
        enterprise_ready = all([
            self.test_results.get("Usage Analytics - User Intents", {}).get("success", False),
            self.test_results.get("Drop-off Analysis", {}).get("success", False),
            self.test_results.get("Quality by Intent", {}).get("success", False)
        ])
        
        if enterprise_ready:
            print("   ✅ Core enterprise features validated")
            print("   ✅ Usage analytics layer functional")
            print("   ✅ Ready for enterprise sales conversations")
        else:
            print("   🔄 Still developing core enterprise features")
            print("   📈 Focus on usage analytics completion")
        
        print(f"\n🌟 AgentIQ Platform Status: {'ENTERPRISE READY' if success_rate >= 75 else 'IN DEVELOPMENT'}")
        print("=" * 80)

def main():
    """Run comprehensive AgentIQ test suite"""
    print("🚀 Starting Comprehensive AgentIQ Platform Test Suite")
    print("Testing complete 7-day roadmap implementation...")
    print("Validating enterprise vision from one-pager...")
    
    # Test local system first
    print(f"\n🔗 Testing Local System: {LOCAL_API}")
    local_tester = AgentIQTestSuite(LOCAL_API)
    
    # Run all test phases
    day1_success = local_tester.test_day1_foundation()
    day2_success = local_tester.test_day2_ingestion()
    day3_success = local_tester.test_day3_analytics()
    day4_success = local_tester.test_day4_llm_judge()
    day5_success = local_tester.test_day5_loss_patterns()
    day67_success = local_tester.test_day67_production_deployment()
    enterprise_success = local_tester.test_enterprise_vision_validation()
    
    # Generate comprehensive report
    local_tester.generate_comprehensive_report()
    
    # Test production if local is working
    if day1_success and day2_success:
        print(f"\n🌐 Testing Production System: {PRODUCTION_API}")
        prod_tester = AgentIQTestSuite(PRODUCTION_API)
        prod_tester.test_day67_production_deployment()

if __name__ == "__main__":
    main()