"""admin assistant: changes wait for the staff member's OK (plans), and a batch of approved changes can be undone together

Revision ID: f2b8d4c9a160
Revises: e1a7c3b8f059
Create Date: 2026-11-09 18:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'f2b8d4c9a160'
down_revision: Union[str, None] = 'e1a7c3b8f059'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'assistant_plans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('chat_id', sa.Integer(), nullable=True),
        sa.Column('staff_id', sa.Integer(), nullable=True),
        sa.Column('message_id', sa.Integer(), nullable=True),
        sa.Column('calls', sa.JSON(), nullable=False),
        sa.Column('results', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('note', sa.String(length=40), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['chat_id'], ['assistant_chats.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['staff_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['message_id'], ['assistant_messages.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assistant_plans_chat_id'), 'assistant_plans', ['chat_id'], unique=False)
    op.create_index(op.f('ix_assistant_plans_created_at'), 'assistant_plans', ['created_at'], unique=False)
    op.add_column('assistant_actions', sa.Column('plan_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_assistant_actions_plan_id'), 'assistant_actions', ['plan_id'], unique=False)
    op.create_foreign_key('fk_assistant_actions_plan_id', 'assistant_actions', 'assistant_plans', ['plan_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_assistant_actions_plan_id', 'assistant_actions', type_='foreignkey')
    op.drop_index(op.f('ix_assistant_actions_plan_id'), table_name='assistant_actions')
    op.drop_column('assistant_actions', 'plan_id')
    op.drop_index(op.f('ix_assistant_plans_created_at'), table_name='assistant_plans')
    op.drop_index(op.f('ix_assistant_plans_chat_id'), table_name='assistant_plans')
    op.drop_table('assistant_plans')
