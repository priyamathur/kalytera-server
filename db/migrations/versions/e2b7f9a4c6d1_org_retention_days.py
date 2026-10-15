"""Per-account retention: delete production data older than N days

Revision ID: e2b7f9a4c6d1
Revises: d8a4c2e7f1b3
Create Date: 2026-10-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'e2b7f9a4c6d1'
down_revision: Union[str, None] = 'd8a4c2e7f1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS retention_days INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS retention_days")
