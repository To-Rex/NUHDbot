"""the admin panel's kept notices (the bell) and when each staff member last opened it

Revision ID: a7c3e9d2b614
Revises: f6d9e4a1b503
Create Date: 2026-11-08 18:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'a7c3e9d2b614'
down_revision: Union[str, None] = 'f6d9e4a1b503'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'admin_notices',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('href', sa.String(length=200), nullable=False, server_default='/admin'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_admin_notices_kind', 'admin_notices', ['kind'])
    op.create_index('ix_admin_notices_created_at', 'admin_notices', ['created_at'])
    op.add_column('users', sa.Column('notices_seen_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'notices_seen_at')
    op.drop_index('ix_admin_notices_created_at', table_name='admin_notices')
    op.drop_index('ix_admin_notices_kind', table_name='admin_notices')
    op.drop_table('admin_notices')
