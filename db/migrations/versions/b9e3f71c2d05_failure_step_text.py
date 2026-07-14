"""Change failure_step from INTEGER to TEXT

Revision ID: b9e3f71c2d05
Revises: a7d2e04f8b31
Create Date: 2026-07-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'b9e3f71c2d05'
down_revision: Union[str, None] = 'a7d2e04f8b31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE eval_results ALTER COLUMN failure_step TYPE TEXT USING failure_step::TEXT"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE eval_results ALTER COLUMN failure_step TYPE INTEGER USING failure_step::INTEGER"
    )
