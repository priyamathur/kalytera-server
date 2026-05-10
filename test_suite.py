"""
Comprehensive Test Suite for AgentIQ
Validates all components work properly before deployment
"""

import pytest
import requests
import json
import os
import subprocess
import time
from datetime import datetime
import sys
from pathlib import Path

class AgentIQTestSuite:
    """Complete test suite for AgentIQ system validation"""
    
    def __init__(self, api_url="http://localhost:8000", dashboard_url="http://localhost:8501"):
        self.api_url = api_url
        self.dashboard_url = dashboard_url
        self.test_results = []
        
    def log_result(self, test_name: str, success: bool, message: str = "", critical: bool = False):
        """Log test result"""
        status = "✅" if success else "❌"
        priority = "CRITICAL" if critical else "INFO"
        print(f"{status} [{priority}] {test_name}: {message}")
        
        self.test_results.append({
            "test": test_name,
            "success": success,
            "message": message,
            "critical": critical,
            "timestamp": datetime.now().isoformat()
        })
        
        # Fail fast on critical errors
        if critical and not success:
            print(f"🛑 CRITICAL FAILURE: {test_name}")
            print("Stopping tests due to critical failure")
            return False
        return True

    def test_environment_setup(self):
        """Test environment variables and basic setup"""
        print("\n🔧 Testing Environment Setup...")
        
        # Test Python version
        python_version = sys.version_info
        if python_version.major >= 3 and python_version.minor >= 8:
            self.log_result("Python Version", True, f"Python {python_version.major}.{python_version.minor}")
        else:
            self.log_result("Python Version", False, f"Python {python_version.major}.{python_version.minor} - need 3.8+", critical=True)
            return False
            
        # Test virtual environment
        if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
            self.log_result("Virtual Environment", True, "Active")
        else:
            self.log_result("Virtual Environment", False, "Not detected", critical=True)
            return False
            
        # Test required directories
        required_dirs = ['api', 'db', 'dashboard', 'evaluation', 'patterns']
        for dir_name in required_dirs:
            dir_path = Path(dir_name)
            if dir_path.exists():
                self.log_result(f"Directory {dir_name}", True, "Exists")
            else:
                self.log_result(f"Directory {dir_name}", False, "Missing", critical=True)
                return False
                
        return True
        
    def test_database_initialization(self):
        """Test database schema and basic operations"""
        print("\n🗄️  Testing Database...")
        
        try:
            # Import database modules
            from db.models import AgentLog, SessionSummary, EvalResult, LossPattern
            from api.database import SessionLocal, engine
            
            self.log_result("Database Import", True, "All models imported")
            
            # Test database connection
            db = SessionLocal()
            
            # Test basic query
            count = db.query(AgentLog).count()
            self.log_result("Database Connection", True, f"{count} agent logs found")
            
            db.close()
            return True
            
        except Exception as e:
            self.log_result("Database Test", False, str(e), critical=True)
            return False
            
    def test_api_server(self):
        """Test API server availability and basic endpoints"""
        print("\n🚀 Testing API Server...")
        
        try:
            # Test basic connection
            response = requests.get(f"{self.api_url}/", timeout=10)
            if response.status_code == 200:
                self.log_result("API Root Endpoint", True, "Responding")
            else:
                self.log_result("API Root Endpoint", False, f"Status {response.status_code}", critical=True)
                return False
                
            # Test health endpoint
            response = requests.get(f"{self.api_url}/health", timeout=10)
            response.raise_for_status()
            health_data = response.json()
            
            self.log_result("API Health", True, f"Status: {health_data.get('status')}")
            
            # Test critical endpoints exist
            critical_endpoints = [
                "/docs",
                "/analytics/session-volume",
                "/patterns/health"
            ]
            
            for endpoint in critical_endpoints:
                try:
                    response = requests.get(f"{self.api_url}{endpoint}", timeout=5)
                    if response.status_code in [200, 422]:  # 422 is OK for missing params
                        self.log_result(f"Endpoint {endpoint}", True, f"Status {response.status_code}")
                    else:
                        self.log_result(f"Endpoint {endpoint}", False, f"Status {response.status_code}")
                except Exception as e:
                    self.log_result(f"Endpoint {endpoint}", False, str(e))
                    
            return True
            
        except Exception as e:
            self.log_result("API Server Test", False, str(e), critical=True)
            return False
            
    def test_data_ingestion(self):
        """Test data ingestion pipeline"""
        print("\n📥 Testing Data Ingestion...")
        
        try:
            # Test data payload
            test_data = {
                "data": [
                    {
                        "session_id": "test_suite_session",
                        "timestamp": datetime.now().isoformat() + "Z",
                        "user_input": "Test ingestion workflow",
                        "agent_response": "This is a test response for validation",
                        "intent": "testing",
                        "workflow_step": 1,
                        "response_time_ms": 500,
                        "tokens_used": 25
                    }
                ],
                "source": "test_suite",
                "format_hint": "json"
            }
            
            response = requests.post(
                f"{self.api_url}/ingest/json",
                json=test_data,
                timeout=15
            )
            response.raise_for_status()
            result = response.json()
            
            sessions_processed = result.get("sessions_processed", 0)
            interactions_processed = result.get("interactions_processed", 0)
            
            self.log_result("JSON Ingestion", True, f"{sessions_processed} sessions, {interactions_processed} interactions")
            return True
            
        except Exception as e:
            self.log_result("Data Ingestion", False, str(e))
            return False
            
    def test_analytics_system(self):
        """Test analytics endpoints and data processing"""
        print("\n📊 Testing Analytics System...")
        
        try:
            # Test analytics endpoints
            analytics_endpoints = [
                ("session-volume", "Session volume analytics"),
                ("intent-performance", "Intent performance analytics"),
                ("dashboard-summary", "Dashboard summary")
            ]
            
            for endpoint, description in analytics_endpoints:
                try:
                    response = requests.get(
                        f"{self.api_url}/analytics/{endpoint}?hours_back=24",
                        timeout=10
                    )
                    response.raise_for_status()
                    data = response.json()
                    
                    self.log_result(f"Analytics: {endpoint}", True, f"{len(data)} data points" if isinstance(data, list) else "Data available")
                    
                except Exception as e:
                    self.log_result(f"Analytics: {endpoint}", False, str(e))
                    
            return True
            
        except Exception as e:
            self.log_result("Analytics System", False, str(e))
            return False
            
    def test_evaluation_system(self):
        """Test evaluation system (with graceful API key handling)"""
        print("\n🧠 Testing Evaluation System...")
        
        try:
            # Test evaluation health (should work without API key)
            response = requests.get(f"{self.api_url}/evaluation/health", timeout=10)
            
            if response.status_code == 200:
                health_data = response.json()
                system_status = health_data.get("evaluation_system", "offline")
                self.log_result("Evaluation Health", True, f"System: {system_status}")
                
                # Test if API key is available
                api_key = health_data.get("anthropic_api", "not_configured")
                if api_key == "configured":
                    self.log_result("Anthropic API", True, "Configured")
                else:
                    self.log_result("Anthropic API", False, "Not configured - evaluation features limited")
                    
            else:
                self.log_result("Evaluation Health", False, f"Status {response.status_code}")
                
            return True
            
        except Exception as e:
            self.log_result("Evaluation System", False, str(e))
            return False
            
    def test_pattern_analysis(self):
        """Test pattern analysis system"""
        print("\n🔍 Testing Pattern Analysis...")
        
        try:
            # Test pattern health
            response = requests.get(f"{self.api_url}/patterns/health", timeout=10)
            response.raise_for_status()
            
            self.log_result("Pattern System Health", True, "Available")
            
            # Test pattern analysis endpoint
            response = requests.post(
                f"{self.api_url}/patterns/analyze",
                params={"hours_back": 24, "min_pattern_count": 1},
                timeout=15
            )
            
            if response.status_code == 200:
                result = response.json()
                patterns_found = result.get("patterns_detected", 0)
                self.log_result("Pattern Analysis", True, f"{patterns_found} patterns detected")
            else:
                self.log_result("Pattern Analysis", False, f"Status {response.status_code}")
                
            return True
            
        except Exception as e:
            self.log_result("Pattern Analysis", False, str(e))
            return False
            
    def test_dashboard_accessibility(self):
        """Test dashboard accessibility"""
        print("\n📱 Testing Dashboard...")
        
        try:
            # Test if dashboard is accessible
            response = requests.get(f"{self.dashboard_url}", timeout=10)
            
            if response.status_code == 200:
                self.log_result("Dashboard Access", True, "Accessible")
                
                # Check for Streamlit indicators in response
                content = response.text.lower()
                if "streamlit" in content or "agentiq" in content:
                    self.log_result("Dashboard Content", True, "AgentIQ dashboard detected")
                else:
                    self.log_result("Dashboard Content", False, "Unexpected content")
                    
            else:
                self.log_result("Dashboard Access", False, f"Status {response.status_code}")
                
            return True
            
        except Exception as e:
            self.log_result("Dashboard Test", False, str(e))
            return False
            
    def run_comprehensive_test_suite(self):
        """Run all tests in sequence"""
        print("🧪 AgentIQ Comprehensive Test Suite")
        print("=" * 60)
        print("Testing all system components for production readiness...")
        
        start_time = datetime.now()
        
        # Run tests in order of dependency
        test_methods = [
            self.test_environment_setup,
            self.test_database_initialization,
            self.test_api_server,
            self.test_data_ingestion,
            self.test_analytics_system,
            self.test_evaluation_system,
            self.test_pattern_analysis,
            self.test_dashboard_accessibility
        ]
        
        passed_tests = 0
        critical_failures = 0
        
        for test_method in test_methods:
            try:
                if test_method():
                    passed_tests += 1
                # Check for critical failures
                if any(not r["success"] and r["critical"] for r in self.test_results[-5:]):
                    critical_failures += 1
                    break
                    
            except Exception as e:
                print(f"❌ Test {test_method.__name__} failed with exception: {e}")
                critical_failures += 1
                break
                
            time.sleep(0.5)  # Brief pause between tests
            
        # Summary
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        total_tests = len(test_methods)
        
        print("\n" + "=" * 60)
        print("📋 Test Suite Summary")
        print(f"Tests passed: {passed_tests}/{total_tests}")
        print(f"Success rate: {passed_tests/total_tests:.1%}")
        print(f"Critical failures: {critical_failures}")
        print(f"Duration: {duration:.1f} seconds")
        
        # Detailed results
        print(f"\n📊 Detailed Results:")
        for result in self.test_results:
            status = "✅" if result["success"] else "❌"
            priority = "[CRITICAL]" if result.get("critical") else ""
            print(f"  {status} {priority} {result['test']}: {result['message']}")
            
        # Final verdict
        if critical_failures == 0 and passed_tests == total_tests:
            print("\n🎉 ALL TESTS PASSED! AgentIQ is ready for production deployment.")
            return True
        else:
            print(f"\n⚠️  TESTS FAILED! {critical_failures} critical failures, {total_tests - passed_tests} total failures.")
            print("System requires fixes before production deployment.")
            return False

def main():
    """Run the comprehensive test suite"""
    import sys
    
    api_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    dashboard_url = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8501"
    
    print(f"Testing AgentIQ API at: {api_url}")
    print(f"Testing AgentIQ Dashboard at: {dashboard_url}")
    
    test_suite = AgentIQTestSuite(api_url, dashboard_url)
    success = test_suite.run_comprehensive_test_suite()
    
    # Export detailed report
    with open("test_suite_report.json", "w") as f:
        json.dump({
            "test_run_timestamp": datetime.now().isoformat(),
            "api_url": api_url,
            "dashboard_url": dashboard_url,
            "overall_success": success,
            "test_results": test_suite.test_results
        }, f, indent=2)
    
    print(f"\n📄 Detailed report saved to: test_suite_report.json")
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()