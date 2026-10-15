"""Keep the judge's own verdict when a person overrules it

Revision ID: d8a4c2e7f1b3
Revises: b9e3f71c2d05
Create Date: 2026-10-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd8a4c2e7f1b3'
down_revision: Union[str, None] = 'b9e3f71c2d05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE eval_results ADD COLUMN IF NOT EXISTS judge_passed BOOLEAN")


def downgrade() -> None:
    op.execute("ALTER TABLE eval_results DROP COLUMN IF EXISTS judge_passed")
