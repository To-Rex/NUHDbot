"""forget currency picks made while the feature was being tried out

Revision ID: a8d3e6b1c925
Revises: f1c6a8e2d457
Create Date: 2026-11-01 20:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a8d3e6b1c925'
down_revision: Union[str, None] = 'f1c6a8e2d457'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # everyone starts from the shop's main currency (yuan); a new pick is remembered again
    op.execute("UPDATE users SET currency = NULL")


def downgrade() -> None:
    pass
