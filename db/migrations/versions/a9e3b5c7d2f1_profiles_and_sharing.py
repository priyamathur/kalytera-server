"""Agent profiles, the anonymous pattern sharing switch (on by default) and shared facts

Revision ID: a9e3b5c7d2f1
Revises: f4c1d9e8a2b6
Create Date: 2026-10-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a9e3b5c7d2f1'
down_revision: Union[str, None] = 'f4c1d9e8a2b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE agent_orgs ADD COLUMN IF NOT EXISTS industry TEXT")
    op.execute("ALTER TABLE agent_orgs ADD COLUMN IF NOT EXISTS agent_type TEXT")
    op.execute("ALTER TABLE agent_orgs ADD COLUMN IF NOT EXISTS system TEXT")
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS share_patterns BOOLEAN NOT NULL DEFAULT TRUE")
    op.execute("""
        CREATE TABLE IF NOT EXISTS global_facts (
            id TEXT PRIMARY KEY,
            org_hash TEXT NOT NULL,
            industry TEXT NOT NULL,
            agent_type TEXT NOT NULL,
            system TEXT NOT NULL,
            kind TEXT NOT NULL,
            failure_type TEXT NOT NULL DEFAULT '',
            action_category TEXT NOT NULL DEFAULT '',
            rule_shape TEXT NOT NULL DEFAULT '',
            last_seen TIMESTAMPTZ NOT NULL
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_global_facts_org_hash ON global_facts (org_hash)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_global_facts_segment ON global_facts (industry, agent_type)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS global_facts")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS share_patterns")
    for col in ("system", "agent_type", "industry"):
        op.execute(f"ALTER TABLE agent_orgs DROP COLUMN IF EXISTS {col}")
