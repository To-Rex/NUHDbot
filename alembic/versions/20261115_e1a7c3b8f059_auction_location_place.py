"""a lot's location names its country (any from the Geo settings) and, if wanted, the city

Revision ID: e1a7c3b8f059
Revises: d0f6b2a7e948
Create Date: 2026-11-09 14:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'e1a7c3b8f059'
down_revision: Union[str, None] = 'd0f6b2a7e948'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('auctions', sa.Column('location_name', sa.JSON(), nullable=True))
    op.add_column('auctions', sa.Column('location_city', sa.JSON(), nullable=True))
    # the first version kept lower-case cn / uz: country codes are upper-case, and the names come from the Geo settings
    op.execute("UPDATE auctions SET location = UPPER(location) WHERE location IS NOT NULL")
    op.execute("UPDATE auctions a SET location_name = c.name FROM countries c WHERE a.location = c.code AND a.location_name IS NULL")


def downgrade() -> None:
    op.drop_column('auctions', 'location_city')
    op.drop_column('auctions', 'location_name')
