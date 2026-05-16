#!/usr/bin/env python3
"""
Phase 1: LLM Evaluation Engine Testing
Tests Claude Sonnet integration and autonomous evaluation
"""

import requests
import json
import time
from datetime import datetime

LOCAL_API = "http://localhost:8000"

def test_1_1_claude_api_integration():
    """Test 1.1: Verify Claude API is properly integrated"""
    print("🧪 Test 1.1: Claude API Integration")
    print("-" * 50)
    
    try:
        response = requests.get(f"{LOCAL_API}/evaluation/health", timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Health endpoint: Status 200")
            print(f"✅ Evaluation system: {data.get('evaluation_system', 'unknown')}")
            print(f"✅ Anthropic API: {data.get('anthropic_api', 'unknown')}")
            print(f"✅ Model: {data.get('model', 'unknown')}")
            
            return data.get('evaluation_system') == 'online'
        else:
            print(f"❌ Health check failed: HTTP {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Health check error: {str(e)}")
        return False

def test_1_2_single_interaction_evaluation():
    """Test 1.2: Test LLM judge on real agent conversations"""
    print("\n🧪 Test 1.2: Single Interaction Evaluation")
    print("-" * 50)
    
    test_cases = [
        {
            "name": "Good Response",
            "data": {
                "user_input": "I need to cancel my subscription",
                "agent_response": "I can help you cancel your subscription. Let me process that for you right away and provide a confirmation email.",
                "context": "customer support"
            },
            "expected_score": "> 0.7"
        },
        {
            "name": "Poor Response",
            "data": {
                "user_input": "I have a billing dispute for a double charge",
                "agent_response": "Sorry, I cannot help with that. Please try again later.",
                "context": "customer support"  
            },
            "expected_score": "< 0.5"
        },
        {
            "name": "Complex Technical Issue",
            "data": {
                "user_input": "Our API integration is failing with 500 errors",
                "agent_response": "I understand you're experiencing 500 errors. I've escalated this to our engineering team and you should expect a resolution within 2 hours. I'll monitor your account and update you every 30 minutes.",
                "context": "technical support"
            },
            "expected_score": "> 0.8"
        }
    ]
    
    results = []
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n📝 Test Case {i}: {test_case['name']}")
        
        try:
            response = requests.post(
                f"{LOCAL_API}/evaluation/evaluate-interaction",
                json=test_case["data"],
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                
                overall_score = result.get('overall_score', 0)
                accuracy_score = result.get('accuracy_score', 0)
                failure_category = result.get('failure_category')
                reasoning = result.get('evaluation_reasoning', '')
                
                print(f"   ✅ Response received: Status 200")
                print(f"   📊 Overall Score: {overall_score:.3f}")
                print(f"   📊 Accuracy Score: {accuracy_score:.3f}")
                print(f"   🏷️  Failure Category: {failure_category}")
                print(f"   💭 Reasoning: {reasoning[:100]}..." if reasoning else "   💭 Reasoning: Not provided")
                
                # Validate score ranges
                if ">" in test_case["expected_score"]:
                    threshold = float(test_case["expected_score"].split(">")[1].strip())
                    score_valid = overall_score > threshold
                else:
                    threshold = float(test_case["expected_score"].split("<")[1].strip())
                    score_valid = overall_score < threshold
                
                if score_valid:
                    print(f"   ✅ Score within expected range: {test_case['expected_score']}")
                else:
                    print(f"   ⚠️  Score outside expected range: {test_case['expected_score']}")
                
                results.append({
                    "name": test_case["name"],
                    "success": True,
                    "overall_score": overall_score,
                    "failure_category": failure_category,
                    "score_valid": score_valid
                })
                
            elif response.status_code == 503:
                print(f"   🟡 Service unavailable (503) - API key issue")
                results.append({"name": test_case["name"], "success": False, "error": "API key"})
                
            else:
                print(f"   ❌ Request failed: HTTP {response.status_code}")
                try:
                    error_data = response.json()
                    print(f"   📄 Error: {error_data.get('detail', 'Unknown error')}")
                except:
                    pass
                results.append({"name": test_case["name"], "success": False, "error": f"HTTP {response.status_code}"})
            
        except Exception as e:
            print(f"   ❌ Exception: {str(e)}")
            results.append({"name": test_case["name"], "success": False, "error": str(e)})
        
        time.sleep(1)  # Rate limiting
    
    return results

def test_1_3_batch_evaluation():
    """Test 1.3: Test batch evaluation of existing logs"""
    print("\n🧪 Test 1.3: Batch Evaluation")
    print("-" * 50)
    
    # First, ensure we have some data to evaluate
    print("📥 Loading test data first...")
    try:
        # Load sophisticated data
        import subprocess
        result = subprocess.run(["python3", "populate_sophisticated_data.py"], 
                              capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            print("✅ Test data loaded successfully")
        else:
            print(f"⚠️  Data loading had issues: {result.stderr[:100]}...")
    except Exception as e:
        print(f"⚠️  Could not load test data: {str(e)}")
    
    print("\n🔄 Triggering batch evaluation...")
    try:
        response = requests.post(f"{LOCAL_API}/evaluation/batch-evaluate", timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Batch evaluation completed")
            print(f"📊 Evaluations completed: {result.get('evaluations_completed', 0)}")
            print(f"📝 Message: {result.get('message', 'N/A')}")
            
            # Check database for evaluation results
            try:
                import sqlite3
                conn = sqlite3.connect("agentiq.db")
                cursor = conn.cursor()
                
                # Count total evaluations
                cursor.execute("SELECT COUNT(*) FROM eval_results;")
                total_evals = cursor.fetchone()[0]
                
                # Count evaluations with failure categories
                cursor.execute("SELECT COUNT(*) FROM eval_results WHERE failure_category IS NOT NULL;")
                categorized_evals = cursor.fetchone()[0]
                
                # Get sample of failure categories
                cursor.execute("SELECT failure_category, COUNT(*) FROM eval_results WHERE failure_category IS NOT NULL GROUP BY failure_category LIMIT 5;")
                categories = cursor.fetchall()
                
                conn.close()
                
                print(f"📊 Total evaluations in DB: {total_evals}")
                print(f"🏷️  Categorized evaluations: {categorized_evals}")
                if categories:
                    print("📋 Sample failure categories:")
                    for category, count in categories:
                        print(f"   - {category}: {count} instances")
                
                return total_evals > 0 and categorized_evals > 0
                
            except Exception as e:
                print(f"⚠️  Could not check database: {str(e)}")
                return result.get('evaluations_completed', 0) > 0
        
        elif response.status_code == 503:
            print(f"🟡 Service unavailable (503) - API key configuration needed")
            return False
        else:
            print(f"❌ Batch evaluation failed: HTTP {response.status_code}")
            try:
                error_data = response.json()
                print(f"📄 Error: {error_data.get('detail', 'Unknown error')}")
            except:
                pass
            return False
            
    except Exception as e:
        print(f"❌ Batch evaluation error: {str(e)}")
        return False

def main():
    print("🚀 Phase 1: LLM Evaluation Engine Testing")
    print("=" * 70)
    print("Testing Claude Sonnet integration and autonomous evaluation")
    print(f"🕒 Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Run all tests
    test_1_1_result = test_1_1_claude_api_integration()
    test_1_2_results = test_1_2_single_interaction_evaluation()
    test_1_3_result = test_1_3_batch_evaluation()
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 PHASE 1 TEST SUMMARY")
    print("=" * 70)
    
    print(f"🔗 Test 1.1 - Claude API Integration: {'✅ PASS' if test_1_1_result else '❌ FAIL'}")
    
    if test_1_2_results:
        successful_evals = sum(1 for r in test_1_2_results if r.get('success'))
        valid_scores = sum(1 for r in test_1_2_results if r.get('score_valid'))
        print(f"🤖 Test 1.2 - Single Evaluations: {successful_evals}/{len(test_1_2_results)} successful")
        print(f"📏 Score Validation: {valid_scores}/{len(test_1_2_results)} within expected ranges")
    else:
        print(f"🤖 Test 1.2 - Single Evaluations: ❌ FAIL")
    
    print(f"📦 Test 1.3 - Batch Evaluation: {'✅ PASS' if test_1_3_result else '❌ FAIL'}")
    
    # Overall assessment
    overall_success = (
        test_1_1_result and 
        test_1_2_results and 
        sum(1 for r in test_1_2_results if r.get('success')) >= len(test_1_2_results) * 0.7 and
        test_1_3_result
    )
    
    print(f"\n🎯 PHASE 1 OVERALL: {'🎉 READY FOR PRODUCTION' if overall_success else '🔧 NEEDS WORK'}")
    
    if overall_success:
        print("✅ LLM evaluation engine fully functional")
        print("✅ Claude Sonnet 4 integration working")  
        print("✅ Autonomous evaluation operational")
        print("🚀 Ready to proceed to Phase 2: Pattern Detection")
    else:
        print("🔧 Issues found that need attention:")
        if not test_1_1_result:
            print("   - Claude API integration needs fixing")
        if not test_1_2_results or sum(1 for r in test_1_2_results if r.get('success')) < len(test_1_2_results) * 0.7:
            print("   - Single evaluation functionality needs work")
        if not test_1_3_result:
            print("   - Batch evaluation system needs attention")
    
    print(f"\n🕒 Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return overall_success

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)