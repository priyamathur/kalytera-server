#!/usr/bin/env python3
"""
Detect AgentIQ production deployment URL and test it
"""

import requests
import time
from typing import Optional

def test_url(url: str) -> dict:
    """Test a URL and return status info"""
    try:
        response = requests.get(f"{url}/health", timeout=10)
        return {
            "url": url,
            "status_code": response.status_code,
            "success": response.status_code == 200,
            "response": response.json() if response.status_code == 200 else response.text[:200],
            "error": None
        }
    except Exception as e:
        return {
            "url": url,
            "status_code": None,
            "success": False,
            "response": None,
            "error": str(e)
        }

def detect_agentiq_production() -> Optional[str]:
    """Try to detect the AgentIQ production URL"""
    
    # Common Render URL patterns for our deployment
    potential_urls = [
        "https://agentiq-api.onrender.com",
        "https://agentiq-api-production.onrender.com", 
        "https://agentiq-backend.onrender.com",
        "https://agentiq-web.onrender.com",
        "https://agentiq-platform.onrender.com",
        "https://udayshankar-agentiq.onrender.com",
        "https://agentiq-udayshankar.onrender.com"
    ]
    
    print("🔍 Detecting AgentIQ production deployment...")
    print("=" * 50)
    
    working_urls = []
    
    for url in potential_urls:
        print(f"Testing: {url}")
        result = test_url(url)
        
        if result["success"]:
            print(f"✅ FOUND: {url}")
            print(f"   Response: {result['response']}")
            working_urls.append(url)
        elif result["status_code"]:
            print(f"❌ HTTP {result['status_code']}: {url}")
        else:
            print(f"❌ Connection failed: {url}")
    
    if working_urls:
        print(f"\n🎉 Found {len(working_urls)} working deployment(s):")
        for url in working_urls:
            print(f"   ✅ {url}")
        return working_urls[0]
    else:
        print("\n❌ No working deployments found")
        return None

def test_agentiq_endpoints(base_url: str):
    """Test key AgentIQ endpoints"""
    
    endpoints = [
        "/health", 
        "/analytics/dashboard-summary",
        "/admin/database-status"
    ]
    
    print(f"\n🧪 Testing AgentIQ endpoints at: {base_url}")
    print("-" * 50)
    
    results = {}
    
    for endpoint in endpoints:
        try:
            response = requests.get(f"{base_url}{endpoint}", timeout=15)
            success = response.status_code == 200
            status = "✅" if success else "❌"
            results[endpoint] = success
            
            print(f"{status} {endpoint}: HTTP {response.status_code}")
            
            if success and endpoint == "/health":
                try:
                    health_data = response.json()
                    db_status = health_data.get('services', {}).get('database', False)
                    intent_status = health_data.get('services', {}).get('intent_classifier', False)
                    print(f"   Database: {'✅' if db_status else '❌'}")
                    print(f"   LLM Judge: {'✅' if intent_status else '⚠️  (expected - needs API key)'}")
                except:
                    pass
                    
        except Exception as e:
            results[endpoint] = False
            print(f"❌ {endpoint}: Error - {str(e)[:50]}...")
    
    working = sum(results.values())
    total = len(results)
    print(f"\n📊 Endpoint Status: {working}/{total} working")
    
    return results

def load_demo_data(base_url: str) -> bool:
    """Load demo data to test the deployment"""
    print(f"\n📦 Loading demo data to: {base_url}")
    
    try:
        response = requests.post(f"{base_url}/admin/seed-sample-data", timeout=30)
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Demo data loaded: {result.get('logs_created', 'unknown')} logs created")
            return True
        else:
            print(f"❌ Demo data failed: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Demo data error: {e}")
        return False

def get_analytics_summary(base_url: str):
    """Get analytics summary"""
    print(f"\n📊 Getting analytics from: {base_url}")
    
    try:
        response = requests.get(f"{base_url}/analytics/dashboard-summary", timeout=15)
        if response.status_code == 200:
            analytics = response.json()
            print("✅ Analytics working:")
            print(f"   Sessions: {analytics.get('total_sessions', 0)}")
            print(f"   Interactions: {analytics.get('total_interactions', 0)}")  
            print(f"   Health Score: {analytics.get('health_score', 0):.1%}")
            print(f"   Completion Rate: {analytics.get('overall_completion_rate', 0):.1%}")
            return analytics
        else:
            print(f"❌ Analytics failed: HTTP {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ Analytics error: {e}")
        return None

def main():
    """Main production detection and testing"""
    print("🤖 AgentIQ Production Deployment Detector")
    print("=" * 50)
    
    # Step 1: Detect production URL
    production_url = detect_agentiq_production()
    
    if not production_url:
        print("\n⚠️  No production deployment detected yet.")
        print("Deployment might still be in progress (~10 minutes)")
        print("\nTry again in a few minutes, or check Render dashboard:")
        print("https://dashboard.render.com/")
        return
    
    # Step 2: Test endpoints
    endpoint_results = test_agentiq_endpoints(production_url)
    
    if not any(endpoint_results.values()):
        print("\n❌ Production deployment not responding correctly")
        return
    
    # Step 3: Load demo data
    print("\n" + "="*50)
    demo_loaded = load_demo_data(production_url)
    
    if demo_loaded:
        print("\n⏳ Waiting 5 seconds for data processing...")
        time.sleep(5)
        
        # Step 4: Get analytics
        analytics = get_analytics_summary(production_url)
        
        if analytics:
            print("\n🎉 AgentIQ Production Deployment SUCCESSFUL!")
            print("=" * 50)
            print(f"🌍 Production URL: {production_url}")
            print(f"🔗 Health Check: {production_url}/health") 
            print(f"📊 Analytics: {production_url}/analytics/dashboard-summary")
            print(f"📈 Sessions Analyzed: {analytics.get('total_sessions', 0)}")
            print("✅ System Status: Fully Operational")
        else:
            print("\n⚠️  Deployment working but analytics need more time")
    else:
        print("\n⚠️  Deployment detected but demo data loading failed")
    
    print("\n🚀 Ready for testing and launch!")
    print(f"Production URL: {production_url}")

if __name__ == "__main__":
    main()