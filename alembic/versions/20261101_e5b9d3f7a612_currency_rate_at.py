"""currency rate_at

Revision ID: e5b9d3f7a612
Revises: d2a7c5e1b384
Create Date: 2026-11-01 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5b9d3f7a612'
down_revision: Union[str, None] = 'd2a7c5e1b384'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('currencies', sa.Column('rate_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    op.execute("UPDATE currencies SET rate_at = updated_at")


def downgrade() -> None:
    op.drop_column('currencies', 'rate_at')
