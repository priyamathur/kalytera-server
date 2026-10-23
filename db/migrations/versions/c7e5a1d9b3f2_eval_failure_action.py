"""The action a failed conversation's mistake was about; problems group by it

Revision ID: c7e5a1d9b3f2
Revises: a9e3b5c7d2f1
Create Date: 2026-10-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c7e5a1d9b3f2'
down_revision: Union[str, None] = 'a9e3b5c7d2f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE eval_results ADD COLUMN IF NOT EXISTS failure_action TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE eval_results DROP COLUMN IF EXISTS failure_action")
