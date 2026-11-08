"""the customer's cart mirrored on the user row: staff see it on the customer's card, a new device gets it back

Revision ID: b8d4f0e3c725
Revises: a7c3e9d2b614
Create Date: 2026-11-08 21:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = 'b8d4f0e3c725'
down_revision: Union[str, None] = 'a7c3e9d2b614'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('cart', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('users', sa.Column('cart_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'cart_at')
    op.drop_column('users', 'cart')
