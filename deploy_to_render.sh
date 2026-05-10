#!/bin/bash
# AgentIQ Render Deployment Script

echo "🚀 AgentIQ Render Deployment"
echo "=========================="

echo "📤 Step 2: Push to GitHub (run manually):"
echo "git push -u origin main"
echo ""

echo "🌐 Step 3: Opening Render for deployment..."

# Open Render Blueprint URL
if command -v open &> /dev/null; then
    open "https://dashboard.render.com/blueprints/new"
    echo "✅ Render dashboard opened in browser"
elif command -v xdg-open &> /dev/null; then
    xdg-open "https://dashboard.render.com/blueprints/new"
    echo "✅ Render dashboard opened in browser"
else
    echo "🔗 Manual URL: https://dashboard.render.com/blueprints/new"
fi

echo ""
echo "🎯 Render Deployment Instructions:"
echo "1. Connect GitHub account (if not already connected)"
echo "2. Select repository: udayshankar/AgentIQ"
echo "3. Render will auto-detect render.yaml"
echo "4. Review services:"
echo "   ✅ PostgreSQL Database (agentiq-db) - Free tier"  
echo "   ✅ Web Service (agentiq-api) - Free tier"
echo "5. Environment variables already configured in render.yaml"
echo "6. Click 'Apply' to start deployment"
echo ""
echo "⏱️  Expected deployment time: ~10 minutes"
echo "📊 Production URL will be: https://agentiq-api.onrender.com"
echo ""
echo "🧪 After deployment, test with:"
echo "python3 load_production_data.py"