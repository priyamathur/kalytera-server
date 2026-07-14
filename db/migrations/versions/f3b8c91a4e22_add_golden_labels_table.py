"""Add golden_labels table for judge calibration

Revision ID: f3b8c91a4e22
Revises: c4f1a83e2d90
Create Date: 2026-07-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3b8c91a4e22'
down_revision: Union[str, None] = 'c4f1a83e2d90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS golden_labels (
            id TEXT NOT NULL PRIMARY KEY,
            agent_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            human_passed BOOLEAN NOT NULL,
            note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_golden_agent_session UNIQUE (agent_id, session_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_golden_labels_agent_id ON golden_labels (agent_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_golden_labels_session_id ON golden_labels (session_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS golden_labels")
