"""Add helpfulness and factuality as built-in scoring dimensions

Revision ID: a7d2e04f8b31
Revises: f3b8c91a4e22
Create Date: 2026-07-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a7d2e04f8b31'
down_revision: Union[str, None] = 'f3b8c91a4e22'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE eval_results ADD COLUMN IF NOT EXISTS helpfulness FLOAT")
    op.execute("ALTER TABLE eval_results ADD COLUMN IF NOT EXISTS factuality FLOAT")
    op.execute("ALTER TABLE agent_quality_configs ADD COLUMN IF NOT EXISTS weight_helpfulness FLOAT DEFAULT 0.1")
    op.execute("ALTER TABLE agent_quality_configs ADD COLUMN IF NOT EXISTS weight_factuality FLOAT DEFAULT 0.1")


def downgrade() -> None:
    op.execute("ALTER TABLE agent_quality_configs DROP COLUMN IF EXISTS weight_factuality")
    op.execute("ALTER TABLE agent_quality_configs DROP COLUMN IF EXISTS weight_helpfulness")
    op.execute("ALTER TABLE eval_results DROP COLUMN IF EXISTS factuality")
    op.execute("ALTER TABLE eval_results DROP COLUMN IF EXISTS helpfulness")
