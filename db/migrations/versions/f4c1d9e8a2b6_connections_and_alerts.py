"""Connections (Langfuse, LangSmith, Slack) and sent problem alerts

Revision ID: f4c1d9e8a2b6
Revises: e2b7f9a4c6d1
Create Date: 2026-10-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'f4c1d9e8a2b6'
down_revision: Union[str, None] = 'e2b7f9a4c6d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS connections (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            agent_id TEXT,
            settings TEXT NOT NULL DEFAULT '{}',
            secret TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ok',
            last_error TEXT,
            last_synced_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_connections_org_id ON connections (org_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_connections_agent_id ON connections (agent_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS problem_alerts (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL,
            pattern_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_problem_alerts_org_id ON problem_alerts (org_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_problem_alerts_pattern_id ON problem_alerts (pattern_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS problem_alerts")
    op.execute("DROP TABLE IF EXISTS connections")
