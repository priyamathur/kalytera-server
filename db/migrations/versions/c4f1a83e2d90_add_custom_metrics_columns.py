"""Add custom_metrics to agent_quality_configs and custom_scores to eval_results

Revision ID: c4f1a83e2d90
Revises: 89519c35a421
Create Date: 2026-07-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c4f1a83e2d90'
down_revision: Union[str, None] = '89519c35a421'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE agent_quality_configs ADD COLUMN IF NOT EXISTS custom_metrics TEXT")
    op.execute("ALTER TABLE eval_results ADD COLUMN IF NOT EXISTS custom_scores TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE eval_results DROP COLUMN IF EXISTS custom_scores")
    op.execute("ALTER TABLE agent_quality_configs DROP COLUMN IF EXISTS custom_metrics")
