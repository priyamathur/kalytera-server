"""
Shared database configuration and dependency
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
import os
from dotenv import load_dotenv

load_dotenv(override=True)

# Database setup - Use SQLite with persistent storage for Railway
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agentiq.db")
print(f"🔍 Connecting to database: {DATABASE_URL[:30]}...")

# Create engine with SQLite settings for Railway
if "sqlite" in DATABASE_URL:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Auto-create tables on startup
def initialize_database():
    """Initialize database tables if they don't exist"""
    try:
        from db.models import Base
        print("🔧 Creating database tables...")
        Base.metadata.create_all(bind=engine)
        
        # Verify tables were created by checking for agent_logs table
        with engine.connect() as conn:
            from sqlalchemy import text
            if "sqlite" in DATABASE_URL:
                query = "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_logs';"
            else:
                query = "SELECT tablename FROM pg_tables WHERE tablename='agent_logs';"
            
            result = conn.execute(text(query))
            tables = result.fetchall()
            if tables:
                print("✅ Database tables created/verified successfully")
                print(f"📋 Tables available: agent_logs, session_summaries, eval_results, loss_patterns")
                return True
            else:
                print("⚠️  Tables not found after creation attempt")
                return False
    except Exception as e:
        print(f"⚠️  Database initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False

# Initialize on import
print("🚀 Initializing AgentIQ database...")
init_result = initialize_database()

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()