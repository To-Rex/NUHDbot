"""orders: three stages — Order, Payment, Shipping

Every order still in a status the new journey no longer has moves to its stage:
  advance confirmed, testing, test ready, awaiting customer, awaiting balance → awaiting payment (awaiting_advance)
  paid, packing → paid (ready to ship)
  delivered, completed → shipped (the end)
  returned → cancelled; disputed → shipped if it had been shipped, else awaiting admin
Each move is written to the order's history with a note, so nothing is lost. Downgrade leaves the orders where they are.

Revision ID: a3c9e5f1b207
Revises: a9d2f6c3e184
Create Date: 2026-11-01 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a3c9e5f1b207'
down_revision: Union[str, None] = 'a9d2f6c3e184'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOTE = 'order journey simplified to Order / Payment / Shipping'
MOVES = [
    ("status IN ('advance_confirmed','testing','test_ready','awaiting_customer','awaiting_balance')", "awaiting_advance"),
    ("status IN ('packing')", "paid"),
    ("status IN ('delivered','completed')", "shipped"),
    ("status = 'returned'", "cancelled"),
    ("status = 'disputed' AND shipped_at IS NOT NULL", "shipped"),
    ("status = 'disputed'", "awaiting_admin"),
]


def upgrade() -> None:
    for where, to in MOVES:
        op.execute(f"""
            INSERT INTO order_status_history (order_id, from_status, to_status, by_user_id, note, created_at)
            SELECT id, status, '{to}', NULL, '{NOTE}', now() FROM orders WHERE {where}
        """)
        op.execute(f"UPDATE orders SET status = '{to}' WHERE {where}")


def downgrade() -> None:
    pass
