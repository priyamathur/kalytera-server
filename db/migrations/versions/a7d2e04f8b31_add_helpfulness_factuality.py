"""Add helpfulness and factuality as built-in scoring dimensions

Revision ID: a7d2e04f8b31
Revises: f3b8c91a4e22
Create Date: 2026-07-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7d2e04f8b31'
down_revision: Union[str, None] = 'f3b8c91a4e22'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('eval_results', sa.Column('helpfulness', sa.Float(), nullable=True))
    op.add_column('eval_results', sa.Column('factuality', sa.Float(), nullable=True))
    op.add_column('agent_quality_configs', sa.Column('weight_helpfulness', sa.Float(), nullable=True, server_default='0.1'))
    op.add_column('agent_quality_configs', sa.Column('weight_factuality', sa.Float(), nullable=True, server_default='0.1'))


def downgrade() -> None:
    op.drop_column('agent_quality_configs', 'weight_factuality')
    op.drop_column('agent_quality_configs', 'weight_helpfulness')
    op.drop_column('eval_results', 'factuality')
    op.drop_column('eval_results', 'helpfulness')
