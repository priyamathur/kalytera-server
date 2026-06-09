#!/usr/bin/env python3
"""
Load demo data to production AgentIQ deployment
"""

import requests
import time
from typing import Dict, Any

def test_production_health(base_url: str) -> bool:
    """Test if production deployment is healthy"""
    try:
        response = requests.get(f"{base_url}/health", timeout=10)
        if response.status_code == 200:
            health_data = response.json()
            print(f"✅ Production health: {health_data}")
            return True
        else:
            print(f"❌ Health check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Cannot reach production: {e}")
        return False

def load_demo_data(base_url: str, num_sessions: int = 100) -> Dict[str, Any]:
    """Load demo data to production deployment"""
    print(f"📤 Loading {num_sessions} demo sessions to {base_url}...")
    
    try:
        # Use the production demo data creation endpoint
        response = requests.post(
            f"{base_url}/admin/seed-sample-data", 
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Sample data loaded: {result}")
            return result
        else:
            print(f"❌ Failed to load data: {response.status_code} - {response.text}")
            return {"success": False, "error": response.text}
            
    except Exception as e:
        print(f"❌ Error loading demo data: {e}")
        return {"success": False, "error": str(e)}

def verify_analytics(base_url: str) -> Dict[str, Any]:
    """Verify analytics are working on production"""
    print("📊 Verifying production analytics...")
    
    try:
        response = requests.get(f"{base_url}/analytics/dashboard-summary", timeout=15)
        
        if response.status_code == 200:
            analytics = response.json()
            print("✅ Analytics working:")
            print(f"   Total sessions: {analytics.get('total_sessions', 0)}")
            print(f"   Health score: {analytics.get('health_score', 0):.1%}")
            print(f"   Dropoff rate: {analytics.get('dropoff_rate', 0):.1%}")
            return analytics
        else:
            print(f"❌ Analytics failed: {response.status_code}")
            return {"error": f"HTTP {response.status_code}"}
            
    except Exception as e:
        print(f"❌ Analytics error: {e}")
        return {"error": str(e)}

def test_key_endpoints(base_url: str) -> Dict[str, bool]:
    """Test key production endpoints"""
    print("🔍 Testing key production endpoints...")
    
    endpoints = {
        "health": "/health",
        "dashboard_summary": "/analytics/dashboard-summary",
        "top_intents": "/analytics/top-intents",
        "patterns": "/patterns/insights/top-intents"
    }
    
    results = {}
    
    for name, endpoint in endpoints.items():
        try:
            response = requests.get(f"{base_url}{endpoint}", timeout=10)
            success = response.status_code == 200
            results[name] = success
            status = "✅" if success else "❌"
            print(f"   {status} {endpoint}: {response.status_code}")
        except Exception as e:
            results[name] = False
            print(f"   ❌ {endpoint}: Error - {e}")
    
    return results

def main():
    """Main production testing flow"""
    print("🚀 AgentIQ Production Data Loader & Tester")
    print("=" * 50)
    
    # Common production URLs for Render
    production_urls = [
        "https://agentiq-api.onrender.com",
        "https://agentiq.onrender.com", 
        "https://agentiq-production.onrender.com"
    ]
    
    print("🔍 Detecting production URL...")
    
    production_url = None
    for url in production_urls:
        print(f"   Testing: {url}")
        if test_production_health(url):
            production_url = url
            print(f"✅ Found production at: {url}")
            break
        time.sleep(2)
    
    if not production_url:
        print("\n❌ No production deployment found.")
        print("📝 Manual production URL entry:")
        production_url = input("Enter your production URL (e.g., https://your-app.onrender.com): ").strip()
        
        if not production_url:
            print("❌ No production URL provided. Exiting.")
            return
        
        if not test_production_health(production_url):
            print("❌ Production URL not responding. Please check deployment.")
            return
    
    print(f"\n🎯 Testing production at: {production_url}")
    
    # Step 1: Test endpoints
    endpoint_results = test_key_endpoints(production_url)
    working_endpoints = sum(endpoint_results.values())
    total_endpoints = len(endpoint_results)
    
    print(f"\n📊 Endpoint Status: {working_endpoints}/{total_endpoints} working")
    
    # Step 2: Load demo data
    print("\n📦 Loading demo data...")
    load_result = load_demo_data(production_url)
    
    if load_result.get("success"):
        print("✅ Demo data loaded successfully")
        
        # Step 3: Wait and verify analytics
        print("\n⏳ Waiting 10 seconds for data processing...")
        time.sleep(10)
        
        analytics = verify_analytics(production_url)
        
        if "error" not in analytics:
            print("\n🎉 Production deployment fully functional!")
            
            # Generate production summary
            print(f"""
📋 Production Summary:
   🌍 URL: {production_url}
   ✅ Health: Operational
   📊 Sessions: {analytics.get('total_sessions', 0)}
   💯 Health Score: {analytics.get('health_score', 0):.1%}
   📈 Quality Score: {analytics.get('avg_quality_score', 0):.1f}
   🎯 Completion Rate: {analytics.get('overall_completion_rate', 0):.1%}
   
🚀 Ready for launch! 
            """)
        else:
            print("⚠️  Analytics not working yet - may need more time")
    else:
        print("❌ Demo data loading failed")
    
    print("\n🔗 Production URLs:")
    print(f"   API: {production_url}")
    print(f"   Health: {production_url}/health")
    print(f"   Analytics: {production_url}/analytics/dashboard-summary")

if __name__ == "__main__":
    main()