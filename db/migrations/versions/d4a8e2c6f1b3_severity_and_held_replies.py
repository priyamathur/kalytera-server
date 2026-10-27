"""Serious mistakes alert after one; replies stopped before the customer saw them

Revision ID: d4a8e2c6f1b3
Revises: c7e5a1d9b3f2
Create Date: 2026-10-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'd4a8e2c6f1b3'
down_revision: Union[str, None] = 'c7e5a1d9b3f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE eval_results ADD COLUMN IF NOT EXISTS severity TEXT")
    op.execute("""CREATE TABLE IF NOT EXISTS held_replies (
        id TEXT PRIMARY KEY, org_id TEXT, agent_id TEXT NOT NULL, session_id TEXT NOT NULL DEFAULT '',
        reply TEXT NOT NULL, reason TEXT NOT NULL, checked_by TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_held_replies_org_id ON held_replies (org_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_held_replies_agent_id ON held_replies (agent_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_held_replies_created_at ON held_replies (created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS held_replies")
    op.execute("ALTER TABLE eval_results DROP COLUMN IF EXISTS severity")
