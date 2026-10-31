"""WD Gold is an Enterprise (gold) line; WD White is the Data Center (white) one

Revision ID: c6e2a9f4b871
Revises: b3f7c1d9e264
Create Date: 2026-11-02 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c6e2a9f4b871'
down_revision: Union[str, None] = 'b3f7c1d9e264'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SERIES_KEY = "upper(regexp_replace(btrim(series), '\\s+', ' ', 'g'))"


def upgrade() -> None:
    bind = op.get_bind()
    # "Gold" had been guessed as Data Center; it is Enterprise. Products that followed the series move with it,
    # a colour someone picked by hand stays.
    for sid, brand_id in bind.execute(sa.text("SELECT id, brand_id FROM series WHERE key = 'GOLD' AND color = 'silver'")).all():
        bind.execute(sa.text("UPDATE series SET color = 'gold' WHERE id = :id"), {"id": sid})
        bind.execute(sa.text(f"UPDATE products SET color = 'gold' WHERE brand_id = :b AND {SERIES_KEY} = 'GOLD' AND (color IS NULL OR color = 'silver')"), {"b": brand_id})
    # WD White belongs to Data Center
    for (brand_id,) in bind.execute(sa.text("SELECT id FROM brands WHERE lower(name) IN ('western digital', 'wd') OR slug = 'western-digital'")).all():
        if bind.execute(sa.text("SELECT 1 FROM series WHERE brand_id = :b AND key = 'WHITE'"), {"b": brand_id}).first() is None:
            bind.execute(sa.text("INSERT INTO series (brand_id, name, key, color, sort) VALUES (:b, 'White', 'WHITE', 'silver', 70)"), {"b": brand_id})


def downgrade() -> None:
    pass
