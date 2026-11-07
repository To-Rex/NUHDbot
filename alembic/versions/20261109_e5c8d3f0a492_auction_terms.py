"""auction terms: the customer's acceptance (date + version)

Revision ID: e5c8d3f0a492
Revises: d4b7c2e9f381
Create Date: 2026-11-07 10:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'e5c8d3f0a492'
down_revision: Union[str, None] = 'd4b7c2e9f381'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('auction_terms_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('auction_terms_version', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'auction_terms_version')
    op.drop_column('users', 'auction_terms_at')
