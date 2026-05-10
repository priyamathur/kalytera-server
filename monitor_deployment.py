#!/usr/bin/env python3
"""
Monitor AgentIQ deployment progress and test when ready
"""

import time
import subprocess
from datetime import datetime

def run_detection():
    """Run the production detection script"""
    try:
        result = subprocess.run(
            ["python3", "detect_production.py"], 
            capture_output=True, 
            text=True,
            timeout=60
        )
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)

def monitor_deployment(max_wait_minutes=20, check_interval_seconds=60):
    """Monitor deployment until it's ready or timeout"""
    
    print("🔄 AgentIQ Deployment Monitor")
    print("=" * 40)
    print(f"⏰ Max wait time: {max_wait_minutes} minutes")
    print(f"🔍 Check interval: {check_interval_seconds} seconds")
    print(f"🕐 Started at: {datetime.now().strftime('%H:%M:%S')}")
    print()
    
    start_time = time.time()
    max_wait_seconds = max_wait_minutes * 60
    check_count = 0
    
    while time.time() - start_time < max_wait_seconds:
        check_count += 1
        elapsed = int(time.time() - start_time)
        remaining = max_wait_seconds - elapsed
        
        print(f"🔍 Check #{check_count} (Elapsed: {elapsed//60}m {elapsed%60}s, Remaining: {remaining//60}m {remaining%60}s)")
        
        success, stdout, stderr = run_detection()
        
        if success and "AgentIQ Production Deployment SUCCESSFUL!" in stdout:
            print("🎉 DEPLOYMENT SUCCESSFUL!")
            print(stdout.split("AgentIQ Production Deployment SUCCESSFUL!")[-1])
            return True
        elif "No working deployments found" in stdout:
            print("⏳ Still deploying...")
        elif stderr:
            print(f"⚠️  Error: {stderr[:100]}...")
        else:
            print("🔄 Checking again...")
        
        if remaining > check_interval_seconds:
            print(f"⏸️  Waiting {check_interval_seconds} seconds...")
            time.sleep(check_interval_seconds)
        else:
            print("⏰ Final check...")
            break
    
    print("\n⏰ Monitor timeout reached")
    print("💡 Deployment may still be in progress. Check Render dashboard:")
    print("   https://dashboard.render.com/")
    return False

def main():
    """Main monitoring function"""
    
    # First do an immediate check
    print("🚀 Initial deployment status check...")
    success, stdout, stderr = run_detection()
    
    if success and "AgentIQ Production Deployment SUCCESSFUL!" in stdout:
        print("✅ Deployment already complete!")
        return
    elif "No working deployments found" in stdout:
        print("⏳ Deployment in progress, starting monitor...")
        success = monitor_deployment()
        
        if success:
            print("\n🎯 Next steps:")
            print("1. ✅ Production deployment complete")
            print("2. 📊 Demo data loaded")  
            print("3. 🚀 Ready for launch!")
        else:
            print("\n📝 Manual check recommended:")
            print("1. Visit: https://dashboard.render.com/")
            print("2. Check deployment logs")
            print("3. Verify services are running")
    else:
        print(f"⚠️  Unexpected result: {stdout[:200]}...")

if __name__ == "__main__":
    main()