"""customer interest events: what each customer opened, searched, carted, ordered, bid on — kept for the demand analysis

Revision ID: c9e5a1f4d836
Revises: b8d4f0e3c725
Create Date: 2026-11-09 02:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c9e5a1f4d836'
down_revision: Union[str, None] = 'b8d4f0e3c725'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'interest_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(length=12), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='SET NULL'), nullable=True),
        sa.Column('brand', sa.String(length=60), nullable=True),
        sa.Column('model', sa.String(length=120), nullable=True),
        sa.Column('capacity_gb', sa.Integer(), nullable=True),
        sa.Column('condition', sa.String(length=10), nullable=True),
        sa.Column('purposes', sa.JSON(), nullable=True),
        sa.Column('price', sa.Numeric(12, 2), nullable=True),
        sa.Column('qty', sa.Integer(), nullable=True),
        sa.Column('query', sa.String(length=200), nullable=True),
        sa.Column('results', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for col in ('user_id', 'kind', 'product_id', 'brand', 'capacity_gb', 'created_at'):
        op.create_index(f'ix_interest_events_{col}', 'interest_events', [col])


def downgrade() -> None:
    for col in ('created_at', 'capacity_gb', 'brand', 'product_id', 'kind', 'user_id'):
        op.drop_index(f'ix_interest_events_{col}', table_name='interest_events')
    op.drop_table('interest_events')
