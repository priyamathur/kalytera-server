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
def _apply_schema_additions() -> None:
    """Idempotent column/table additions for PostgreSQL when Alembic state may be stale.

    Uses raw psycopg2 with autocommit=True so each DDL statement is committed
    immediately, bypassing SQLAlchemy transaction management entirely.
    """
    if "sqlite" in DATABASE_URL:
        return  # SQLite: create_all() builds the full schema on first run

    ddl_stmts = [
        # Type change must come first (converts INTEGER -> TEXT for existing rows)
        "ALTER TABLE eval_results ALTER COLUMN failure_step TYPE TEXT USING failure_step::TEXT",
        "ALTER TABLE eval_results ADD COLUMN IF NOT EXISTS helpfulness FLOAT",
        "ALTER TABLE eval_results ADD COLUMN IF NOT EXISTS factuality FLOAT",
        "ALTER TABLE eval_results ADD COLUMN IF NOT EXISTS custom_scores TEXT",
        "ALTER TABLE agent_quality_configs ADD COLUMN IF NOT EXISTS weight_helpfulness FLOAT DEFAULT 0.1",
        "ALTER TABLE agent_quality_configs ADD COLUMN IF NOT EXISTS weight_factuality FLOAT DEFAULT 0.1",
        "ALTER TABLE agent_quality_configs ADD COLUMN IF NOT EXISTS custom_metrics TEXT",
        """CREATE TABLE IF NOT EXISTS golden_labels (
            id TEXT NOT NULL PRIMARY KEY,
            agent_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            human_passed BOOLEAN NOT NULL,
            note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_golden_agent_session UNIQUE (agent_id, session_id)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_golden_labels_agent_id ON golden_labels (agent_id)",
        "CREATE INDEX IF NOT EXISTS ix_golden_labels_session_id ON golden_labels (session_id)",
    ]

    raw = engine.raw_connection()
    try:
        raw.autocommit = True          # each DDL commits immediately — no transaction wrapping
        cur = raw.cursor()
        for stmt in ddl_stmts:
            short = stmt.strip().split("\n")[0][:80]
            try:
                cur.execute(stmt)
                print(f"  ✓ schema: {short}")
            except Exception as exc:
                # "already exists" / "already that type" errors are expected on re-deploy
                print(f"  · schema skip ({type(exc).__name__}): {short}")
        cur.close()

        # Verify the two most critical columns actually exist now
        cur2 = raw.cursor()
        cur2.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name IN ('eval_results','agent_quality_configs') "
            "AND column_name IN ('failure_step','helpfulness','factuality',"
            "'weight_helpfulness','weight_factuality') ORDER BY table_name, column_name"
        )
        rows = cur2.fetchall()
        cur2.close()
        for col, dtype in rows:
            print(f"  ✓ verified: {col} ({dtype})")
    finally:
        raw.close()
    print("✅ Schema additions complete")


def initialize_database():
    """Initialize database tables if they don't exist"""
    try:
        from db.models import (  # noqa: F401 — import all models so Base.metadata is fully populated
            Base, AgentLog, EvalResult, LossPattern, AgentQualityConfig,
            Organization, User, ApiKey, UsageRecord,
        )
        print("🔧 Creating database tables...")
        Base.metadata.create_all(bind=engine)
        _apply_schema_additions()
        
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
                all_tables = ", ".join(sorted(Base.metadata.tables.keys()))
                print(f"📋 Tables available: {all_tables}")
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