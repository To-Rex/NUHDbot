"""a lot says where its drives are: China or Uzbekistan

Revision ID: d0f6b2a7e948
Revises: c9e5a1f4d836
Create Date: 2026-11-09 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'd0f6b2a7e948'
down_revision: Union[str, None] = 'c9e5a1f4d836'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('auctions', sa.Column('location', sa.String(length=2), nullable=True))


def downgrade() -> None:
    op.drop_column('auctions', 'location')
