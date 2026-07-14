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
    op.create_table(
        'golden_labels',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('agent_id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('human_passed', sa.Boolean(), nullable=False),
        sa.Column('note', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_id', 'session_id', name='uq_golden_agent_session'),
    )
    op.create_index('ix_golden_labels_agent_id', 'golden_labels', ['agent_id'])
    op.create_index('ix_golden_labels_session_id', 'golden_labels', ['session_id'])


def downgrade() -> None:
    op.drop_index('ix_golden_labels_session_id', table_name='golden_labels')
    op.drop_index('ix_golden_labels_agent_id', table_name='golden_labels')
    op.drop_table('golden_labels')
