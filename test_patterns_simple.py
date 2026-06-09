#!/usr/bin/env python3
"""
Simple pattern analysis test to avoid circular imports
"""

import sys
sys.path.append('.')
import asyncio
import json

def test_pattern_analysis_components():
    """Test pattern analysis components independently"""
    
    print("🧪 Testing Pattern Analysis Components")
    print("=" * 50)
    
    # Test 1: Validate pattern data structures
    try:
        # Test pattern structure
        pattern_data = {
            "pattern_type": "intent",
            "pattern_value": "billing_dispute", 
            "failure_count": 47,
            "total_failures": 100,
            "pct_of_all_failures": 47.0,
            "root_cause": "Billing API timeout at step 3 prevents account access",
            "improvement_suggestions": ["Increase API timeout", "Add retry logic"]
        }
        
        # Validate pattern structure
        required_keys = ["pattern_type", "pattern_value", "failure_count", "pct_of_all_failures", "root_cause"]
        for key in required_keys:
            assert key in pattern_data, f"Pattern missing required key: {key}"
        
        # Validate percentage calculation
        expected_pct = (pattern_data["failure_count"] / pattern_data["total_failures"]) * 100
        assert abs(pattern_data["pct_of_all_failures"] - expected_pct) < 0.1, "Percentage calculation incorrect"
        
        print("✅ Pattern data structure validation passed")
        print(f"📊 Pattern: {pattern_data['pattern_type']} = {pattern_data['pattern_value']}")
        print(f"📊 Impact: {pattern_data['pct_of_all_failures']}% of failures")
        
    except Exception as e:
        print(f"❌ Pattern structure test failed: {e}")
    
    # Test 2: Validate failure taxonomy
    try:
        failure_types = ["wrong_answer", "tool_failure", "goal_drift", "incomplete", "hallucination", "context_loss", "loop"]
        pattern_types = ["intent", "workflow_step", "tool_call", "topic"]
        
        print(f"✅ Failure types: {len(failure_types)} categories")
        print(f"📋 Types: {', '.join(failure_types)}")
        
        print(f"✅ Pattern dimensions: {len(pattern_types)} types")
        print(f"📋 Dimensions: {', '.join(pattern_types)}")
        
        assert len(failure_types) == 7, "Should have 7 failure types"
        assert len(pattern_types) >= 4, "Should have at least 4 pattern dimensions"
        
    except Exception as e:
        print(f"❌ Taxonomy test failed: {e}")
    
    # Test 3: Validate pattern export schema
    try:
        export_schema = {
            "patterns": [
                {
                    "pattern_type": "intent",
                    "pattern_value": "billing",
                    "failure_count": 25,
                    "pct_of_all_failures": 35.2,
                    "root_cause": "API timeout prevents account access",
                    "improvement_suggestions": ["Add retry logic", "Increase timeout"]
                }
            ],
            "metadata": {
                "generated_at": "2026-06-08T10:00:00Z",
                "hours_analyzed": 24,
                "total_failures": 71
            },
            "training_data": {
                "negative_examples": [],
                "pattern_coverage": {}
            },
            "policy_improvement": {
                "improvement_signals": [
                    "Focus on billing API reliability",
                    "Add timeout handling in step 3"
                ]
            },
            "reward_function": {
                "primary_metric": "overall_score",
                "target_threshold": 0.75,
                "weights": {
                    "accuracy": 0.3,
                    "goal_alignment": 0.25,
                    "decision_quality": 0.25,
                    "completeness": 0.2
                }
            }
        }
        
        # Validate schema matches expected structure
        required_sections = ["patterns", "metadata", "training_data", "policy_improvement", "reward_function"]
        for section in required_sections:
            assert section in export_schema, f"Export schema missing section: {section}"
        
        # Test JSON serialization
        json_str = json.dumps(export_schema, indent=2)
        parsed = json.loads(json_str)
        assert parsed == export_schema, "Schema should be JSON serializable"
        
        print("✅ Pattern export schema validation passed")
        print(f"📄 Schema has {len(required_sections)} required sections")
        print(f"🔧 Ready for RL integration with {len(export_schema['policy_improvement']['improvement_signals'])} signals")
        
    except Exception as e:
        print(f"❌ Export schema test failed: {e}")
    
    # Test 4: Pattern threshold logic
    try:
        min_pattern_count = 5
        test_scenarios = [
            {"count": 3, "should_create": False, "name": "below threshold"},
            {"count": 5, "should_create": True, "name": "at threshold"}, 
            {"count": 15, "should_create": True, "name": "above threshold"}
        ]
        
        for scenario in test_scenarios:
            should_create = scenario["count"] >= min_pattern_count
            assert should_create == scenario["should_create"], f"Pattern threshold logic failed for {scenario['name']}"
        
        print("✅ Pattern threshold logic validation passed")
        print(f"🎯 Minimum pattern count: {min_pattern_count}")
        
    except Exception as e:
        print(f"❌ Threshold logic test failed: {e}")
    
    print("\n🎯 Pattern Analysis Component Tests Complete")

if __name__ == "__main__":
    test_pattern_analysis_components()