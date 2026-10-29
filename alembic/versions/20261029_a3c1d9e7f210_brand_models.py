"""brand models dictionary

Revision ID: a3c1d9e7f210
Revises: cfe0826b89ff
Create Date: 2026-10-29 16:40:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3c1d9e7f210'
down_revision: Union[str, None] = 'cfe0826b89ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'brand_models',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('brand_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('key', sa.String(length=120), nullable=False),
        sa.Column('capacity_gb', sa.Integer(), nullable=True),
        sa.Column('interface', sa.String(length=8), nullable=True),
        sa.Column('form_factor', sa.String(length=4), nullable=True),
        sa.Column('series', sa.String(length=60), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('brand_id', 'key', name='uq_brand_models_brand_key'),
    )
    op.create_index(op.f('ix_brand_models_brand_id'), 'brand_models', ['brand_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_brand_models_brand_id'), table_name='brand_models')
    op.drop_table('brand_models')
