"""
AgentIQ FastAPI application entry point
"""

from api.ingest_endpoints import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)