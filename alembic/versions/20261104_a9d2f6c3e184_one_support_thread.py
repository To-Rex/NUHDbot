"""support: one conversation per customer

Every customer's threads (general, per order, reopened) are merged into one: the messages move to the kept
thread (the general one, else the latest), unread counters add up, it stays open if any was open. Then a unique
index makes sure a customer never gets a second one.

Revision ID: a9d2f6c3e184
Revises: f4c8e1a6b297
Create Date: 2026-11-01 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a9d2f6c3e184'
down_revision: Union[str, None] = 'f4c8e1a6b297'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TEMP TABLE thread_keep ON COMMIT DROP AS
        SELECT id, first_value(id) OVER (PARTITION BY user_id ORDER BY (order_id IS NULL) DESC, last_message_at DESC NULLS LAST, id DESC) AS keep
        FROM support_threads
    """)
    op.execute("UPDATE support_messages m SET thread_id = k.keep FROM thread_keep k WHERE m.thread_id = k.id AND k.id <> k.keep")
    op.execute("""
        UPDATE support_threads t SET
            unread_for_staff = a.us, unread_for_customer = a.uc, last_message_at = a.lm,
            status = CASE WHEN a.any_open THEN 'open' ELSE t.status END,
            assigned_to = COALESCE(t.assigned_to, a.asg)
        FROM (
            SELECT k.keep, sum(s.unread_for_staff) AS us, sum(s.unread_for_customer) AS uc, max(s.last_message_at) AS lm,
                   bool_or(s.status = 'open') AS any_open, max(s.assigned_to) AS asg
            FROM thread_keep k JOIN support_threads s ON s.id = k.id GROUP BY k.keep
        ) a
        WHERE t.id = a.keep
    """)
    op.execute("DELETE FROM support_threads t USING thread_keep k WHERE t.id = k.id AND k.id <> k.keep")
    op.drop_index('ix_support_threads_user_id', table_name='support_threads')
    op.create_index('ix_support_threads_user_id', 'support_threads', ['user_id'], unique=True)


def downgrade() -> None:  # the merged threads stay merged; only the rule goes
    op.drop_index('ix_support_threads_user_id', table_name='support_threads')
    op.create_index('ix_support_threads_user_id', 'support_threads', ['user_id'], unique=False)
