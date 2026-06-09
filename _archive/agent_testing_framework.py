"""
AgentIQ Testing Framework - Production-Ready Agent Testing & Evaluation
Autonomous testing and performance validation for any AI agent

Usage:
```python
from agent_testing_framework import AgentTester

# Test any agent
tester = AgentTester(agent_id="my-coding-agent")

# Run comprehensive test suite
results = tester.run_full_test_suite()

# Get performance report
report = tester.generate_performance_report()
```
"""

import time
from datetime import datetime
from typing import Dict, List, Any, Callable, Optional
from dataclasses import dataclass
from agentiq_sdk import AgentIQ

@dataclass
class TestCase:
    """Test case for agent validation"""
    name: str
    user_input: str
    expected_keywords: List[str]
    expected_response_time: int  # milliseconds
    intent: str
    difficulty: str  # easy, medium, hard
    metadata: Dict[str, Any]

@dataclass
class TestResult:
    """Result of a single test case"""
    test_name: str
    passed: bool
    response: str
    response_time: int
    quality_score: float
    issues: List[str]
    recommendations: List[str]

class AgentTester:
    """Autonomous agent testing and evaluation framework"""
    
    def __init__(self, agent_id: str, agent_function: Optional[Callable] = None):
        """
        Initialize agent tester
        
        Args:
            agent_id: Unique identifier for the agent being tested
            agent_function: Function that takes user_input and returns agent_response
        """
        self.agent_id = agent_id
        self.agent_function = agent_function
        self.agentiq = AgentIQ(agent_id=f"test-{agent_id}")
        self.test_session_id = None
        
        # Test suites for different agent types
        self.test_suites = {
            "coding": self._get_coding_test_cases(),
            "customer_service": self._get_customer_service_test_cases(),
            "data_science": self._get_data_science_test_cases(),
            "sales": self._get_sales_test_cases(),
            "general": self._get_general_test_cases()
        }
    
    def register_agent(self, agent_function: Callable[[str], str]):
        """Register the agent function to test"""
        self.agent_function = agent_function
        return self
    
    def run_single_test(self, test_case: TestCase) -> TestResult:
        """Run a single test case against the agent"""
        start_time = time.time()
        
        try:
            # Call agent function
            if not self.agent_function:
                raise ValueError("No agent function registered. Use register_agent() first.")
            
            response = self.agent_function(test_case.user_input)
            response_time = int((time.time() - start_time) * 1000)
            
            # Track with AgentIQ
            self.agentiq.track(
                user_input=test_case.user_input,
                agent_response=response,
                metadata={
                    "test_case": test_case.name,
                    "intent": test_case.intent,
                    "response_time": response_time,
                    "expected_keywords": test_case.expected_keywords
                },
                session_id=self.test_session_id
            )
            
            # Evaluate response
            passed = self._evaluate_response(response, test_case)
            quality_score = self._calculate_quality_score(response, test_case)
            issues = self._identify_issues(response, test_case, response_time)
            recommendations = self._generate_recommendations(issues, test_case)
            
            return TestResult(
                test_name=test_case.name,
                passed=passed,
                response=response,
                response_time=response_time,
                quality_score=quality_score,
                issues=issues,
                recommendations=recommendations
            )
            
        except Exception as e:
            return TestResult(
                test_name=test_case.name,
                passed=False,
                response=f"ERROR: {str(e)}",
                response_time=int((time.time() - start_time) * 1000),
                quality_score=0.0,
                issues=[f"Agent execution failed: {str(e)}"],
                recommendations=["Fix agent implementation errors"]
            )
    
    def run_test_suite(self, suite_name: str) -> Dict[str, Any]:
        """Run a complete test suite"""
        if suite_name not in self.test_suites:
            raise ValueError(f"Unknown test suite: {suite_name}. Available: {list(self.test_suites.keys())}")
        
        # Start test session
        self.test_session_id = self.agentiq.start_session()
        
        test_cases = self.test_suites[suite_name]
        results = []
        
        print(f"🧪 Running {suite_name} test suite ({len(test_cases)} tests)...")
        
        for i, test_case in enumerate(test_cases, 1):
            print(f"  Test {i}/{len(test_cases)}: {test_case.name}...")
            result = self.run_single_test(test_case)
            results.append(result)
            
            status = "✅ PASS" if result.passed else "❌ FAIL"
            print(f"    {status} ({result.response_time}ms, quality: {result.quality_score:.2f})")
        
        # End test session
        session_summary = self.agentiq.end_session("test_completed")
        
        # Calculate suite metrics
        suite_results = self._calculate_suite_metrics(results, suite_name)
        suite_results["session_summary"] = session_summary
        suite_results["individual_results"] = results
        
        return suite_results
    
    def run_full_test_suite(self) -> Dict[str, Any]:
        """Run all test suites and generate comprehensive report"""
        print(f"🚀 Running full test suite for agent: {self.agent_id}")
        
        all_results = {}
        overall_metrics = {
            "total_tests": 0,
            "total_passed": 0,
            "average_quality": 0.0,
            "average_response_time": 0.0,
            "critical_issues": [],
            "recommendations": []
        }
        
        # Run each test suite
        for suite_name in self.test_suites.keys():
            suite_results = self.run_test_suite(suite_name)
            all_results[suite_name] = suite_results
            
            # Aggregate metrics
            overall_metrics["total_tests"] += suite_results["total_tests"]
            overall_metrics["total_passed"] += suite_results["passed_tests"]
        
        # Calculate overall averages
        if overall_metrics["total_tests"] > 0:
            overall_metrics["pass_rate"] = overall_metrics["total_passed"] / overall_metrics["total_tests"]
            
            # Collect all individual results for averaging
            all_individual_results = []
            for suite_results in all_results.values():
                all_individual_results.extend(suite_results["individual_results"])
            
            overall_metrics["average_quality"] = sum(r.quality_score for r in all_individual_results) / len(all_individual_results)
            overall_metrics["average_response_time"] = sum(r.response_time for r in all_individual_results) / len(all_individual_results)
        
        # Generate comprehensive recommendations
        overall_metrics["recommendations"] = self._generate_overall_recommendations(all_results)
        
        return {
            "agent_id": self.agent_id,
            "timestamp": datetime.now().isoformat(),
            "overall_metrics": overall_metrics,
            "suite_results": all_results,
            "agentiq_insights": self.agentiq.get_insights()
        }
    
    def generate_performance_report(self, results: Optional[Dict] = None) -> str:
        """Generate a detailed performance report"""
        if not results:
            results = self.run_full_test_suite()
        
        metrics = results["overall_metrics"]
        
        report = f"""
🏆 AGENT PERFORMANCE REPORT
Agent ID: {self.agent_id}
Generated: {results["timestamp"]}

📊 OVERALL PERFORMANCE
• Tests Run: {metrics["total_tests"]}
• Pass Rate: {metrics.get("pass_rate", 0):.1%} ({metrics["total_passed"]}/{metrics["total_tests"]})
• Average Quality: {metrics["average_quality"]:.2f}/1.0
• Average Response Time: {metrics["average_response_time"]:.0f}ms

📈 SUITE BREAKDOWN
"""
        
        # Add suite details
        for suite_name, suite_data in results["suite_results"].items():
            report += f"""
{suite_name.upper()}:
  Pass Rate: {suite_data["pass_rate"]:.1%} ({suite_data["passed_tests"]}/{suite_data["total_tests"]})
  Avg Quality: {suite_data["average_quality"]:.2f}
  Avg Response Time: {suite_data["average_response_time"]:.0f}ms
"""
        
        # Add recommendations
        if metrics["recommendations"]:
            report += "\n🎯 RECOMMENDATIONS\n"
            for i, rec in enumerate(metrics["recommendations"], 1):
                report += f"{i}. {rec}\n"
        
        # Performance grade
        pass_rate = metrics.get("pass_rate", 0)
        if pass_rate >= 0.9:
            grade = "A+"
        elif pass_rate >= 0.8:
            grade = "A"
        elif pass_rate >= 0.7:
            grade = "B"
        elif pass_rate >= 0.6:
            grade = "C"
        else:
            grade = "F"
        
        report += f"\n🎓 OVERALL GRADE: {grade}\n"
        
        return report
    
    def continuous_monitoring(self, interval_minutes: int = 60):
        """Start continuous agent monitoring"""
        print(f"🔄 Starting continuous monitoring for {self.agent_id} (every {interval_minutes} minutes)")
        
        while True:
            try:
                # Run quick health check test
                health_results = self.run_test_suite("general")
                
                # Check for issues
                if health_results["pass_rate"] < 0.8:
                    print(f"⚠️ ALERT: Agent performance degraded - {health_results['pass_rate']:.1%} pass rate")
                
                # Wait for next check
                time.sleep(interval_minutes * 60)
                
            except KeyboardInterrupt:
                print("🛑 Continuous monitoring stopped")
                break
            except Exception as e:
                print(f"❌ Monitoring error: {e}")
                time.sleep(300)  # Wait 5 minutes on error
    
    def _evaluate_response(self, response: str, test_case: TestCase) -> bool:
        """Evaluate if response meets test case criteria"""
        response_lower = response.lower()
        
        # Check for expected keywords
        keywords_found = sum(1 for keyword in test_case.expected_keywords 
                           if keyword.lower() in response_lower)
        keyword_score = keywords_found / max(len(test_case.expected_keywords), 1)
        
        # Response quality checks
        quality_checks = [
            len(response) > 20,  # Minimum response length
            not response.startswith("I don't know"),  # Not a cop-out response
            not response.startswith("Sorry, I can't"),  # Not immediately giving up
        ]
        
        quality_score = sum(quality_checks) / len(quality_checks)
        
        # Overall pass criteria
        return keyword_score >= 0.5 and quality_score >= 0.7
    
    def _calculate_quality_score(self, response: str, test_case: TestCase) -> float:
        """Calculate quality score for response"""
        scores = []
        
        # Keyword relevance (0-1)
        keywords_found = sum(1 for keyword in test_case.expected_keywords 
                           if keyword.lower() in response.lower())
        keyword_score = keywords_found / max(len(test_case.expected_keywords), 1)
        scores.append(keyword_score)
        
        # Response completeness (0-1)
        completeness_score = min(len(response) / 100, 1.0)  # Normalize by 100 chars
        scores.append(completeness_score)
        
        # Response relevance (simple heuristic)
        relevance_score = 0.8 if len(response) > 50 else 0.5
        scores.append(relevance_score)
        
        return sum(scores) / len(scores)
    
    def _identify_issues(self, response: str, test_case: TestCase, response_time: int) -> List[str]:
        """Identify issues with the response"""
        issues = []
        
        if response_time > test_case.expected_response_time:
            issues.append(f"Slow response time: {response_time}ms (expected: <{test_case.expected_response_time}ms)")
        
        if len(response) < 20:
            issues.append("Response too short")
        
        if response.startswith("I don't know") or response.startswith("Sorry, I can't"):
            issues.append("Agent giving up too quickly")
        
        # Check for expected keywords
        missing_keywords = [kw for kw in test_case.expected_keywords 
                          if kw.lower() not in response.lower()]
        if missing_keywords:
            issues.append(f"Missing expected keywords: {', '.join(missing_keywords)}")
        
        return issues
    
    def _generate_recommendations(self, issues: List[str], test_case: TestCase) -> List[str]:
        """Generate recommendations based on issues"""
        recommendations = []
        
        for issue in issues:
            if "slow response" in issue.lower():
                recommendations.append("Optimize agent processing speed")
            elif "too short" in issue.lower():
                recommendations.append("Improve response completeness")
            elif "giving up" in issue.lower():
                recommendations.append("Enhance agent persistence and problem-solving")
            elif "missing keywords" in issue.lower():
                recommendations.append(f"Improve understanding of {test_case.intent} queries")
        
        return recommendations
    
    def _calculate_suite_metrics(self, results: List[TestResult], suite_name: str) -> Dict:
        """Calculate metrics for test suite"""
        total_tests = len(results)
        passed_tests = sum(1 for r in results if r.passed)
        
        return {
            "suite_name": suite_name,
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "failed_tests": total_tests - passed_tests,
            "pass_rate": passed_tests / total_tests if total_tests > 0 else 0,
            "average_quality": sum(r.quality_score for r in results) / total_tests if total_tests > 0 else 0,
            "average_response_time": sum(r.response_time for r in results) / total_tests if total_tests > 0 else 0,
        }
    
    def _generate_overall_recommendations(self, all_results: Dict) -> List[str]:
        """Generate overall recommendations across all test suites"""
        recommendations = []
        
        # Analyze performance across suites
        worst_suite = None
        worst_pass_rate = 1.0
        
        for suite_name, suite_data in all_results.items():
            if suite_data["pass_rate"] < worst_pass_rate:
                worst_pass_rate = suite_data["pass_rate"]
                worst_suite = suite_name
        
        if worst_pass_rate < 0.7:
            recommendations.append(f"🔴 PRIORITY: Focus on improving {worst_suite} performance ({worst_pass_rate:.1%} pass rate)")
        
        # Response time analysis
        slow_suites = [name for name, data in all_results.items() if data["average_response_time"] > 3000]
        if slow_suites:
            recommendations.append(f"⚡ Optimize response times for: {', '.join(slow_suites)}")
        
        # Quality analysis
        low_quality_suites = [name for name, data in all_results.items() if data["average_quality"] < 0.6]
        if low_quality_suites:
            recommendations.append(f"📈 Improve response quality for: {', '.join(low_quality_suites)}")
        
        if not recommendations:
            recommendations.append("✅ Agent performing well across all test suites")
        
        return recommendations
    
    # Test case definitions for different agent types
    def _get_coding_test_cases(self) -> List[TestCase]:
        return [
            TestCase("debug_python_error", "Fix this Python error: NameError: name 'x' is not defined", 
                    ["variable", "defined", "x"], 2000, "debugging", "easy", {}),
            TestCase("write_function", "Write a function that reverses a string", 
                    ["def", "reverse", "return"], 3000, "code_generation", "medium", {}),
            TestCase("optimize_code", "Optimize this slow sorting algorithm", 
                    ["algorithm", "efficient", "time", "complexity"], 4000, "optimization", "hard", {}),
        ]
    
    def _get_customer_service_test_cases(self) -> List[TestCase]:
        return [
            TestCase("password_reset", "I forgot my password, can you help?", 
                    ["reset", "email", "link"], 2000, "account_recovery", "easy", {}),
            TestCase("billing_issue", "I was charged twice this month", 
                    ["billing", "charge", "refund"], 3000, "billing_support", "medium", {}),
            TestCase("complex_complaint", "Your service is terrible and I want to cancel", 
                    ["understand", "resolve", "help"], 4000, "complaint_handling", "hard", {}),
        ]
    
    def _get_data_science_test_cases(self) -> List[TestCase]:
        return [
            TestCase("analyze_data", "Analyze this customer data for trends", 
                    ["analyze", "trends", "insights"], 3000, "data_analysis", "medium", {}),
            TestCase("create_visualization", "Create a chart showing sales by region", 
                    ["chart", "visualization", "region"], 4000, "data_visualization", "medium", {}),
        ]
    
    def _get_sales_test_cases(self) -> List[TestCase]:
        return [
            TestCase("qualify_lead", "Is this prospect a good fit for our enterprise package?", 
                    ["qualify", "enterprise", "fit"], 2500, "lead_qualification", "medium", {}),
            TestCase("handle_objection", "Your pricing is too high compared to competitors", 
                    ["value", "benefits", "pricing"], 3000, "objection_handling", "hard", {}),
        ]
    
    def _get_general_test_cases(self) -> List[TestCase]:
        return [
            TestCase("simple_question", "What is 2 + 2?", 
                    ["4", "four"], 1000, "general", "easy", {}),
            TestCase("explain_concept", "Explain machine learning in simple terms", 
                    ["machine", "learning", "data"], 3000, "explanation", "medium", {}),
        ]


# Quick testing functions
def test_agent_quickly(agent_function: Callable[[str], str], agent_id: str = "quick-test") -> Dict:
    """Quick function to test an agent"""
    tester = AgentTester(agent_id)
    tester.register_agent(agent_function)
    return tester.run_test_suite("general")

def monitor_agent_performance(agent_function: Callable[[str], str], agent_id: str):
    """Start continuous monitoring of agent performance"""
    tester = AgentTester(agent_id)
    tester.register_agent(agent_function)
    tester.continuous_monitoring()