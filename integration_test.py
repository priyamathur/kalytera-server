"""
Full integration test for deployed Kalytera system
Tests all major workflows: trace ingestion, evaluation, pattern analysis, dashboard APIs
"""

import requests
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any

class KalyteraIntegrationTest:
    def __init__(self, api_base_url: str, dashboard_url: str = None):
        self.api_base_url = api_base_url.rstrip('/')
        self.dashboard_url = dashboard_url
        self.test_session_id = str(uuid.uuid4())
        self.test_results = []
        
    def log_test(self, test_name: str, success: bool, message: str = "", data: Any = None):
        """Log test result"""
        result = {
            "test": test_name,
            "success": success,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "data": data
        }
        self.test_results.append(result)
        
        status = "✅" if success else "❌"
        print(f"{status} {test_name}: {message}")
        
    def test_api_health(self) -> bool:
        """Test basic API health and connectivity"""
        try:
            response = requests.get(f"{self.api_base_url}/health", timeout=10)
            
            if response.status_code == 200:
                health_data = response.json()
                self.log_test("API Health", True, f"API is healthy: {health_data.get('status')}")
                return True
            else:
                self.log_test("API Health", False, f"HTTP {response.status_code}")
                return False
                
        except Exception as e:
            self.log_test("API Health", False, f"Connection failed: {e}")
            return False
    
    def test_trace_ingestion(self) -> bool:
        """Test real-time trace ingestion"""
        try:
            # Send a test trace
            test_trace = {
                "session_id": self.test_session_id,
                "timestamp": datetime.now().isoformat(),
                "user_input": "I need help with my billing",
                "agent_response": "I'd be happy to help you with your billing question. Let me look up your account.",
                "response_time_ms": 1200,
                "workflow_step": 1,
                "tool_calls": '["billing_api", "account_lookup"]',
                "tokens_used": 45,
                "error_occurred": False
            }
            
            response = requests.post(
                f"{self.api_base_url}/api/trace",
                json=test_trace,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                self.log_test("Trace Ingestion", True, f"Trace accepted: {result.get('message')}")
                
                # Wait a moment for background processing
                time.sleep(2)
                return True
            else:
                self.log_test("Trace Ingestion", False, f"HTTP {response.status_code}: {response.text}")
                return False
                
        except Exception as e:
            self.log_test("Trace Ingestion", False, f"Request failed: {e}")
            return False
    
    def test_evaluation_system(self) -> bool:
        """Test evaluation system"""
        try:
            # Check evaluation health
            response = requests.get(f"{self.api_base_url}/evaluation/health", timeout=10)
            
            if response.status_code == 200:
                eval_health = response.json()
                system_status = eval_health.get("evaluation_system")
                
                if system_status == "online":
                    self.log_test("Evaluation System", True, "Evaluation system is online")
                    
                    # Test batch evaluation
                    eval_response = requests.post(
                        f"{self.api_base_url}/evaluation/evaluate-batch",
                        json={"hours_back": 0.1},  # Last 6 minutes
                        timeout=30
                    )
                    
                    if eval_response.status_code == 200:
                        eval_result = eval_response.json()
                        self.log_test("Batch Evaluation", True, f"Evaluated {eval_result.get('evaluations_completed', 0)} interactions")
                        return True
                    else:
                        self.log_test("Batch Evaluation", False, f"Evaluation failed: {eval_response.status_code}")
                        return False
                        
                else:
                    self.log_test("Evaluation System", False, f"System status: {system_status}")
                    return False
                    
        except Exception as e:
            self.log_test("Evaluation System", False, f"Test failed: {e}")
            return False
    
    def test_pattern_analysis(self) -> bool:
        """Test pattern analysis system"""
        try:
            # Check pattern system health
            response = requests.get(f"{self.api_base_url}/patterns/health", timeout=10)
            
            if response.status_code == 200:
                pattern_health = response.json()
                
                # Run pattern analysis
                analysis_response = requests.post(
                    f"{self.api_base_url}/patterns/analyze",
                    json={"hours_back": 24, "min_pattern_count": 2},
                    timeout=30
                )
                
                if analysis_response.status_code == 200:
                    analysis_result = analysis_response.json()
                    patterns_found = analysis_result.get("patterns_detected", 0)
                    self.log_test("Pattern Analysis", True, f"Found {patterns_found} patterns")
                    return True
                else:
                    self.log_test("Pattern Analysis", False, f"Analysis failed: {analysis_response.status_code}")
                    return False
                    
        except Exception as e:
            self.log_test("Pattern Analysis", False, f"Test failed: {e}")
            return False
    
    def test_analytics_endpoints(self) -> bool:
        """Test analytics endpoints"""
        analytics_endpoints = [
            "/analytics/dashboard-summary",
            "/analytics/session-volume", 
            "/analytics/intent-performance",
            "/analytics/quality-by-intent",
            "/analytics/dropoff-analysis"
        ]
        
        success_count = 0
        
        for endpoint in analytics_endpoints:
            try:
                response = requests.get(f"{self.api_base_url}{endpoint}", timeout=15)
                
                if response.status_code == 200:
                    data = response.json()
                    self.log_test(f"Analytics {endpoint.split('/')[-1]}", True, "Data retrieved successfully")
                    success_count += 1
                else:
                    self.log_test(f"Analytics {endpoint.split('/')[-1]}", False, f"HTTP {response.status_code}")
                    
            except Exception as e:
                self.log_test(f"Analytics {endpoint.split('/')[-1]}", False, f"Request failed: {e}")
        
        overall_success = success_count == len(analytics_endpoints)
        self.log_test("Analytics Endpoints", overall_success, f"{success_count}/{len(analytics_endpoints)} endpoints working")
        return overall_success
    
    def test_pattern_exports(self) -> bool:
        """Test pattern export functionality"""
        try:
            # Test developer export
            dev_response = requests.get(
                f"{self.api_base_url}/patterns/export/developer",
                params={"hours_back": 24},
                timeout=15
            )
            
            # Test insights endpoint
            insights_response = requests.get(
                f"{self.api_base_url}/patterns/insights/top-intents",
                timeout=15
            )
            
            if dev_response.status_code == 200 and insights_response.status_code == 200:
                dev_data = dev_response.json()
                insights_data = insights_response.json()
                
                patterns_count = len(dev_data.get("patterns", []))
                key_insight = insights_data.get("key_insight", "")
                
                self.log_test("Pattern Exports", True, f"Exported {patterns_count} patterns. Key insight: {key_insight}")
                return True
            else:
                self.log_test("Pattern Exports", False, f"Export failed: {dev_response.status_code}, {insights_response.status_code}")
                return False
                
        except Exception as e:
            self.log_test("Pattern Exports", False, f"Test failed: {e}")
            return False
    
    def test_dashboard_connectivity(self) -> bool:
        """Test dashboard connectivity if URL provided"""
        if not self.dashboard_url:
            self.log_test("Dashboard Connectivity", True, "Dashboard URL not provided - skipping")
            return True
            
        try:
            response = requests.get(self.dashboard_url, timeout=10)
            
            if response.status_code == 200:
                self.log_test("Dashboard Connectivity", True, "Dashboard is accessible")
                return True
            else:
                self.log_test("Dashboard Connectivity", False, f"HTTP {response.status_code}")
                return False
                
        except Exception as e:
            self.log_test("Dashboard Connectivity", False, f"Connection failed: {e}")
            return False
    
    def test_end_to_end_workflow(self) -> bool:
        """Test complete end-to-end workflow"""
        try:
            print("\n🔄 Testing end-to-end workflow...")
            
            # Step 1: Send multiple traces for a session
            session_id = str(uuid.uuid4())
            
            interactions = [
                {
                    "session_id": session_id,
                    "timestamp": datetime.now().isoformat(),
                    "user_input": "I want to cancel my subscription",
                    "agent_response": "I can help you cancel your subscription. Let me pull up your account details.",
                    "response_time_ms": 1000,
                    "workflow_step": 1,
                    "tool_calls": '["subscription_api"]',
                    "tokens_used": 35,
                    "error_occurred": False
                },
                {
                    "session_id": session_id, 
                    "timestamp": (datetime.now() + timedelta(seconds=30)).isoformat(),
                    "user_input": "Yes, please cancel it immediately",
                    "agent_response": "I've successfully cancelled your subscription. You'll retain access until your billing period ends.",
                    "response_time_ms": 800,
                    "workflow_step": 2,
                    "tool_calls": '["billing_api", "cancellation_api"]',
                    "tokens_used": 42,
                    "error_occurred": False
                }
            ]
            
            # Send traces
            for interaction in interactions:
                response = requests.post(
                    f"{self.api_base_url}/api/trace",
                    json=interaction,
                    timeout=10
                )
                
                if response.status_code != 200:
                    self.log_test("End-to-End Workflow", False, f"Trace failed: {response.status_code}")
                    return False
            
            # Step 2: Wait for processing
            time.sleep(3)
            
            # Step 3: Trigger evaluation
            eval_response = requests.post(
                f"{self.api_base_url}/evaluation/evaluate-batch",
                json={"hours_back": 0.1},
                timeout=30
            )
            
            if eval_response.status_code != 200:
                self.log_test("End-to-End Workflow", False, f"Evaluation failed: {eval_response.status_code}")
                return False
            
            # Step 4: Check session appears in analytics
            time.sleep(2)
            
            summary_response = requests.get(f"{self.api_base_url}/analytics/dashboard-summary", timeout=15)
            
            if summary_response.status_code == 200:
                summary_data = summary_response.json()
                session_count = summary_data.get("total_sessions", 0)
                
                self.log_test("End-to-End Workflow", True, f"Workflow complete. Total sessions: {session_count}")
                return True
            else:
                self.log_test("End-to-End Workflow", False, f"Analytics failed: {summary_response.status_code}")
                return False
                
        except Exception as e:
            self.log_test("End-to-End Workflow", False, f"Test failed: {e}")
            return False
    
    def run_all_tests(self) -> Dict[str, Any]:
        """Run complete integration test suite"""
        
        print("🧪 Kalytera Integration Test Suite")
        print("=" * 50)
        print(f"🎯 API: {self.api_base_url}")
        if self.dashboard_url:
            print(f"🎯 Dashboard: {self.dashboard_url}")
        print()
        
        # Run all tests
        tests = [
            ("API Health", self.test_api_health),
            ("Trace Ingestion", self.test_trace_ingestion),
            ("Evaluation System", self.test_evaluation_system),
            ("Pattern Analysis", self.test_pattern_analysis),
            ("Analytics Endpoints", self.test_analytics_endpoints),
            ("Pattern Exports", self.test_pattern_exports),
            ("Dashboard Connectivity", self.test_dashboard_connectivity),
            ("End-to-End Workflow", self.test_end_to_end_workflow)
        ]
        
        passed_tests = 0
        total_tests = len(tests)
        
        for test_name, test_func in tests:
            print(f"\n🧪 Running {test_name}...")
            try:
                success = test_func()
                if success:
                    passed_tests += 1
            except Exception as e:
                self.log_test(test_name, False, f"Test crashed: {e}")
        
        # Results summary
        print("\n📊 Integration Test Results")
        print("=" * 50)
        print(f"✅ Passed: {passed_tests}/{total_tests} tests")
        print(f"❌ Failed: {total_tests - passed_tests}/{total_tests} tests")
        
        success_rate = (passed_tests / total_tests) * 100
        print(f"📈 Success Rate: {success_rate:.1f}%")
        
        # Detailed results
        print("\n📋 Detailed Results:")
        for result in self.test_results:
            status = "✅" if result["success"] else "❌"
            print(f"{status} {result['test']}: {result['message']}")
        
        # Overall assessment
        if success_rate >= 90:
            print("\n🎉 System is ready for production!")
        elif success_rate >= 75:
            print("\n⚠️  System is mostly functional but has some issues")
        else:
            print("\n❌ System has significant issues and needs debugging")
        
        return {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "success_rate": success_rate,
            "results": self.test_results,
            "ready_for_production": success_rate >= 90
        }

def main():
    """Main function to run integration tests"""
    import os
    import sys
    
    # Get URLs from command line or environment
    api_url = os.getenv("API_BASE_URL", "http://localhost:8000")
    dashboard_url = os.getenv("DASHBOARD_URL")
    
    if len(sys.argv) > 1:
        api_url = sys.argv[1]
    if len(sys.argv) > 2:
        dashboard_url = sys.argv[2]
    
    # Run tests
    tester = KalyteraIntegrationTest(api_url, dashboard_url)
    results = tester.run_all_tests()
    
    # Exit with appropriate code
    if results["ready_for_production"]:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()