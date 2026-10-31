"""staff nav layout

Revision ID: c4e8a2d6f913
Revises: b7c2f4a91d30
Create Date: 2026-11-01 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c4e8a2d6f913'
down_revision: Union[str, None] = 'b7c2f4a91d30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('nav_layout', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'nav_layout')
