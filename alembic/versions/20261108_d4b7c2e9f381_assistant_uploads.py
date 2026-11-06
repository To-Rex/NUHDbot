"""admin assistant: pictures attached in the chat

Revision ID: d4b7c2e9f381
Revises: c8f1a3d5e264
Create Date: 2026-11-06 10:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'd4b7c2e9f381'
down_revision: Union[str, None] = 'c8f1a3d5e264'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('assistant_messages', sa.Column('attachments', sa.JSON(), nullable=True))
    op.create_table(
        'assistant_uploads',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('chat_id', sa.Integer(), sa.ForeignKey('assistant_chats.id', ondelete='SET NULL'), nullable=True),
        sa.Column('staff_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('thumb', sa.String(length=255), nullable=False),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=160), nullable=False, server_default=''),
        sa.Column('used', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_assistant_uploads_chat_id', 'assistant_uploads', ['chat_id'])
    op.create_index('ix_assistant_uploads_staff_id', 'assistant_uploads', ['staff_id'])
    op.create_index('ix_assistant_uploads_created_at', 'assistant_uploads', ['created_at'])


def downgrade() -> None:
    op.drop_table('assistant_uploads')
    op.drop_column('assistant_messages', 'attachments')
