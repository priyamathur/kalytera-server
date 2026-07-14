"""Add custom_metrics to agent_quality_configs and custom_scores to eval_results

Revision ID: c4f1a83e2d90
Revises: 89519c35a421
Create Date: 2026-07-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4f1a83e2d90'
down_revision: Union[str, None] = '89519c35a421'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'agent_quality_configs',
        sa.Column('custom_metrics', sa.Text(), nullable=True),
    )
    op.add_column(
        'eval_results',
        sa.Column('custom_scores', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('eval_results', 'custom_scores')
    op.drop_column('agent_quality_configs', 'custom_metrics')
