"""
AgentIQ API - Main FastAPI application entry point
Includes all routers and handles CORS for dashboard integration
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os

# Import all routers
from api.ingest_endpoints import app as ingest_app
from api.analytics_endpoints import analytics_router
from api.evaluation_endpoints import evaluation_router
from api.pattern_endpoints import pattern_router

# Create main FastAPI application
app = FastAPI(
    title="AgentIQ API",
    description="Real-time agent monitoring and quality analysis platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware for dashboard integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",  # Streamlit default
        "https://*.railway.app",  # Railway deployments
        "http://localhost:3000",  # React apps
        "http://localhost:8000",  # API itself
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check endpoint
@app.get("/health")
async def health_check():
    """API health check"""
    return {
        "status": "healthy",
        "service": "agentiq-api",
        "version": "1.0.0"
    }

# Mount all routers
app.include_router(analytics_router)
app.include_router(evaluation_router)
app.include_router(pattern_router)

# Include ingest endpoints from the existing ingest app
app.mount("/api", ingest_app)

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "AgentIQ API",
        "description": "Real-time agent monitoring and quality analysis",
        "docs": "/docs",
        "health": "/health",
        "version": "1.0.0"
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=port,
        reload=False  # Disable reload in production
    )