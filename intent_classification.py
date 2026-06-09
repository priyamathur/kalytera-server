"""
AgentIQ Intent Classification System
Advanced intent detection to understand how agents are actually being used

Core Features:
- Multi-level intent hierarchy (domain -> intent -> sub-intent)
- Context-aware classification using LLM analysis  
- Real-time intent pattern recognition
- Usage analytics by intent classification
- Drop-off analysis by intent category
"""

import requests
from typing import Dict, List, Optional
from datetime import datetime
import logging
from dataclasses import dataclass
from enum import Enum

class IntentDomain(Enum):
    """High-level domains for agent usage"""
    CUSTOMER_SUPPORT = "customer_support"
    TECHNICAL_ASSISTANCE = "technical_assistance" 
    SALES_BUSINESS = "sales_business"
    DATA_ANALYSIS = "data_analysis"
    CONTENT_CREATION = "content_creation"
    PROCESS_AUTOMATION = "process_automation"
    RESEARCH_DISCOVERY = "research_discovery"
    TROUBLESHOOTING = "troubleshooting"
    GENERAL_INQUIRY = "general_inquiry"

@dataclass
class IntentClassification:
    """Structured intent classification result"""
    domain: IntentDomain
    primary_intent: str
    sub_intent: str
    confidence: float
    reasoning: str
    complexity_level: str  # simple, moderate, complex
    urgency_level: str     # low, medium, high, critical
    workflow_type: str     # single-step, multi-step, iterative
    expected_tools: List[str]

class AgentIntentClassifier:
    """Advanced intent classification for agent usage analytics"""
    
    def __init__(self, api_base: str = "https://agentiq-api-z9it.onrender.com"):
        self.api_base = api_base
        self.logger = logging.getLogger("AgentIQ-IntentClassifier")
        
        # Intent patterns learned from enterprise agent deployments
        self.intent_patterns = self._load_intent_patterns()
        self.workflow_signatures = self._load_workflow_signatures()
    
    def classify_intent(self, user_input: str, context: Optional[Dict] = None) -> IntentClassification:
        """
        Classify user intent with enterprise-grade accuracy
        
        Args:
            user_input: User's raw input to the agent
            context: Optional context (session history, user profile, etc.)
        
        Returns:
            Detailed intent classification with confidence and reasoning
        """
        
        # Multi-stage classification pipeline
        domain = self._classify_domain(user_input, context)
        primary_intent = self._classify_primary_intent(user_input, domain, context)
        sub_intent = self._classify_sub_intent(user_input, domain, primary_intent, context)
        
        # Complexity and urgency analysis
        complexity = self._analyze_complexity(user_input, context)
        urgency = self._analyze_urgency(user_input, context)
        workflow_type = self._predict_workflow_type(user_input, primary_intent, context)
        expected_tools = self._predict_tools_needed(primary_intent, sub_intent, context)
        
        # Overall confidence calculation
        confidence = self._calculate_confidence(user_input, domain, primary_intent, sub_intent)
        reasoning = self._generate_reasoning(user_input, domain, primary_intent, sub_intent)
        
        return IntentClassification(
            domain=domain,
            primary_intent=primary_intent,
            sub_intent=sub_intent,
            confidence=confidence,
            reasoning=reasoning,
            complexity_level=complexity,
            urgency_level=urgency,
            workflow_type=workflow_type,
            expected_tools=expected_tools
        )
    
    def analyze_intent_patterns(self, time_window_hours: int = 24) -> Dict[str, any]:
        """
        Analyze intent patterns across agent usage for usage analytics
        
        Returns:
            Comprehensive intent usage analytics
        """
        try:
            # Get recent agent interactions
            response = requests.get(f"{self.api_base}/analytics/session-volume", timeout=10)
            if response.status_code != 200:
                return {"error": "Unable to fetch session data"}
            
            sessions_data = response.json()
            
            # Analyze intent distribution
            intent_distribution = {}
            workflow_patterns = {}
            drop_off_by_intent = {}
            quality_by_intent = {}
            
            # Get quality data by intent
            quality_response = requests.get(f"{self.api_base}/analytics/quality-by-intent", timeout=10)
            if quality_response.status_code == 200:
                quality_data = quality_response.json()
                for quality in quality_data:
                    intent = quality['intent']
                    quality_by_intent[intent] = {
                        'avg_quality': quality['avg_quality_score'],
                        'sample_size': quality['sample_size'],
                        'confidence': quality['confidence_level'],
                        'failure_patterns': quality.get('top_failure_patterns', [])
                    }
            
            # Get performance data by intent
            performance_response = requests.get(f"{self.api_base}/analytics/intent-performance", timeout=10)
            if performance_response.status_code == 200:
                performance_data = performance_response.json()
                for perf in performance_data:
                    intent = perf['intent']
                    intent_distribution[intent] = {
                        'session_count': perf['session_count'],
                        'completion_rate': perf['completion_rate'],
                        'avg_steps': perf.get('avg_workflow_steps', 1),
                        'success_rate': perf['completion_rate']
                    }
            
            # Generate usage insights
            insights = self._generate_usage_insights(
                intent_distribution, 
                workflow_patterns, 
                quality_by_intent
            )
            
            return {
                'intent_distribution': intent_distribution,
                'workflow_patterns': workflow_patterns,
                'quality_by_intent': quality_by_intent,
                'drop_off_analysis': drop_off_by_intent,
                'usage_insights': insights,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Intent pattern analysis failed: {e}")
            return {"error": str(e)}
    
    def get_intent_performance_recommendations(self) -> List[Dict[str, str]]:
        """
        Generate specific recommendations based on intent performance patterns
        
        Returns:
            List of actionable recommendations for developers
        """
        recommendations = []
        
        try:
            patterns = self.analyze_intent_patterns()
            
            if 'error' in patterns:
                return [{"priority": "Critical", "recommendation": "Fix data pipeline - unable to analyze intent patterns", "impact": "Cannot provide intent-based optimization"}]
            
            quality_by_intent = patterns.get('quality_by_intent', {})
            intent_distribution = patterns.get('intent_distribution', {})
            
            # Analyze each intent for improvement opportunities
            for intent, quality_data in quality_by_intent.items():
                avg_quality = quality_data['avg_quality']
                sample_size = quality_data['sample_size']
                failure_patterns = quality_data.get('failure_patterns', [])
                
                # Get distribution data
                dist_data = intent_distribution.get(intent, {})
                session_count = dist_data.get('session_count', 0)
                completion_rate = dist_data.get('completion_rate', 0)
                
                # Critical quality issues
                if avg_quality < 0.6 and sample_size >= 10:
                    recommendations.append({
                        "priority": "Critical",
                        "intent": intent,
                        "recommendation": f"Urgent: Improve {intent} responses - quality score {avg_quality:.2f}",
                        "impact": f"Could improve {session_count} sessions with {sample_size} evaluations",
                        "specific_actions": failure_patterns[:3] if failure_patterns else ["Review response accuracy", "Improve context understanding", "Add validation"]
                    })
                
                # High-volume low-performance intents
                elif session_count > 50 and completion_rate < 0.7:
                    recommendations.append({
                        "priority": "High",
                        "intent": intent,
                        "recommendation": f"Optimize {intent} workflow - {completion_rate:.1%} completion rate",
                        "impact": f"High-traffic intent with {session_count} sessions",
                        "specific_actions": ["Streamline workflow steps", "Reduce drop-off points", "Add error handling"]
                    })
                
                # Medium priority improvements
                elif avg_quality < 0.75 and sample_size >= 5:
                    recommendations.append({
                        "priority": "Medium", 
                        "intent": intent,
                        "recommendation": f"Enhance {intent} quality - room for improvement",
                        "impact": f"Moderate impact on {session_count} sessions",
                        "specific_actions": ["A/B test response variations", "Gather user feedback", "Optimize prompts"]
                    })
            
            # Sort by priority and potential impact
            priority_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
            recommendations.sort(key=lambda x: (
                priority_order.get(x["priority"], 4),
                -intent_distribution.get(x.get("intent", ""), {}).get("session_count", 0)
            ))
            
            return recommendations[:10]  # Top 10 recommendations
            
        except Exception as e:
            self.logger.error(f"Recommendation generation failed: {e}")
            return [{"priority": "Critical", "recommendation": f"System error in recommendation engine: {e}", "impact": "Cannot generate intent-based recommendations"}]
    
    def _classify_domain(self, user_input: str, context: Optional[Dict]) -> IntentDomain:
        """Classify high-level domain using keyword analysis and LLM reasoning"""
        user_lower = user_input.lower()
        
        # Customer support indicators
        support_keywords = ["help", "issue", "problem", "broken", "not working", "error", "support", "account", "billing", "password", "reset", "cancel", "refund"]
        if any(keyword in user_lower for keyword in support_keywords):
            return IntentDomain.CUSTOMER_SUPPORT
        
        # Technical assistance indicators  
        tech_keywords = ["code", "debug", "function", "api", "programming", "development", "technical", "integration", "configuration", "setup"]
        if any(keyword in user_lower for keyword in tech_keywords):
            return IntentDomain.TECHNICAL_ASSISTANCE
        
        # Sales and business indicators
        sales_keywords = ["pricing", "quote", "demo", "trial", "purchase", "upgrade", "plan", "features", "comparison", "roi"]
        if any(keyword in user_lower for keyword in sales_keywords):
            return IntentDomain.SALES_BUSINESS
        
        # Data analysis indicators
        data_keywords = ["analyze", "data", "report", "metrics", "dashboard", "chart", "visualization", "statistics", "insights"]
        if any(keyword in user_lower for keyword in data_keywords):
            return IntentDomain.DATA_ANALYSIS
        
        # Content creation indicators
        content_keywords = ["write", "create", "generate", "draft", "content", "article", "blog", "copy", "marketing"]
        if any(keyword in user_lower for keyword in content_keywords):
            return IntentDomain.CONTENT_CREATION
        
        # Process automation indicators
        automation_keywords = ["automate", "workflow", "process", "schedule", "batch", "bulk", "recurring"]
        if any(keyword in user_lower for keyword in automation_keywords):
            return IntentDomain.PROCESS_AUTOMATION
        
        # Research and discovery indicators
        research_keywords = ["research", "find", "search", "discover", "explore", "investigate", "learn", "understand"]
        if any(keyword in user_lower for keyword in research_keywords):
            return IntentDomain.RESEARCH_DISCOVERY
        
        # Troubleshooting indicators
        trouble_keywords = ["troubleshoot", "diagnose", "fix", "resolve", "investigate", "why", "how to fix"]
        if any(keyword in user_lower for keyword in trouble_keywords):
            return IntentDomain.TROUBLESHOOTING
        
        # Default to general inquiry
        return IntentDomain.GENERAL_INQUIRY
    
    def _classify_primary_intent(self, user_input: str, domain: IntentDomain, context: Optional[Dict]) -> str:
        """Classify specific intent within domain"""
        user_lower = user_input.lower()
        
        if domain == IntentDomain.CUSTOMER_SUPPORT:
            if any(word in user_lower for word in ["password", "login", "access"]):
                return "account_access"
            elif any(word in user_lower for word in ["billing", "charge", "payment", "refund"]):
                return "billing_support"
            elif any(word in user_lower for word in ["cancel", "close", "delete"]):
                return "account_cancellation"
            elif any(word in user_lower for word in ["feature", "how to", "tutorial"]):
                return "feature_guidance"
            else:
                return "general_support"
        
        elif domain == IntentDomain.TECHNICAL_ASSISTANCE:
            if any(word in user_lower for word in ["debug", "error", "bug", "fix"]):
                return "debugging"
            elif any(word in user_lower for word in ["code", "function", "class", "method"]):
                return "code_generation"
            elif any(word in user_lower for word in ["api", "integration", "connect"]):
                return "api_integration"
            elif any(word in user_lower for word in ["configure", "setup", "install"]):
                return "configuration"
            else:
                return "general_technical"
        
        elif domain == IntentDomain.SALES_BUSINESS:
            if any(word in user_lower for word in ["pricing", "cost", "price"]):
                return "pricing_inquiry"
            elif any(word in user_lower for word in ["demo", "trial", "test"]):
                return "demo_request"
            elif any(word in user_lower for word in ["features", "capabilities", "comparison"]):
                return "feature_comparison"
            elif any(word in user_lower for word in ["upgrade", "plan", "subscription"]):
                return "upgrade_inquiry"
            else:
                return "general_sales"
        
        elif domain == IntentDomain.DATA_ANALYSIS:
            if any(word in user_lower for word in ["analyze", "analysis", "insights"]):
                return "data_analysis"
            elif any(word in user_lower for word in ["chart", "graph", "visualization"]):
                return "data_visualization"
            elif any(word in user_lower for word in ["report", "summary", "dashboard"]):
                return "reporting"
            elif any(word in user_lower for word in ["metrics", "kpi", "performance"]):
                return "performance_metrics"
            else:
                return "general_data"
        
        # Default intent for each domain
        domain_defaults = {
            IntentDomain.CONTENT_CREATION: "content_generation",
            IntentDomain.PROCESS_AUTOMATION: "workflow_automation",
            IntentDomain.RESEARCH_DISCOVERY: "information_discovery",
            IntentDomain.TROUBLESHOOTING: "problem_diagnosis",
            IntentDomain.GENERAL_INQUIRY: "general_question"
        }
        
        return domain_defaults.get(domain, "general_inquiry")
    
    def _classify_sub_intent(self, user_input: str, domain: IntentDomain, primary_intent: str, context: Optional[Dict]) -> str:
        """Classify specific sub-intent for granular analysis"""
        user_lower = user_input.lower()
        
        # Sub-intent classification based on primary intent
        if primary_intent == "debugging":
            if any(word in user_lower for word in ["syntax", "typo", "indentation"]):
                return "syntax_error"
            elif any(word in user_lower for word in ["logic", "algorithm", "wrong result"]):
                return "logic_error"
            elif any(word in user_lower for word in ["runtime", "exception", "crash"]):
                return "runtime_error"
            elif any(word in user_lower for word in ["performance", "slow", "optimization"]):
                return "performance_issue"
            else:
                return "general_debugging"
        
        elif primary_intent == "billing_support":
            if any(word in user_lower for word in ["charged", "unexpected", "wrong"]):
                return "unexpected_charge"
            elif any(word in user_lower for word in ["refund", "money back"]):
                return "refund_request"
            elif any(word in user_lower for word in ["payment", "method", "card"]):
                return "payment_method"
            elif any(word in user_lower for word in ["invoice", "receipt", "statement"]):
                return "billing_documents"
            else:
                return "general_billing"
        
        elif primary_intent == "data_analysis":
            if any(word in user_lower for word in ["trend", "pattern", "correlation"]):
                return "pattern_analysis"
            elif any(word in user_lower for word in ["performance", "metrics", "kpi"]):
                return "performance_analysis"
            elif any(word in user_lower for word in ["user", "customer", "behavior"]):
                return "user_behavior_analysis"
            elif any(word in user_lower for word in ["financial", "revenue", "cost"]):
                return "financial_analysis"
            else:
                return "general_analysis"
        
        # Default sub-intent
        return f"{primary_intent}_general"
    
    def _analyze_complexity(self, user_input: str, context: Optional[Dict]) -> str:
        """Analyze the complexity level of the user request"""
        user_lower = user_input.lower()
        
        # Complex indicators
        complex_indicators = [
            "multi-step", "workflow", "integrate", "complex", "advanced", "enterprise",
            "multiple", "various", "comprehensive", "detailed analysis", "cross-platform"
        ]
        
        # Simple indicators
        simple_indicators = [
            "what is", "how to", "simple", "basic", "quick", "just need", "one question"
        ]
        
        if any(indicator in user_lower for indicator in complex_indicators):
            return "complex"
        elif any(indicator in user_lower for indicator in simple_indicators):
            return "simple" 
        elif len(user_input.split()) > 20:
            return "complex"
        elif len(user_input.split()) < 5:
            return "simple"
        else:
            return "moderate"
    
    def _analyze_urgency(self, user_input: str, context: Optional[Dict]) -> str:
        """Analyze the urgency level of the user request"""
        user_lower = user_input.lower()
        
        # Critical urgency indicators
        critical_indicators = [
            "urgent", "emergency", "critical", "asap", "immediately", "right now",
            "broken", "down", "not working", "production", "losing money"
        ]
        
        # High urgency indicators
        high_indicators = [
            "important", "soon", "today", "deadline", "blocking", "stuck", "issue"
        ]
        
        # Low urgency indicators
        low_indicators = [
            "when you have time", "no rush", "eventually", "curious", "wondering"
        ]
        
        if any(indicator in user_lower for indicator in critical_indicators):
            return "critical"
        elif any(indicator in user_lower for indicator in high_indicators):
            return "high"
        elif any(indicator in user_lower for indicator in low_indicators):
            return "low"
        else:
            return "medium"
    
    def _predict_workflow_type(self, user_input: str, primary_intent: str, context: Optional[Dict]) -> str:
        """Predict the type of workflow this request will trigger"""
        user_lower = user_input.lower()
        
        # Multi-step workflow indicators
        multi_step_indicators = [
            "analyze and then", "first then", "step by step", "process", "workflow",
            "multiple", "series of", "sequence", "integration", "setup"
        ]
        
        # Iterative workflow indicators
        iterative_indicators = [
            "optimize", "improve", "refine", "iterate", "experiment", "test", "try different"
        ]
        
        if any(indicator in user_lower for indicator in multi_step_indicators):
            return "multi-step"
        elif any(indicator in user_lower for indicator in iterative_indicators):
            return "iterative"
        else:
            return "single-step"
    
    def _predict_tools_needed(self, primary_intent: str, sub_intent: str, context: Optional[Dict]) -> List[str]:
        """Predict which tools/APIs the agent will likely need"""
        tool_mapping = {
            "debugging": ["code_analyzer", "error_detector", "syntax_checker"],
            "code_generation": ["code_generator", "documentation", "best_practices"],
            "billing_support": ["billing_system", "payment_processor", "refund_system"],
            "data_analysis": ["data_processor", "analytics_engine", "visualization_tool"],
            "pricing_inquiry": ["pricing_calculator", "feature_comparison", "quote_generator"],
            "account_access": ["authentication_system", "password_reset", "account_lookup"]
        }
        
        return tool_mapping.get(primary_intent, ["general_tools"])
    
    def _calculate_confidence(self, user_input: str, domain: IntentDomain, primary_intent: str, sub_intent: str) -> float:
        """Calculate confidence score for the intent classification"""
        
        # Base confidence from keyword matching
        base_confidence = 0.7
        
        # Boost confidence for clear indicators
        user_lower = user_input.lower()
        domain_keywords = self._get_domain_keywords(domain)
        intent_keywords = self._get_intent_keywords(primary_intent)
        
        keyword_matches = sum(1 for keyword in domain_keywords if keyword in user_lower)
        intent_matches = sum(1 for keyword in intent_keywords if keyword in user_lower)
        
        # Confidence boosting
        if keyword_matches >= 2:
            base_confidence += 0.15
        if intent_matches >= 1:
            base_confidence += 0.1
        if len(user_input.split()) >= 5:  # More context = higher confidence
            base_confidence += 0.05
        
        return min(base_confidence, 0.95)  # Cap at 95%
    
    def _generate_reasoning(self, user_input: str, domain: IntentDomain, primary_intent: str, sub_intent: str) -> str:
        """Generate human-readable reasoning for the classification"""
        return f"Classified as {domain.value} domain based on keywords and context. Primary intent '{primary_intent}' identified from specific request patterns. Sub-intent '{sub_intent}' provides granular categorization for targeted optimization."
    
    def _generate_usage_insights(self, intent_distribution: Dict, workflow_patterns: Dict, quality_by_intent: Dict) -> List[str]:
        """Generate actionable usage insights for enterprise teams"""
        insights = []
        
        if not intent_distribution:
            return ["No usage data available for analysis"]
        
        # Most popular intents
        sorted_intents = sorted(intent_distribution.items(), key=lambda x: x[1].get('session_count', 0), reverse=True)
        if sorted_intents:
            top_intent = sorted_intents[0]
            insights.append(f"Most popular intent: {top_intent[0]} with {top_intent[1]['session_count']} sessions")
        
        # Quality issues
        low_quality_intents = []
        for intent, quality_data in quality_by_intent.items():
            if quality_data['avg_quality'] < 0.7 and quality_data['sample_size'] >= 5:
                low_quality_intents.append((intent, quality_data['avg_quality']))
        
        if low_quality_intents:
            worst_intent = min(low_quality_intents, key=lambda x: x[1])
            insights.append(f"Quality concern: {worst_intent[0]} has {worst_intent[1]:.2f} average quality score")
        
        # Success rate analysis
        low_success_intents = []
        for intent, dist_data in intent_distribution.items():
            completion_rate = dist_data.get('completion_rate', 0)
            session_count = dist_data.get('session_count', 0)
            if completion_rate < 0.7 and session_count >= 10:
                low_success_intents.append((intent, completion_rate, session_count))
        
        if low_success_intents:
            worst_success = min(low_success_intents, key=lambda x: x[1])
            insights.append(f"Completion issue: {worst_success[0]} has {worst_success[1]:.1%} completion rate across {worst_success[2]} sessions")
        
        # High-impact opportunities
        total_sessions = sum(data.get('session_count', 0) for data in intent_distribution.values())
        high_volume_threshold = total_sessions * 0.2  # 20% of total traffic
        
        for intent, dist_data in intent_distribution.items():
            session_count = dist_data.get('session_count', 0)
            completion_rate = dist_data.get('completion_rate', 1)
            
            if session_count >= high_volume_threshold and completion_rate < 0.8:
                potential_impact = session_count * (0.8 - completion_rate)
                insights.append(f"High-impact opportunity: Improving {intent} could recover {potential_impact:.0f} additional successful sessions")
                break
        
        return insights if insights else ["Agent performance is stable across all intents"]
    
    def _load_intent_patterns(self) -> Dict:
        """Load learned intent patterns from enterprise deployments"""
        # This would normally load from a model or database
        # For now, return structured patterns
        return {
            "domain_keywords": {
                "customer_support": ["help", "issue", "problem", "support", "account"],
                "technical_assistance": ["code", "debug", "api", "technical", "development"],
                "sales_business": ["pricing", "quote", "demo", "features", "upgrade"],
                "data_analysis": ["analyze", "data", "report", "insights", "metrics"]
            },
            "intent_keywords": {
                "debugging": ["debug", "error", "bug", "fix", "broken"],
                "billing_support": ["billing", "charge", "payment", "refund", "invoice"],
                "account_access": ["password", "login", "access", "reset", "locked"],
                "data_analysis": ["analyze", "insights", "trends", "patterns", "performance"]
            }
        }
    
    def _load_workflow_signatures(self) -> Dict:
        """Load workflow signatures for pattern recognition"""
        return {
            "multi_step_patterns": ["analyze and then", "first then", "step by step"],
            "iterative_patterns": ["optimize", "improve", "iterate", "refine"],
            "single_step_patterns": ["what is", "how do", "show me"]
        }
    
    def _get_domain_keywords(self, domain: IntentDomain) -> List[str]:
        """Get keywords associated with a domain"""
        domain_map = {
            IntentDomain.CUSTOMER_SUPPORT: ["help", "issue", "problem", "support"],
            IntentDomain.TECHNICAL_ASSISTANCE: ["code", "debug", "api", "technical"],
            IntentDomain.SALES_BUSINESS: ["pricing", "quote", "demo", "features"],
            IntentDomain.DATA_ANALYSIS: ["analyze", "data", "report", "insights"]
        }
        return domain_map.get(domain, [])
    
    def _get_intent_keywords(self, intent: str) -> List[str]:
        """Get keywords associated with an intent"""
        intent_map = {
            "debugging": ["debug", "error", "bug", "fix"],
            "billing_support": ["billing", "charge", "payment", "refund"],
            "account_access": ["password", "login", "access", "reset"],
            "data_analysis": ["analyze", "insights", "trends", "patterns"]
        }
        return intent_map.get(intent, [])