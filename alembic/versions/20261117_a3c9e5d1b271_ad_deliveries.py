"""ad posts keep every send: which chat, the message id or the error

Revision ID: a3c9e5d1b271
Revises: f2b8d4c9a160
Create Date: 2026-11-09 21:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'a3c9e5d1b271'
down_revision: Union[str, None] = 'f2b8d4c9a160'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ad_posts', sa.Column('deliveries', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    op.drop_column('ad_posts', 'deliveries')
