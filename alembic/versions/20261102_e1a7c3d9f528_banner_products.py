"""banners: several products or every discounted one

Revision ID: e1a7c3d9f528
Revises: d8b4f2c6a193
Create Date: 2026-11-02 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e1a7c3d9f528'
down_revision: Union[str, None] = 'd8b4f2c6a193'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('banners', sa.Column('product_ids', sa.JSON(), server_default=sa.text("'[]'"), nullable=False))
    op.add_column('banners', sa.Column('auto_sale', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    op.drop_column('banners', 'auto_sale')
    op.drop_column('banners', 'product_ids')
