"""banners: seconds a slide stays

Revision ID: f4c8e1a6b297
Revises: e1a7c3d9f528
Create Date: 2026-11-01 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f4c8e1a6b297'
down_revision: Union[str, None] = 'e1a7c3d9f528'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('banners', sa.Column('seconds', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('banners', 'seconds')
