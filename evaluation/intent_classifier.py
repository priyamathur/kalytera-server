"""
Intent classifier using Claude API
Analyzes first 2 steps of each session to determine user intent
Provides high-accuracy intent classification for session routing
"""

import os
from typing import List, Dict, Tuple, Optional
from anthropic import Anthropic
import json
import asyncio
from dataclasses import dataclass


@dataclass
class IntentClassification:
    """Result of intent classification"""
    primary_intent: str
    confidence: float
    secondary_intents: List[Tuple[str, float]]
    reasoning: str
    workflow_patterns: List[str]


class IntentClassifier:
    """Claude-powered intent classifier for agent conversations"""
    
    # Model fallback chain - try newer models first, fall back to older/smaller ones
    CLAUDE_MODELS = [
        "claude-3-5-sonnet-20241022",  # Latest Sonnet
        "claude-3-5-haiku-20241022",   # Latest Haiku  
        "claude-3-opus-20240229",      # Opus (most capable)
        "claude-3-sonnet-20240229",    # Original Sonnet
        "claude-3-haiku-20240307",     # Stable Haiku (fastest)
    ]
    
    # Standard intent taxonomy - can be customized per deployment
    INTENT_CATEGORIES = {
        "billing": {
            "description": "Questions about charges, payments, invoices, billing cycles",
            "indicators": ["bill", "charge", "payment", "invoice", "billing", "cost", "price"],
            "complexity": "medium"
        },
        "refunds": {
            "description": "Return requests, refund inquiries, dispute resolution",
            "indicators": ["refund", "return", "cancel order", "dispute", "chargeback", "money back"],
            "complexity": "high"
        },
        "subscriptions": {
            "description": "Subscription management, plan changes, cancellations",
            "indicators": ["subscription", "plan", "upgrade", "downgrade", "cancel", "renewal"],
            "complexity": "low"
        },
        "account_recovery": {
            "description": "Password resets, account access, security issues",
            "indicators": ["password", "login", "access", "locked", "security", "hack", "forgot"],
            "complexity": "high"
        },
        "technical_support": {
            "description": "Product issues, bugs, troubleshooting, how-to questions",
            "indicators": ["bug", "error", "not working", "broken", "help", "how to", "issue"],
            "complexity": "medium"
        },
        "general_enquiry": {
            "description": "General questions, information requests, policy questions",
            "indicators": ["policy", "hours", "contact", "location", "information", "about"],
            "complexity": "low"
        }
    }
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize classifier with Anthropic API"""
        api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or ""
        if not api_key or api_key.startswith("your_"):
            raise ValueError("ANTHROPIC_API_KEY environment variable not set or is a placeholder")
        self.client = Anthropic(api_key=api_key)
    
    async def classify_intent(self, conversation_text: str) -> Dict[str, str]:
        """
        Simple intent classification interface for trace endpoint
        
        Args:
            conversation_text: Formatted conversation string
            
        Returns:
            Dict with intent and confidence
        """
        # Parse conversation into interactions
        interactions = self._parse_conversation_text(conversation_text)
        
        # Get full classification
        classification = await self.classify_session_intent(interactions)
        
        return {
            "intent": classification.primary_intent,
            "confidence": classification.confidence,
            "reasoning": classification.reasoning
        }

    def _parse_conversation_text(self, conversation_text: str) -> List[Dict]:
        """Parse conversation text back into interaction format"""
        interactions = []
        lines = conversation_text.strip().split('\n')
        
        current_user_input = ""
        current_agent_response = ""
        
        for line in lines:
            line = line.strip()
            if line.startswith("User:"):
                current_user_input = line[5:].strip()
            elif line.startswith("Agent:"):
                current_agent_response = line[6:].strip()
                # When we have both user and agent, create interaction
                if current_user_input and current_agent_response:
                    interactions.append({
                        "user_input": current_user_input,
                        "agent_response": current_agent_response
                    })
                    current_user_input = ""
                    current_agent_response = ""
        
        return interactions

    async def classify_session_intent(self, interactions: List[Dict]) -> IntentClassification:
        """
        Classify intent based on first 2 interactions of a session
        
        Args:
            interactions: List of interaction dicts with user_input and agent_response
            
        Returns:
            IntentClassification with primary intent, confidence, and analysis
        """
        
        if not interactions:
            return IntentClassification(
                primary_intent="unknown",
                confidence=0.0,
                secondary_intents=[],
                reasoning="No interactions provided",
                workflow_patterns=[]
            )
        
        # Use first 2 interactions for classification
        analysis_interactions = interactions[:2]
        
        # Prepare conversation context for Claude
        conversation_text = self._format_conversation_for_analysis(analysis_interactions)
        
        # Build classification prompt
        prompt = self._build_classification_prompt(conversation_text)
        
        # Try multiple Claude models in order of preference
        for model_name in self.CLAUDE_MODELS:
            try:
                # Get classification from Claude
                response = self.client.messages.create(
                    model=model_name,
                    max_tokens=1000,
                    temperature=0.1,  # Low temperature for consistent classification
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
                
                # Parse Claude's response
                classification = self._parse_classification_response(response.content[0].text)
                
                print(f"✅ Intent classification successful with {model_name}")
                return classification
                
            except Exception as e:
                print(f"⚠️  Model {model_name} failed: {e}")
                continue  # Try next model
        
        # If all Claude models fail, use rule-based fallback as last resort
        print("⚠️  All Claude models failed, using rule-based fallback")
        return self._fallback_classification(analysis_interactions)
    
    def _format_conversation_for_analysis(self, interactions: List[Dict]) -> str:
        """Format interactions into readable conversation for Claude"""
        
        conversation_parts = []
        
        for i, interaction in enumerate(interactions, 1):
            user_input = interaction.get('user_input', '')
            agent_response = interaction.get('agent_response', '')
            
            conversation_parts.append(f"Turn {i}:")
            conversation_parts.append(f"User: {user_input}")
            conversation_parts.append(f"Agent: {agent_response}")
            conversation_parts.append("")  # Blank line for readability
        
        return "\n".join(conversation_parts)
    
    def _build_classification_prompt(self, conversation: str) -> str:
        """Build prompt for Claude intent classification"""
        
        # Build intent category descriptions
        intent_descriptions = []
        for intent, details in self.INTENT_CATEGORIES.items():
            intent_descriptions.append(f"- **{intent}**: {details['description']}")
        
        intent_list = "\n".join(intent_descriptions)
        
        return f"""You are an expert at analyzing customer service conversations to determine user intent.

Analyze the following conversation and classify the primary intent. Consider both what the user explicitly asks for and what they implicitly need.

INTENT CATEGORIES:
{intent_list}

CONVERSATION:
{conversation}

Respond with a JSON object containing:
{{
    "primary_intent": "the most likely intent category",
    "confidence": 0.95,  // confidence score 0.0-1.0
    "secondary_intents": [
        ["intent_name", 0.3],  // other possible intents with scores
        ["another_intent", 0.2]
    ],
    "reasoning": "brief explanation of why you chose this classification",
    "workflow_patterns": ["pattern1", "pattern2"]  // observed conversation patterns
}}

Guidelines:
- Focus on user's actual need, not just keywords
- Consider conversation flow and context
- Be confident in clear cases, cautious when ambiguous
- Secondary intents should only include realistic alternatives
- Workflow patterns might be: "direct_request", "complaint", "confusion", "escalation", "information_gathering"

Respond only with valid JSON."""
    
    def _parse_classification_response(self, response_text: str) -> IntentClassification:
        """Parse Claude's JSON response into IntentClassification"""
        
        try:
            # Extract JSON from response (handle any extra text)
            response_text = response_text.strip()
            if not response_text.startswith('{'):
                # Find JSON in response
                start = response_text.find('{')
                end = response_text.rfind('}') + 1
                if start >= 0 and end > start:
                    response_text = response_text[start:end]
            
            result = json.loads(response_text)
            
            return IntentClassification(
                primary_intent=result.get('primary_intent', 'unknown'),
                confidence=float(result.get('confidence', 0.0)),
                secondary_intents=[(intent, float(score)) for intent, score in result.get('secondary_intents', [])],
                reasoning=result.get('reasoning', ''),
                workflow_patterns=result.get('workflow_patterns', [])
            )
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"⚠️  Failed to parse Claude response: {e}")
            print(f"Raw response: {response_text}")
            
            # Attempt to extract intent from text
            return self._extract_intent_from_text(response_text)
    
    def _extract_intent_from_text(self, text: str) -> IntentClassification:
        """Fallback: extract intent from unstructured text response"""
        
        text_lower = text.lower()
        
        # Look for intent mentions in text
        intent_scores = {}
        for intent in self.INTENT_CATEGORIES.keys():
            if intent in text_lower:
                # Simple scoring based on mentions
                intent_scores[intent] = text_lower.count(intent)
        
        if intent_scores:
            primary_intent = max(intent_scores, key=intent_scores.get)
            confidence = min(0.6, intent_scores[primary_intent] * 0.3)  # Lower confidence for fallback
        else:
            primary_intent = "general_enquiry"
            confidence = 0.3
        
        return IntentClassification(
            primary_intent=primary_intent,
            confidence=confidence,
            secondary_intents=[],
            reasoning=f"Fallback classification from text analysis: {text[:100]}...",
            workflow_patterns=[]
        )
    
    def _fallback_classification(self, interactions: List[Dict]) -> IntentClassification:
        """Rule-based fallback when all Claude models fail - last resort only"""
        
        # Combine all user inputs for analysis
        all_text = " ".join([
            interaction.get('user_input', '') 
            for interaction in interactions
        ]).lower()
        
        # Score each intent based on keyword matching
        intent_scores = {}
        
        for intent, details in self.INTENT_CATEGORIES.items():
            score = 0
            indicators = details['indicators']
            
            for indicator in indicators:
                score += all_text.count(indicator.lower())
            
            # Weight by indicator strength
            if score > 0:
                intent_scores[intent] = score / len(indicators)
        
        if intent_scores:
            # Get primary and secondary intents
            sorted_intents = sorted(intent_scores.items(), key=lambda x: x[1], reverse=True)
            primary_intent = sorted_intents[0][0]
            confidence = min(0.8, sorted_intents[0][1])  # Cap at 0.8 for rule-based
            
            secondary_intents = [
                (intent, score * 0.7)  # Reduce secondary intent confidence
                for intent, score in sorted_intents[1:3]  # Top 2 alternatives
                if score > 0.1
            ]
        else:
            primary_intent = "general_enquiry"
            confidence = 0.5
            secondary_intents = []
        
        return IntentClassification(
            primary_intent=primary_intent,
            confidence=confidence,
            secondary_intents=secondary_intents,
            reasoning="Rule-based fallback classification based on keyword matching",
            workflow_patterns=["keyword_based"]
        )
    
    def batch_classify_sessions(self, sessions: List[List[Dict]]) -> List[IntentClassification]:
        """Classify multiple sessions in batch"""
        
        results = []
        
        for i, session_interactions in enumerate(sessions):
            try:
                classification = asyncio.run(self.classify_session_intent(session_interactions))
                results.append(classification)
                
                # Rate limiting - Claude has usage limits
                if i % 10 == 0 and i > 0:
                    print(f"📊 Classified {i}/{len(sessions)} sessions...")
                    asyncio.sleep(1)  # Brief pause every 10 requests
                    
            except Exception as e:
                print(f"⚠️  Failed to classify session {i}: {e}")
                results.append(self._fallback_classification(session_interactions))
        
        return results
    
    @staticmethod
    def get_intent_description(intent: str) -> Dict[str, str]:
        """Get description and metadata for an intent"""
        return IntentClassifier.INTENT_CATEGORIES.get(intent, {
            "description": "Unknown intent category",
            "indicators": [],
            "complexity": "medium"
        })


# Testing and validation utilities
class IntentClassifierTester:
    """Test and validate intent classifier performance"""
    
    def __init__(self, classifier: IntentClassifier):
        self.classifier = classifier
    
    def test_with_known_examples(self) -> Dict[str, float]:
        """Test classifier with known examples and return accuracy metrics"""
        
        test_cases = [
            {
                "interactions": [
                    {"user_input": "I have a question about my last bill", "agent_response": "I can help with billing questions."},
                    {"user_input": "There's a charge I don't recognize", "agent_response": "Let me look up that charge for you."}
                ],
                "expected_intent": "billing"
            },
            {
                "interactions": [
                    {"user_input": "I want to return this product", "agent_response": "I can help with returns."},
                    {"user_input": "When will I get my money back?", "agent_response": "Refunds typically take 3-5 business days."}
                ],
                "expected_intent": "refunds"
            },
            {
                "interactions": [
                    {"user_input": "How do I cancel my subscription?", "agent_response": "I can help you manage your subscription."},
                    {"user_input": "I want to downgrade my plan", "agent_response": "Let me show you the available options."}
                ],
                "expected_intent": "subscriptions"
            }
        ]
        
        correct_predictions = 0
        results = {}
        
        for i, test_case in enumerate(test_cases):
            try:
                classification = asyncio.run(
                    self.classifier.classify_session_intent(test_case["interactions"])
                )
                
                predicted = classification.primary_intent
                expected = test_case["expected_intent"]
                
                if predicted == expected:
                    correct_predictions += 1
                
                results[f"test_{i}"] = {
                    "expected": expected,
                    "predicted": predicted,
                    "confidence": classification.confidence,
                    "correct": predicted == expected
                }
                
            except Exception as e:
                print(f"Test case {i} failed: {e}")
                results[f"test_{i}"] = {"error": str(e)}
        
        accuracy = correct_predictions / len(test_cases) if test_cases else 0
        results["overall_accuracy"] = accuracy
        
        return results