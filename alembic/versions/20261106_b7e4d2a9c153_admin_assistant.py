"""admin assistant: chats, messages and the undo journal

Revision ID: b7e4d2a9c153
Revises: a3c9e5f1b207
Create Date: 2026-11-02 10:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'b7e4d2a9c153'
down_revision: Union[str, None] = 'a3c9e5f1b207'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'assistant_chats',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('staff_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(length=120), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_assistant_chats_staff_id', 'assistant_chats', ['staff_id'])
    op.create_table(
        'assistant_messages',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('chat_id', sa.Integer(), sa.ForeignKey('assistant_chats.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(length=12), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('tool_calls', sa.JSON(), nullable=True),
        sa.Column('tool_call_id', sa.String(length=64), nullable=True),
        sa.Column('name', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_assistant_messages_chat_id', 'assistant_messages', ['chat_id'])
    op.create_table(
        'assistant_actions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('chat_id', sa.Integer(), sa.ForeignKey('assistant_chats.id', ondelete='SET NULL'), nullable=True),
        sa.Column('staff_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('tool', sa.String(length=64), nullable=False),
        sa.Column('args', sa.JSON(), nullable=False),
        sa.Column('summary', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('entity', sa.String(length=40), nullable=True),
        sa.Column('entity_id', sa.String(length=40), nullable=True),
        sa.Column('journal', sa.JSON(), nullable=False),
        sa.Column('files', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False, server_default='done'),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('undo_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('undone_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('step', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_index('ix_assistant_actions_chat_id', 'assistant_actions', ['chat_id'])
    op.create_index('ix_assistant_actions_created_at', 'assistant_actions', ['created_at'])
    op.create_index('ix_assistant_actions_undo_until', 'assistant_actions', ['undo_until'])


def downgrade() -> None:
    op.drop_table('assistant_actions')
    op.drop_table('assistant_messages')
    op.drop_table('assistant_chats')
