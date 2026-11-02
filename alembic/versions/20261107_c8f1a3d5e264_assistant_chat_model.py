"""admin assistant: the model each chat talks to

Revision ID: c8f1a3d5e264
Revises: b7e4d2a9c153
Create Date: 2026-11-03 09:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c8f1a3d5e264'
down_revision: Union[str, None] = 'b7e4d2a9c153'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('assistant_chats', sa.Column('provider', sa.String(length=32), nullable=False, server_default='deepseek'))
    op.add_column('assistant_chats', sa.Column('model', sa.String(length=120), nullable=False, server_default='deepseek-chat'))
    op.add_column('assistant_messages', sa.Column('model', sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column('assistant_messages', 'model')
    op.drop_column('assistant_chats', 'model')
    op.drop_column('assistant_chats', 'provider')
