"""auction deposits paid by QR: payment methods (with QR codes), the deposit's method / review fields, the lot's deposit percent

Revision ID: f6d9e4a1b503
Revises: e5c8d3f0a492
Create Date: 2026-11-08 12:00:00.000000
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'f6d9e4a1b503'
down_revision: Union[str, None] = 'e5c8d3f0a492'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'payment_methods',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('kind', sa.String(length=12), nullable=False, server_default='other'),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('account', sa.String(length=200), nullable=True),
        sa.Column('instructions', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('qr_filename', sa.String(length=255), nullable=True),
        sa.Column('qr_text', sa.String(length=1000), nullable=True),
        sa.Column('currency', sa.String(length=3), nullable=True),
        sa.Column('for_deposits', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('for_orders', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('sort', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column('auction_deposits', sa.Column('method_id', sa.Integer(), sa.ForeignKey('payment_methods.id', ondelete='SET NULL'), nullable=True))
    op.add_column('auction_deposits', sa.Column('admin_note', sa.Text(), nullable=True))
    op.add_column('auction_deposits', sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('auctions', sa.Column('deposit_percent', sa.Numeric(5, 2), nullable=True))

    # the payment methods typed into Settings so far become rows (name + details to copy), so nothing the shop shows is lost
    conn = op.get_bind()
    row = conn.execute(sa.text("SELECT value FROM settings WHERE key = 'payment_methods'")).first()
    if row:
        value = row[0] if isinstance(row[0], dict) else json.loads(row[0] or '{}')
        for n, m in enumerate(value.get('v') or []):
            if isinstance(m, dict) and (m.get('name') or '').strip():
                conn.execute(sa.text("INSERT INTO payment_methods (kind, name, account, instructions, sort) VALUES ('other', :name, :account, '{}', :sort)"),
                             {"name": m['name'].strip()[:80], "account": (m.get('details') or '').strip()[:200] or None, "sort": n})


def downgrade() -> None:
    op.drop_column('auctions', 'deposit_percent')
    op.drop_column('auction_deposits', 'reviewed_at')
    op.drop_column('auction_deposits', 'admin_note')
    op.drop_column('auction_deposits', 'method_id')
    op.drop_table('payment_methods')
