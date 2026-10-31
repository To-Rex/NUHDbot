"""product color

Revision ID: b7c2f4a91d30
Revises: a3c1d9e7f210
Create Date: 2026-10-31 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c2f4a91d30'
down_revision: Union[str, None] = 'a3c1d9e7f210'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('color', sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column('products', 'color')
