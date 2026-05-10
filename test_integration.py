"""
AgentIQ Full Integration Test Suite
Tests complete pipeline: ingestion → evaluation → pattern analysis → export
"""

import requests
import json
import time
from datetime import datetime
import sys

class AgentIQIntegrationTest:
    """Full integration test for AgentIQ platform"""
    
    def __init__(self, api_base_url="http://localhost:8000"):
        self.api_base_url = api_base_url
        self.test_results = []
    
    def log_test(self, test_name: str, success: bool, message: str = ""):
        """Log test result"""
        status = "✅" if success else "❌"
        print(f"{status} {test_name}: {message}")
        self.test_results.append({
            "test": test_name,
            "success": success,
            "message": message,
            "timestamp": datetime.now().isoformat()
        })
    
    def test_api_health(self):
        """Test API health endpoints"""
        try:
            response = requests.get(f"{self.api_base_url}/health", timeout=10)
            response.raise_for_status()
            
            data = response.json()
            services_healthy = data.get("services", {})
            
            self.log_test("API Health Check", True, f"API online with {len(services_healthy)} services")
            return True
            
        except Exception as e:
            self.log_test("API Health Check", False, str(e))
            return False
    
    def test_data_ingestion(self):
        """Test JSON and CSV ingestion endpoints"""
        
        # Test JSON ingestion
        sample_json_data = [
            {
                "session_id": "test_integration_001",
                "timestamp": "2024-01-15T10:00:00Z",
                "user_input": "I need help with billing",
                "agent_response": "I can help you with your billing question. Let me look up your account.",
                "intent": "billing",
                "workflow_step": 1,
                "response_time_ms": 1200,
                "tokens_used": 45
            },
            {
                "session_id": "test_integration_001",
                "timestamp": "2024-01-15T10:01:00Z", 
                "user_input": "There's a charge I don't recognize",
                "agent_response": "I'm unable to access the billing system right now due to a technical issue.",
                "intent": "billing",
                "workflow_step": 2,
                "response_time_ms": 800,
                "tokens_used": 32,
                "tool_calls": "Error: billing_api timeout"
            }
        ]
        
        try:
            response = requests.post(
                f"{self.api_base_url}/ingest/json",
                json={
                    "data": sample_json_data,
                    "source": "integration_test",
                    "format_hint": "json"
                },
                timeout=15
            )
            response.raise_for_status()
            
            result = response.json()
            sessions_processed = result.get("sessions_processed", 0)
            interactions_processed = result.get("interactions_processed", 0)
            
            self.log_test("JSON Ingestion", True, f"{sessions_processed} sessions, {interactions_processed} interactions")
            return True
            
        except Exception as e:
            self.log_test("JSON Ingestion", False, str(e))
            return False
    
    def test_analytics_endpoints(self):
        """Test analytics API endpoints"""
        
        endpoints = [
            "/analytics/session-volume?hours_back=24",
            "/analytics/top-intents?hours_back=24",
            "/analytics/workflow-dropoff?hours_back=24",
            "/analytics/tool-usage?hours_back=24"
        ]
        
        success_count = 0
        
        for endpoint in endpoints:
            try:
                response = requests.get(f"{self.api_base_url}{endpoint}", timeout=10)
                response.raise_for_status()
                
                data = response.json()
                success_count += 1
                
            except Exception as e:
                self.log_test(f"Analytics {endpoint}", False, str(e))
        
        total_tests = len(endpoints)
        self.log_test("Analytics Endpoints", success_count == total_tests, 
                     f"{success_count}/{total_tests} endpoints working")
        
        return success_count == total_tests
    
    def test_evaluation_system(self):
        """Test LLM evaluation system"""
        
        # Test evaluation health
        try:
            response = requests.get(f"{self.api_base_url}/evaluation/health", timeout=10)
            response.raise_for_status()
            
            health_data = response.json()
            system_status = health_data.get("evaluation_system", "offline")
            
            if system_status == "online":
                # Test batch evaluation
                eval_response = requests.post(
                    f"{self.api_base_url}/evaluation/evaluate-batch",
                    params={"hours_back": 0.5},
                    timeout=30
                )
                eval_response.raise_for_status()
                
                eval_result = eval_response.json()
                evaluations_completed = eval_result.get("evaluations_completed", 0)
                
                self.log_test("Evaluation System", True, 
                             f"System online, {evaluations_completed} evaluations completed")
            else:
                self.log_test("Evaluation System", False, "Claude API not available")
            
            return True
            
        except Exception as e:
            self.log_test("Evaluation System", False, str(e))
            return False
    
    def test_pattern_analysis(self):
        """Test pattern analysis and export"""
        
        try:
            # Test pattern analysis
            response = requests.post(
                f"{self.api_base_url}/patterns/analyze",
                params={"hours_back": 24, "min_pattern_count": 1},
                timeout=20
            )
            response.raise_for_status()
            
            analysis_data = response.json()
            patterns_detected = analysis_data.get("patterns_detected", 0)
            total_failures = analysis_data.get("total_failures", 0)
            
            # Test export endpoints
            export_response = requests.get(
                f"{self.api_base_url}/patterns/export/developer",
                params={"hours_back": 24, "min_impact": 0},
                timeout=15
            )
            export_response.raise_for_status()
            
            export_data = export_response.json()
            exportable_patterns = len(export_data.get("patterns", []))
            
            self.log_test("Pattern Analysis", True, 
                         f"{patterns_detected} patterns from {total_failures} failures, {exportable_patterns} exportable")
            return True
            
        except Exception as e:
            self.log_test("Pattern Analysis", False, str(e))
            return False
    
    def test_export_formats(self):
        """Test different export formats for developer RL loops"""
        
        formats_to_test = [
            ("developer", "Developer format"),
            ("reinforcement_learning", "RL format")
        ]
        
        success_count = 0
        
        for format_type, description in formats_to_test:
            try:
                if format_type == "reinforcement_learning":
                    # Test RL export format
                    response = requests.get(
                        f"{self.api_base_url}/patterns/export/developer",
                        params={
                            "format": "reinforcement_learning",
                            "hours_back": 24,
                            "min_impact": 0
                        },
                        timeout=15
                    )
                else:
                    # Test developer export format
                    response = requests.get(
                        f"{self.api_base_url}/patterns/export/developer",
                        params={"hours_back": 24, "min_impact": 0},
                        timeout=15
                    )
                
                response.raise_for_status()
                data = response.json()
                
                # Validate export structure
                if format_type == "reinforcement_learning":
                    required_fields = ["training_data", "policy_improvement", "reward_function"]
                    has_required = all(field in data for field in required_fields)
                    
                    if has_required:
                        training_examples = len(data.get("training_data", {}).get("negative_examples", []))
                        self.log_test(f"Export {description}", True, f"{training_examples} training examples")
                        success_count += 1
                    else:
                        self.log_test(f"Export {description}", False, "Missing required fields")
                else:
                    patterns = len(data.get("patterns", []))
                    self.log_test(f"Export {description}", True, f"{patterns} patterns exported")
                    success_count += 1
                
            except Exception as e:
                self.log_test(f"Export {description}", False, str(e))
        
        return success_count == len(formats_to_test)
    
    def test_key_insights(self):
        """Test key insights endpoint"""
        
        try:
            response = requests.get(
                f"{self.api_base_url}/patterns/insights/top-intents",
                params={"limit": 5},
                timeout=10
            )
            response.raise_for_status()
            
            insights_data = response.json()
            key_insight = insights_data.get("key_insight", "")
            top_intents = insights_data.get("top_intents", [])
            
            # Validate insight structure
            has_insight = bool(key_insight)
            has_intents = len(top_intents) > 0
            
            if has_insight and has_intents:
                self.log_test("Key Insights", True, 
                             f"Insight: '{key_insight[:50]}...' with {len(top_intents)} intents")
            else:
                self.log_test("Key Insights", True, "No insights available (insufficient data)")
            
            return True
            
        except Exception as e:
            self.log_test("Key Insights", False, str(e))
            return False
    
    def run_full_integration_test(self):
        """Run complete integration test suite"""
        
        print("🚀 Starting AgentIQ Full Integration Test")
        print("=" * 60)
        
        start_time = datetime.now()
        
        # Run all tests
        test_methods = [
            self.test_api_health,
            self.test_data_ingestion,
            self.test_analytics_endpoints,
            self.test_evaluation_system,
            self.test_pattern_analysis,
            self.test_export_formats,
            self.test_key_insights
        ]
        
        total_tests = len(test_methods)
        successful_tests = 0
        
        for test_method in test_methods:
            try:
                if test_method():
                    successful_tests += 1
                time.sleep(1)  # Brief pause between tests
                
            except Exception as e:
                print(f"❌ Test {test_method.__name__} failed with exception: {e}")
        
        # Summary
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print("\n" + "=" * 60)
        print("🎯 Integration Test Summary")
        print(f"Tests passed: {successful_tests}/{total_tests}")
        print(f"Success rate: {successful_tests/total_tests:.1%}")
        print(f"Duration: {duration:.1f} seconds")
        
        if successful_tests == total_tests:
            print("🎉 All integration tests passed! AgentIQ is ready for deployment.")
            return True
        else:
            print("⚠️ Some tests failed. Check the issues above before deployment.")
            return False
    
    def export_test_report(self, filename: str = "integration_test_report.json"):
        """Export detailed test report"""
        
        report = {
            "test_run_timestamp": datetime.now().isoformat(),
            "api_base_url": self.api_base_url,
            "total_tests": len(self.test_results),
            "successful_tests": sum(1 for t in self.test_results if t["success"]),
            "failed_tests": sum(1 for t in self.test_results if not t["success"]),
            "test_results": self.test_results
        }
        
        with open(filename, "w") as f:
            json.dump(report, f, indent=2)
        
        print(f"📊 Test report exported to {filename}")

def main():
    """Run integration tests"""
    
    # Check if API URL is provided
    api_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    
    print(f"Testing AgentIQ at: {api_url}")
    
    # Run tests
    test_suite = AgentIQIntegrationTest(api_url)
    success = test_suite.run_full_integration_test()
    
    # Export report
    test_suite.export_test_report()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()