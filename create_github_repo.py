#!/usr/bin/env python3
"""
Create GitHub repository using API and push AgentIQ code
"""

import requests
import json
import os
import subprocess

def run_cmd(cmd):
    """Run shell command"""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip(), result.stderr.strip(), result.returncode

def create_github_repo_api():
    """Create GitHub repo via API (requires token)"""
    print("🔧 GitHub API repository creation would require a personal access token.")
    print("📝 Manual creation is more reliable for this demo.")
    
    repo_data = {
        "name": "AgentIQ",
        "description": "Continuous agent evaluation platform with LLM-powered insights",
        "private": False,
        "auto_init": False
    }
    
    print(f"""
🎯 Create this repository manually:
   
1. Go to: https://github.com/new
2. Repository name: {repo_data['name']}
3. Description: {repo_data['description']}
4. Visibility: Public
5. Initialize: NO (we have existing code)
6. Click "Create repository"

Then the script will continue automatically...
    """)
    
    input("Press Enter after creating the repository on GitHub...")
    return "https://github.com/udayshankar/AgentIQ.git"

def push_to_github(repo_url):
    """Push code to GitHub repository"""
    print(f"📤 Pushing AgentIQ to {repo_url}")
    
    # Configure git if needed
    name, _, _ = run_cmd("git config user.name")
    if not name:
        run_cmd('git config user.name "AgentIQ Platform"')
        run_cmd('git config user.email "platform@agentiq.dev"')
    
    # Add all files and commit if needed
    out, err, code = run_cmd("git status --porcelain")
    if out:  # There are unstaged changes
        run_cmd("git add .")
        run_cmd('git commit -m "Final production deployment\n\n🤖 Generated with [Claude Code](https://claude.ai/code)\n\nCo-Authored-By: Claude <noreply@anthropic.com>"')
    
    # Push to GitHub
    print("🚀 Pushing to GitHub...")
    out, err, code = run_cmd("git push -u origin main")
    
    if code != 0:
        print(f"❌ Push failed: {err}")
        if "authentication" in err.lower() or "permission" in err.lower():
            print("""
🔑 Authentication needed! Try one of these:

Option 1 - SSH (recommended):
   git remote set-url origin git@github.com:udayshankar/AgentIQ.git
   git push -u origin main

Option 2 - Personal Access Token:
   git remote set-url origin https://USERNAME:TOKEN@github.com/udayshankar/AgentIQ.git
   git push -u origin main

Create token at: https://github.com/settings/tokens (select 'repo' scope)
            """)
            return False
        else:
            print(f"Error details: {err}")
            return False
    
    print("✅ Code successfully pushed to GitHub!")
    return True

def deploy_to_render():
    """Open Render for Blueprint deployment"""
    print("🚀 Opening Render for deployment...")
    
    render_blueprint_url = "https://dashboard.render.com/blueprints/new"
    
    print(f"""
🎯 Render Deployment (Blueprint Method):

1. Go to: {render_blueprint_url}
2. Connect GitHub account if not already connected
3. Select repository: udayshankar/AgentIQ
4. Render will automatically detect render.yaml
5. Review the services:
   ✅ PostgreSQL Database (agentiq-db) - Free tier
   ✅ Web Service (agentiq-api) - Free tier
6. Environment variables are already configured
7. Click "Apply" to start deployment

⏱️  Expected deployment time: ~10 minutes

📊 You'll get a URL like: https://agentiq-api.onrender.com
    """)
    
    try:
        import webbrowser
        webbrowser.open(render_blueprint_url)
        print("✅ Render dashboard opened in browser")
    except:
        print(f"🔗 Manual URL: {render_blueprint_url}")
    
    return "https://agentiq-api.onrender.com"  # Expected URL

def main():
    """Main deployment flow"""
    print("🤖 AgentIQ Production Deployment")
    print("=" * 40)
    
    # Check we're in the right directory
    if not os.path.exists("render.yaml"):
        print("❌ render.yaml not found. Run from AgentIQ directory.")
        return
    
    print("📦 Current deployment files:")
    files = ["render.yaml", "requirements.txt", "main.py", "api/ingest_endpoints.py"]
    for f in files:
        exists = "✅" if os.path.exists(f) else "❌"
        print(f"   {exists} {f}")
    
    # Step 1: Create GitHub repository
    print("\n🐙 Step 1: GitHub Repository")
    repo_url = create_github_repo_api()
    
    # Step 2: Push code to GitHub  
    print("\n📤 Step 2: Push Code to GitHub")
    if not push_to_github(repo_url):
        print("❌ Cannot proceed without successful GitHub push")
        return
    
    # Step 3: Deploy to Render
    print("\n🚀 Step 3: Deploy to Render")
    expected_url = deploy_to_render()
    
    print(f"""
🎉 Deployment initiated!

📋 Next steps:
   1. Complete Render deployment (~10 minutes)
   2. Test production URL: {expected_url}
   3. Load demo data for testing
   
🔗 Expected production URL: {expected_url}
    """)

if __name__ == "__main__":
    main()