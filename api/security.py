"""
Security and API Key Management for AgentIQ
Implements secure key handling and token usage optimization
"""

import os
import hashlib
from typing import Optional
from functools import lru_cache
import asyncio
import time
from datetime import datetime, timedelta
from collections import defaultdict
import logging

# Configure logging for security events
security_logger = logging.getLogger("agentiq.security")


class SecureAPIKeyManager:
    """
    Secure API key management with token usage tracking and optimization
    """
    
    def __init__(self):
        self._api_key = None
        self._key_hash = None
        self._usage_tracker = TokenUsageTracker()
        self._load_secure_key()
    
    def _load_secure_key(self):
        """Load API key securely from environment"""
        api_key = os.getenv("ANTHROPIC_API_KEY")
        
        if not api_key:
            security_logger.warning("No ANTHROPIC_API_KEY found in environment")
            return
        
        if api_key.startswith("your_") or len(api_key) < 50:
            security_logger.warning("Invalid or placeholder API key detected")
            return
            
        # Store only hash for logging/debugging
        self._key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:8]
        self._api_key = api_key
        
        security_logger.info(f"API key loaded successfully (hash: {self._key_hash})")
    
    @property
    def is_available(self) -> bool:
        """Check if API key is available"""
        return self._api_key is not None
    
    @property
    def api_key(self) -> Optional[str]:
        """Get API key (never log this)"""
        return self._api_key
    
    @property 
    def usage_tracker(self) -> 'TokenUsageTracker':
        """Get usage tracker instance"""
        return self._usage_tracker
    
    def get_masked_key(self) -> str:
        """Get masked key for logging"""
        if not self._api_key:
            return "NOT_SET"
        return f"sk-ant-***{self._api_key[-6:]}"


class TokenUsageTracker:
    """
    Track and optimize Claude API token usage
    """
    
    def __init__(self):
        self.daily_limits = {
            "total_tokens": 100000,  # Conservative daily limit
            "requests_per_hour": 100,
            "pattern_analysis_tokens": 50000,
            "evaluation_tokens": 40000
        }
        
        self.usage_stats = defaultdict(int)
        self.request_timestamps = []
        self.last_reset = datetime.now().date()
    
    def _reset_daily_stats_if_needed(self):
        """Reset stats if it's a new day"""
        today = datetime.now().date()
        if today > self.last_reset:
            self.usage_stats.clear()
            self.request_timestamps.clear()
            self.last_reset = today
            security_logger.info("Daily token usage stats reset")
    
    def check_rate_limit(self) -> bool:
        """Check if we're within rate limits"""
        self._reset_daily_stats_if_needed()
        
        # Check hourly request limit
        hour_ago = datetime.now() - timedelta(hours=1)
        recent_requests = [ts for ts in self.request_timestamps if ts > hour_ago]
        
        if len(recent_requests) >= self.daily_limits["requests_per_hour"]:
            security_logger.warning("Hourly rate limit exceeded")
            return False
        
        # Check daily token limit
        if self.usage_stats["total_tokens"] >= self.daily_limits["total_tokens"]:
            security_logger.warning("Daily token limit exceeded")
            return False
        
        return True
    
    def record_usage(self, operation: str, tokens_used: int):
        """Record token usage for an operation"""
        self._reset_daily_stats_if_needed()
        
        self.usage_stats["total_tokens"] += tokens_used
        self.usage_stats[f"{operation}_tokens"] += tokens_used
        self.request_timestamps.append(datetime.now())
        
        # Log usage for monitoring
        remaining = self.daily_limits["total_tokens"] - self.usage_stats["total_tokens"]
        security_logger.info(
            f"Token usage - Operation: {operation}, Used: {tokens_used}, "
            f"Daily total: {self.usage_stats['total_tokens']}, Remaining: {remaining}"
        )
    
    def get_usage_stats(self) -> dict:
        """Get current usage statistics"""
        self._reset_daily_stats_if_needed()
        
        return {
            "daily_usage": dict(self.usage_stats),
            "daily_limits": self.daily_limits,
            "requests_last_hour": len([
                ts for ts in self.request_timestamps 
                if ts > datetime.now() - timedelta(hours=1)
            ]),
            "utilization_pct": round(
                (self.usage_stats["total_tokens"] / self.daily_limits["total_tokens"]) * 100, 1
            )
        }


class OptimizedClaudeClient:
    """
    Optimized Claude client with token limits and prompt optimization
    """
    
    def __init__(self, key_manager: SecureAPIKeyManager):
        self.key_manager = key_manager
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize Claude client if API key available"""
        if not self.key_manager.is_available:
            return
        
        try:
            from anthropic import Anthropic
            self.client = Anthropic(api_key=self.key_manager.api_key)
            security_logger.info("Claude client initialized successfully")
        except Exception as e:
            security_logger.error(f"Failed to initialize Claude client: {e}")
    
    async def evaluate_interaction(
        self, 
        user_input: str, 
        agent_response: str, 
        context: Optional[str] = None
    ) -> dict:
        """
        Optimized evaluation with token limits and concise prompts
        """
        if not self.client or not self.key_manager.usage_tracker.check_rate_limit():
            return self._fallback_evaluation()
        
        # Optimized prompt - much shorter than original
        prompt = self._build_optimized_evaluation_prompt(user_input, agent_response, context)
        
        try:
            response = self.client.messages.create(
                model="claude-3-haiku-20240307",  # Use Haiku for cost optimization
                max_tokens=150,  # Strict token limit
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}]
            )
            
            # Track token usage (approximate)
            estimated_tokens = len(prompt.split()) + 150
            self.key_manager.usage_tracker.record_usage("evaluation", estimated_tokens)
            
            return self._parse_evaluation_response(response.content[0].text)
            
        except Exception as e:
            security_logger.error(f"Evaluation API call failed: {e}")
            return self._fallback_evaluation()
    
    async def analyze_pattern(self, pattern_data: dict) -> dict:
        """
        Optimized pattern analysis with minimal token usage
        """
        if not self.client or not self.key_manager.usage_tracker.check_rate_limit():
            return {"root_cause": "Analysis unavailable", "suggested_fix": "Manual review needed"}
        
        # Ultra-concise prompt for pattern analysis
        prompt = f"""Pattern: {pattern_data['type']} - {pattern_data['value']}
Failures: {pattern_data['failure_count']} ({pattern_data['failure_rate']:.1%})

Provide:
1. ROOT_CAUSE: One sentence
2. SUGGESTED_FIX: One sentence"""
        
        try:
            response = self.client.messages.create(
                model="claude-3-haiku-20240307",  # Haiku for cost efficiency
                max_tokens=100,  # Very strict limit
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}]
            )
            
            # Track minimal token usage
            self.key_manager.usage_tracker.record_usage("pattern_analysis", 120)
            
            return self._parse_pattern_response(response.content[0].text)
            
        except Exception as e:
            security_logger.error(f"Pattern analysis failed: {e}")
            return {"root_cause": "Analysis unavailable", "suggested_fix": "Manual review needed"}
    
    def _build_optimized_evaluation_prompt(self, user_input: str, agent_response: str, context: Optional[str]) -> str:
        """Build ultra-concise evaluation prompt"""
        
        # Truncate inputs to save tokens
        user_input = user_input[:200] + "..." if len(user_input) > 200 else user_input
        agent_response = agent_response[:300] + "..." if len(agent_response) > 300 else agent_response
        
        return f"""User: {user_input}
Agent: {agent_response}

Score 0-1 and classify failure:
Format: SCORE:0.X|TYPE:category|REASON:brief"""
    
    def _parse_evaluation_response(self, response: str) -> dict:
        """Parse concise evaluation response"""
        try:
            # Parse format: SCORE:0.7|TYPE:incomplete|REASON:missing info
            parts = response.strip().split('|')
            
            score = 0.5  # default
            failure_type = "unknown"
            reasoning = "Evaluation completed"
            
            for part in parts:
                if part.startswith("SCORE:"):
                    score = float(part.split(":")[1])
                elif part.startswith("TYPE:"):
                    failure_type = part.split(":")[1]
                elif part.startswith("REASON:"):
                    reasoning = part.split(":", 1)[1]
            
            return {
                "overall_score": score,
                "accuracy_score": score,
                "goal_alignment_score": score,
                "decision_quality_score": score,
                "completeness_score": score,
                "failure_category": failure_type,
                "evaluation_reasoning": reasoning
            }
            
        except Exception:
            return self._fallback_evaluation()
    
    def _parse_pattern_response(self, response: str) -> dict:
        """Parse pattern analysis response"""
        try:
            root_cause = ""
            suggested_fix = ""
            
            for line in response.split('\n'):
                if 'ROOT_CAUSE:' in line:
                    root_cause = line.split('ROOT_CAUSE:', 1)[1].strip()
                elif 'SUGGESTED_FIX:' in line:
                    suggested_fix = line.split('SUGGESTED_FIX:', 1)[1].strip()
            
            return {
                "root_cause": root_cause or "Pattern analysis needed",
                "suggested_fix": suggested_fix or "Manual investigation required"
            }
            
        except Exception:
            return {"root_cause": "Analysis failed", "suggested_fix": "Manual review needed"}
    
    def _fallback_evaluation(self) -> dict:
        """Fallback evaluation when API unavailable"""
        return {
            "overall_score": 0.5,
            "accuracy_score": 0.5,
            "goal_alignment_score": 0.5,
            "decision_quality_score": 0.5,
            "completeness_score": 0.5,
            "failure_category": "evaluation_unavailable",
            "evaluation_reasoning": "Claude API unavailable - using fallback scoring"
        }


# Global instances
key_manager = SecureAPIKeyManager()
optimized_claude_client = OptimizedClaudeClient(key_manager)


# Security middleware for FastAPI
def get_usage_stats():
    """Get API usage statistics for monitoring"""
    return key_manager.usage_tracker.get_usage_stats()


def check_api_health():
    """Check API key and usage health"""
    return {
        "api_key_available": key_manager.is_available,
        "api_key_hash": key_manager._key_hash,
        "usage_stats": get_usage_stats(),
        "rate_limit_ok": key_manager.usage_tracker.check_rate_limit()
    }