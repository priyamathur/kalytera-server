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
    """Idempotent schema migrations for PostgreSQL when Alembic state may be stale.

    Strategy: read current schema state first (no locks), then only run DDL for
    what is actually missing or wrong. On a healthy deploy this does zero DDL and
    takes zero locks — eliminating the deploy-time deadlock risk.
    """
    if "sqlite" in DATABASE_URL:
        return  # SQLite: create_all() builds the full schema on first run

    raw = engine.raw_connection()
    try:
        raw.autocommit = True  # each DDL commits immediately
        cur = raw.cursor()

        # ── 1. Snapshot current column state (read-only, no locks) ──────────
        cur.execute("""
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_name IN ('eval_results', 'agent_quality_configs')
              AND column_name IN (
                'failure_step', 'helpfulness', 'factuality', 'custom_scores',
                'weight_helpfulness', 'weight_factuality', 'custom_metrics'
              )
        """)
        cols: dict = {(r[0], r[1]): r[2] for r in cur.fetchall()}

        cur.execute("SELECT to_regclass('public.golden_labels')")
        golden_exists: bool = cur.fetchone()[0] is not None  # type: ignore[index]

        # ── 2. Only run DDL for what is actually needed ──────────────────────
        def _ddl(stmt: str) -> None:
            try:
                cur.execute(stmt)
                print(f"  ✓ schema: {stmt.strip().split(chr(10))[0][:80]}")
            except Exception as exc:
                print(f"  · schema err: {stmt.strip()[:60]} — {exc}")

        fs_type = cols.get(("eval_results", "failure_step"), "")
        if "int" in fs_type.lower():
            _ddl("ALTER TABLE eval_results ALTER COLUMN failure_step TYPE TEXT USING failure_step::TEXT")

        if ("eval_results", "helpfulness") not in cols:
            _ddl("ALTER TABLE eval_results ADD COLUMN helpfulness FLOAT")
        if ("eval_results", "factuality") not in cols:
            _ddl("ALTER TABLE eval_results ADD COLUMN factuality FLOAT")
        if ("eval_results", "custom_scores") not in cols:
            _ddl("ALTER TABLE eval_results ADD COLUMN custom_scores TEXT")
        if ("agent_quality_configs", "weight_helpfulness") not in cols:
            _ddl("ALTER TABLE agent_quality_configs ADD COLUMN weight_helpfulness FLOAT DEFAULT 0.1")
        if ("agent_quality_configs", "weight_factuality") not in cols:
            _ddl("ALTER TABLE agent_quality_configs ADD COLUMN weight_factuality FLOAT DEFAULT 0.1")
        if ("agent_quality_configs", "custom_metrics") not in cols:
            _ddl("ALTER TABLE agent_quality_configs ADD COLUMN custom_metrics TEXT")

        if not golden_exists:
            _ddl("""CREATE TABLE golden_labels (
                id TEXT NOT NULL PRIMARY KEY,
                agent_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                human_passed BOOLEAN NOT NULL,
                note TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_golden_agent_session UNIQUE (agent_id, session_id)
            )""")
            _ddl("CREATE INDEX ix_golden_labels_agent_id ON golden_labels (agent_id)")
            _ddl("CREATE INDEX ix_golden_labels_session_id ON golden_labels (session_id)")

        cur.close()
    finally:
        raw.close()
    print("✅ Schema verified")


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