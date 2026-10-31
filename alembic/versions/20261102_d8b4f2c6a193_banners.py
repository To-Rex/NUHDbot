"""banners for the Mini App home slider

Revision ID: d8b4f2c6a193
Revises: c6e2a9f4b871
Create Date: 2026-11-02 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd8b4f2c6a193'
down_revision: Union[str, None] = 'c6e2a9f4b871'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'banners',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('title', sa.JSON(), nullable=False),
        sa.Column('subtitle', sa.JSON(), nullable=False),
        sa.Column('badge', sa.String(length=24), nullable=True),
        sa.Column('color', sa.String(length=16), nullable=False),
        sa.Column('image', sa.String(length=255), nullable=True),
        sa.Column('image_thumb', sa.String(length=255), nullable=True),
        sa.Column('product_id', sa.Integer(), nullable=True),
        sa.Column('link', sa.String(length=255), nullable=True),
        sa.Column('old_price', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('sort', sa.Integer(), nullable=False),
        sa.Column('clicks', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('banners')
