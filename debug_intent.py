#!/usr/bin/env python3
import asyncio
import sys
sys.path.append('.')

async def test_intent_classifier():
    from evaluation.intent_classifier import IntentClassifier
    
    classifier = IntentClassifier()
    print("✅ Intent classifier created")
    
    # Test with properly formatted conversation
    conversation = "User: I need to dispute this charge\nAgent: I can help you with that billing issue"
    print(f"🔍 Testing with conversation: '{conversation}'")
    
    result = await classifier.classify_intent(conversation)
    print(f"📊 Result: {result}")
    print(f"📊 Result type: {type(result)}")
    
    # Check what keys are available
    if isinstance(result, dict):
        print(f"📊 Available keys: {list(result.keys())}")

if __name__ == "__main__":
    asyncio.run(test_intent_classifier())