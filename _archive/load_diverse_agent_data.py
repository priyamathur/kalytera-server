"""
Load diverse agent data across multiple agent types for AgentIQ testing
Simulates real-world usage: coding, customer service, data science, sales/BDR, marketing
"""

import requests
import random

API_BASE = "https://agentiq-api-z9it.onrender.com"

# Diverse agent scenarios across different domains
AGENT_SCENARIOS = [
    # Coding Assistants
    {
        "intent": "code_generation",
        "user_inputs": [
            "Write a function to merge two sorted arrays",
            "Create a REST API endpoint for user authentication",
            "Implement a binary search algorithm",
            "Write a React component for user profiles"
        ],
        "responses": [
            "def merge_sorted(arr1, arr2):\n    result = []\n    i = j = 0\n    while i < len(arr1) and j < len(arr2):\n        if arr1[i] <= arr2[j]:\n            result.append(arr1[i])\n            i += 1\n        else:\n            result.append(arr2[j])\n            j += 1\n    return result + arr1[i:] + arr2[j:]",
            "@app.post('/auth/login')\nasync def login(credentials: LoginRequest):\n    user = authenticate_user(credentials.username, credentials.password)\n    if user:\n        token = create_access_token(user.id)\n        return {'access_token': token, 'user': user}\n    raise HTTPException(401, 'Invalid credentials')"
        ]
    },
    {
        "intent": "debugging", 
        "user_inputs": [
            "Why is my Python code throwing IndexError?",
            "Debug this SQL query returning wrong results",
            "Fix this JavaScript async/await issue",
            "My React component won't re-render"
        ],
        "responses": [
            "IndexError usually means you're accessing an array index that doesn't exist. Check your loop bounds and ensure the index is within range using len(array).",
            "The SQL query issue is likely in your JOIN clause. Make sure you're joining on the correct foreign key relationships and check for NULL values."
        ]
    },
    
    # Customer Service
    {
        "intent": "billing",
        "user_inputs": [
            "I don't understand this charge on my account",
            "Why was I billed twice this month?",
            "Can you explain my invoice?",
            "I want to dispute a charge"
        ],
        "responses": [
            "I can help you understand your billing. Let me look up your account details and explain each charge on your statement.",
            "I see the duplicate charge on your account. This appears to be a processing error. I'll initiate a refund for the duplicate payment right away."
        ]
    },
    {
        "intent": "refunds",
        "user_inputs": [
            "I want to cancel my subscription and get a refund",
            "Can I get my money back for this purchase?",
            "I was charged for something I didn't order",
            "Process a refund for my last payment"
        ],
        "responses": [
            "I can help you with your refund request. Let me review your account and recent purchases to determine what refunds you're eligible for.",
            "I've processed your refund request. The amount will be credited back to your original payment method within 5-7 business days."
        ]
    },
    {
        "intent": "technical_support",
        "user_inputs": [
            "The app keeps crashing when I try to upload files",
            "I can't log into my account",
            "The website is loading very slowly",
            "My data isn't syncing between devices"
        ],
        "responses": [
            "I'm sorry you're experiencing app crashes. This is usually caused by file size limits or unsupported file types. Let me help you troubleshoot this issue.",
            "Let's troubleshoot your login issue. First, please try resetting your password. If that doesn't work, I'll check if your account has been temporarily locked."
        ]
    },
    
    # Data Science
    {
        "intent": "data_analysis",
        "user_inputs": [
            "Analyze this dataset for trends and patterns",
            "What's the correlation between these variables?",
            "Help me understand this statistical test result",
            "Identify outliers in my data"
        ],
        "responses": [
            "Based on your dataset, I can see several interesting trends. The main pattern shows a 23% increase in user engagement during weekends, with a strong correlation (r=0.78) between session duration and conversion rates.",
            "The correlation analysis shows a moderate positive relationship (r=0.64, p<0.01) between these variables, suggesting they move together but other factors also influence the relationship."
        ]
    },
    {
        "intent": "visualization",
        "user_inputs": [
            "Create a chart showing sales trends over time",
            "Make a scatter plot of these two variables",
            "Design a dashboard for this KPI data",
            "Build a heatmap of user activity"
        ],
        "responses": [
            "I'll create a time series chart showing your sales trends. Based on your data, I recommend using a line chart with trend lines to highlight the 15% monthly growth pattern.",
            "Here's a scatter plot showing the relationship between your variables. I've added a regression line and color-coded the points by category to make patterns more visible."
        ]
    },
    
    # Sales/BDR
    {
        "intent": "lead_qualification",
        "user_inputs": [
            "Help me qualify this inbound lead",
            "What questions should I ask this prospect?",
            "Is this lead ready for sales?",
            "Score this lead based on our criteria"
        ],
        "responses": [
            "Based on the lead information, this prospect scores 8/10 on our qualification criteria. They have budget authority, a clear pain point, and are in our target market. I recommend scheduling a discovery call.",
            "Here are the key qualification questions to ask: 1) What's driving your need for a solution now? 2) Who else is involved in the decision? 3) What's your timeline? 4) What budget range are you working with?"
        ]
    },
    {
        "intent": "prospecting",
        "user_inputs": [
            "Find similar companies to our best customers",
            "Research this prospect's company background",
            "What's the best way to reach this decision maker?",
            "Help me find the right contact at this company"
        ],
        "responses": [
            "I've identified 15 companies similar to your top customers. They're all mid-market SaaS companies with 100-500 employees in the same industry, showing similar growth patterns and technology needs.",
            "Based on my research, the best approach for this prospect is LinkedIn outreach. They're active on the platform and have engaged with similar content. I suggest mentioning their recent funding round as a conversation starter."
        ]
    },
    
    # Marketing
    {
        "intent": "content_creation",
        "user_inputs": [
            "Write a blog post about industry trends",
            "Create social media content for this campaign",
            "Draft an email newsletter",
            "Generate ad copy for this product"
        ],
        "responses": [
            "Here's a blog post draft on the latest industry trends. I've focused on the three major shifts happening in your market and included actionable insights your audience can implement immediately.",
            "I've created a series of social media posts for your campaign. Each post is optimized for different platforms with relevant hashtags and engaging visuals suggestions."
        ]
    },
    {
        "intent": "campaign_analysis",
        "user_inputs": [
            "Analyze the performance of our recent campaign",
            "Which marketing channels are working best?",
            "What's our ROI on this ad spend?",
            "Compare this campaign to our previous ones"
        ],
        "responses": [
            "Your recent campaign generated a 3.2x ROAS with 847 qualified leads. Email marketing was your top performer (45% of conversions), followed by LinkedIn ads (32%) and organic search (23%).",
            "Based on the data, your paid social campaigns are outperforming search ads by 67% in terms of cost per acquisition. I recommend reallocating 30% of your search budget to social."
        ]
    }
]

def generate_diverse_session_batch(batch_size=500):
    """Generate a batch of diverse agent sessions across different domains"""
    sessions = []
    
    for i in range(batch_size):
        session_id = f"diverse-agent-{i:06d}"
        scenario = random.choice(AGENT_SCENARIOS)
        
        # Multi-step conversation
        steps = random.randint(1, 3)
        interactions = []
        
        for step in range(1, steps + 1):
            user_input = random.choice(scenario["user_inputs"])
            agent_response = random.choice(scenario["responses"])
            
            # Add some variation for follow-up steps
            if step > 1:
                follow_ups = [
                    f"Can you also {user_input.lower()}",
                    f"Additionally, {user_input.lower()}",
                    f"Follow up: {user_input}",
                    f"Thanks! Now {user_input.lower()}"
                ]
                user_input = random.choice(follow_ups)
                agent_response = f"Certainly! {agent_response}"
            
            interaction = {
                "user_input": user_input,
                "agent_response": agent_response,
                "session_id": session_id,
                "response_time_ms": random.randint(800, 4000),  # Realistic response times
                "workflow_step": step,
                "intent": scenario["intent"],
                "tool_calls": "[]" if random.random() > 0.4 else '[{"name": "search_tool", "result": "success"}]'
            }
            interactions.append(interaction)
        
        sessions.extend(interactions)
    
    return sessions

def load_diverse_data_in_batches(total_sessions=5000, batch_size=500):
    """Load diverse agent data across all agent types"""
    
    print(f"Loading {total_sessions} diverse agent sessions across multiple domains...")
    print("Agent types: Coding, Customer Service, Data Science, Sales/BDR, Marketing")
    
    batches = total_sessions // batch_size
    for batch_num in range(batches):
        print(f"Loading batch {batch_num + 1}/{batches} ({batch_size} sessions)...")
        
        sessions = generate_diverse_session_batch(batch_size)
        
        # Send to AgentIQ API
        try:
            response = requests.post(
                f"{API_BASE}/ingest/json",
                json={"data": sessions},
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                processed = result.get('interactions_processed', 0)
                print(f"✅ Batch {batch_num + 1}: {processed} interactions across {len(set(s['intent'] for s in sessions))} intent types")
            else:
                print(f"❌ Batch {batch_num + 1} failed: {response.status_code} - {response.text}")
                
        except Exception as e:
            print(f"❌ Batch {batch_num + 1} error: {e}")
    
    print(f"🎉 Completed loading {total_sessions} diverse agent sessions!")
    print("Dashboard should now show data from multiple agent types")

if __name__ == "__main__":
    # Load 5,000 diverse agent sessions across all domains
    load_diverse_data_in_batches(total_sessions=5000, batch_size=500)