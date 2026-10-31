"""currencies

Revision ID: d2a7c5e1b384
Revises: c4e8a2d6f913
Create Date: 2026-11-01 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd2a7c5e1b384'
down_revision: Union[str, None] = 'c4e8a2d6f913'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    currencies = op.create_table(
        'currencies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=3), nullable=False),
        sa.Column('name', sa.String(length=40), nullable=False),
        sa.Column('symbol', sa.String(length=8), nullable=False),
        sa.Column('symbol_first', sa.Boolean(), nullable=False),
        sa.Column('rate', sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column('decimals', sa.Integer(), nullable=False),
        sa.Column('is_base', sa.Boolean(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('sort', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )
    # products are priced in USD: it is the base every other rate is entered against
    op.bulk_insert(currencies, [{'code': 'USD', 'name': 'Dollar', 'symbol': '$', 'symbol_first': True, 'rate': 1, 'decimals': 2, 'is_base': True, 'is_active': True, 'sort': 0}])
    op.add_column('users', sa.Column('currency', sa.String(length=3), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'currency')
    op.drop_table('currencies')
