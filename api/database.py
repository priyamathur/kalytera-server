"""
Shared database configuration and dependency.

Two modes (set DATABASE_URL env var to switch):
  SQLite     — default, zero config, for local dev and demos
               DATABASE_URL=sqlite:///./kalytera.db  (or leave unset)
  PostgreSQL — for production
               DATABASE_URL=postgresql://user:pass@host:5432/dbname
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()  # env vars already set in the environment take precedence over .env

# Database setup - Use SQLite with persistent storage for Railway
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./kalytera.db")
print(f"🔍 Connecting to database: {DATABASE_URL[:30]}...")

if "sqlite" in DATABASE_URL:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # External Render URLs contain ".render.com" and require SSL.
    # Internal Render URLs (short hostnames, no domain) and local dev don't need SSL.
    _needs_ssl = ".render.com" in DATABASE_URL and "sslmode=" not in DATABASE_URL
    _connect_args: dict = {"connect_timeout": 10}
    if _needs_ssl:
        _connect_args["sslmode"] = "require"
    engine = create_engine(
        DATABASE_URL,
        connect_args=_connect_args,
        pool_pre_ping=True,
        pool_recycle=300,
    )

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
                print("📋 Tables available: agent_logs, session_summaries, eval_results, loss_patterns")
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
print("🚀 Initializing Kalytera database...")
init_result = initialize_database()

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()