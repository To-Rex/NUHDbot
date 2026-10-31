"""currency is_default (shown first in the Mini App)

Revision ID: f1c6a8e2d457
Revises: e5b9d3f7a612
Create Date: 2026-11-01 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1c6a8e2d457'
down_revision: Union[str, None] = 'e5b9d3f7a612'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('currencies', sa.Column('is_default', sa.Boolean(), server_default=sa.false(), nullable=False))
    # the shop asked for prices in yuan first; staff can pick another one on the Currencies page
    op.execute("UPDATE currencies SET is_default = true WHERE code = 'CNY'")
    op.execute("UPDATE currencies SET is_active = true WHERE code = 'CNY'")


def downgrade() -> None:
    op.drop_column('currencies', 'is_default')
