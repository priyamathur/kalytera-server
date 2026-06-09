"""
Load thousands of realistic coding agent sessions for AgentIQ testing
Simulates real-world coding assistant usage patterns
"""

import requests
import random

API_BASE = "https://agentiq-api-z9it.onrender.com"

# Realistic coding tasks and responses
CODING_SCENARIOS = [
    # Code Generation
    {
        "intent": "code_generation",
        "user_inputs": [
            "Write a function to merge two sorted arrays",
            "Create a binary search algorithm", 
            "Implement a stack data structure",
            "Write a function to find palindromes",
            "Create a REST API endpoint for user login",
            "Implement quicksort algorithm",
            "Write a decorator for timing functions",
            "Create a class for handling database connections"
        ],
        "responses": [
            "def merge_sorted(arr1, arr2):\n    result = []\n    i = j = 0\n    while i < len(arr1) and j < len(arr2):\n        if arr1[i] <= arr2[j]:\n            result.append(arr1[i])\n            i += 1\n        else:\n            result.append(arr2[j])\n            j += 1\n    return result + arr1[i:] + arr2[j:]",
            "def binary_search(arr, target):\n    left, right = 0, len(arr) - 1\n    while left <= right:\n        mid = (left + right) // 2\n        if arr[mid] == target:\n            return mid\n        elif arr[mid] < target:\n            left = mid + 1\n        else:\n            right = mid - 1\n    return -1",
            "class Stack:\n    def __init__(self):\n        self.items = []\n    \n    def push(self, item):\n        self.items.append(item)\n    \n    def pop(self):\n        if not self.is_empty():\n            return self.items.pop()\n        return None\n    \n    def is_empty(self):\n        return len(self.items) == 0"
        ]
    },
    # Debugging
    {
        "intent": "debugging",
        "user_inputs": [
            "Why is my Python code throwing IndexError?",
            "Debug this SQL query that's returning wrong results",
            "Fix this JavaScript async/await issue",
            "My React component won't re-render, help debug",
            "Why is my API returning 500 errors?",
            "Debug memory leak in this Python script",
            "Fix this CSS layout that's broken on mobile"
        ],
        "responses": [
            "IndexError usually means you're trying to access an array index that doesn't exist. Check your loop bounds and ensure the index is within range using len(array).",
            "The SQL query issue is likely in your JOIN clause. Make sure you're joining on the correct foreign key relationships and check for NULL values that might affect your results.",
            "For async/await issues, ensure you're using 'await' keyword before async function calls and that your function is declared as 'async'. Also check error handling with try/catch.",
        ]
    },
    # Code Review
    {
        "intent": "code_review",
        "user_inputs": [
            "Review this Python function for best practices",
            "Is this React component efficient?",
            "Check this SQL query for optimization",
            "Review this API design for security issues",
            "Improve this algorithm's time complexity"
        ],
        "responses": [
            "The function looks good but could be improved by: 1) Adding type hints, 2) Using more descriptive variable names, 3) Adding docstring, 4) Handling edge cases like empty inputs.",
            "The React component has unnecessary re-renders. Consider using React.memo() and useCallback for optimization. Also move static data outside the component.",
            "The SQL query can be optimized by: 1) Adding indexes on frequently queried columns, 2) Using EXISTS instead of IN for large datasets, 3) Limiting results with proper pagination."
        ]
    },
    # API Development  
    {
        "intent": "api_development",
        "user_inputs": [
            "Create a FastAPI endpoint for file upload",
            "Build a GraphQL query for user data",
            "Design REST API for e-commerce cart",
            "Implement JWT authentication middleware",
            "Create webhook handler for payments"
        ],
        "responses": [
            "@app.post('/upload')\nasync def upload_file(file: UploadFile = File(...)):\n    contents = await file.read()\n    # Save file logic here\n    return {'filename': file.filename, 'size': len(contents)}",
            "type Query {\n  user(id: ID!): User\n  users(limit: Int, offset: Int): [User]\n}\n\ntype User {\n  id: ID!\n  name: String!\n  email: String!\n  posts: [Post]\n}",
            "@app.post('/cart/add')\nasync def add_to_cart(item: CartItem, user_id: str = Depends(get_current_user)):\n    cart = get_user_cart(user_id)\n    cart.add_item(item)\n    return {'success': True, 'cart_total': cart.total}"
        ]
    }
]

def generate_session_batch(batch_size=1000):
    """Generate a batch of realistic coding sessions"""
    sessions = []
    
    for i in range(batch_size):
        session_id = f"coding-{i:06d}"
        scenario = random.choice(CODING_SCENARIOS)
        
        # Multi-step conversation
        steps = random.randint(1, 4)
        interactions = []
        
        for step in range(1, steps + 1):
            user_input = random.choice(scenario["user_inputs"])
            agent_response = random.choice(scenario["responses"])
            
            # Add some variation to responses
            if step > 1:
                user_input = f"Can you also {user_input.lower()}"
                agent_response = f"Sure! {agent_response}"
            
            interaction = {
                "user_input": user_input,
                "agent_response": agent_response,
                "session_id": session_id,
                "response_time_ms": random.randint(500, 3000),
                "workflow_step": step,
                "intent": scenario["intent"],
                "tool_calls": "[]" if random.random() > 0.3 else '[{"name": "code_executor", "result": "success"}]'
            }
            interactions.append(interaction)
        
        sessions.extend(interactions)
    
    return sessions

def load_data_in_batches(total_sessions=10000, batch_size=1000):
    """Load massive amounts of coding agent data"""
    
    print(f"Loading {total_sessions} coding agent sessions...")
    
    batches = total_sessions // batch_size
    for batch_num in range(batches):
        print(f"Loading batch {batch_num + 1}/{batches} ({batch_size} sessions)...")
        
        sessions = generate_session_batch(batch_size)
        
        # Send to AgentIQ API
        try:
            response = requests.post(
                f"{API_BASE}/ingest/json",
                json={"data": sessions},
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Batch {batch_num + 1}: {result.get('sessions_processed', 0)} sessions, {result.get('interactions_processed', 0)} interactions")
            else:
                print(f"❌ Batch {batch_num + 1} failed: {response.status_code} - {response.text}")
                
        except Exception as e:
            print(f"❌ Batch {batch_num + 1} error: {e}")
    
    print(f"🎉 Completed loading {total_sessions} coding agent sessions!")

if __name__ == "__main__":
    # Load 10,000 realistic coding agent sessions
    load_data_in_batches(total_sessions=10000, batch_size=500)