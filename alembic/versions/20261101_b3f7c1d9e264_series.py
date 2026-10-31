"""series dictionary with colours

Revision ID: b3f7c1d9e264
Revises: a8d3e6b1c925
Create Date: 2026-11-01 21:00:00.000000
"""
import re
from collections import Counter
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3f7c1d9e264'
down_revision: Union[str, None] = 'a8d3e6b1c925'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# same hints the product form used to guess a colour from the series name
HINTS = [(r"\b(wd\s*)?gold\b", "silver"), (r"\b(purple|skyhawk|s300)\b", "purple"), (r"\b(red|ironwolf|n300)\b", "red"),
         (r"\b(exos|ultrastar|mg|mg\d{2})\b", "gold"), (r"\b(black|wd_black|firecuda)\b", "black"), (r"\b(blue|barracuda|p300)\b", "blue"),
         # or a use named after a colour direction
         (r"\bsurveillance\b", "purple"), (r"\bnas\b", "red"), (r"\benterprise\b", "gold"), (r"\bdata\s*cent(er|re)\b", "silver"), (r"\bgaming\b", "black"), (r"\bdesktop\b", "blue")]


def _key(name):
    return re.sub(r"\s+", " ", (name or "").strip()).upper()


def _hint(name):
    return next((c for rx, c in HINTS if re.search(rx, name or "", re.I)), None)


def upgrade() -> None:
    series = op.create_table(
        'series',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('brand_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('key', sa.String(length=60), nullable=False),
        sa.Column('color', sa.String(length=16), nullable=True),
        sa.Column('sort', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('brand_id', 'key', name='uq_series_brand_key'),
    )
    op.create_index(op.f('ix_series_brand_id'), 'series', ['brand_id'], unique=False)
    # start from what the shop already has: each brand's series list, then series typed on products
    bind = op.get_bind()
    rows, seen = [], set()
    used = Counter()
    for brand_id, name, color in bind.execute(sa.text("SELECT brand_id, series, color FROM products WHERE brand_id IS NOT NULL AND series IS NOT NULL AND btrim(series) <> ''")):
        used[(brand_id, _key(name), color)] += 1

    def add(brand_id, name, sort):
        name = re.sub(r"\s+", " ", (name or "").strip())[:60]
        k = _key(name)
        if not name or (brand_id, k) in seen:
            return
        seen.add((brand_id, k))
        color = _hint(name)
        if color is None:  # no hint: the colour most products of this series already have
            picks = Counter({c: n for (b, kk, c), n in used.items() if b == brand_id and kk == k and c})
            color = picks.most_common(1)[0][0] if picks else None
        rows.append({"brand_id": brand_id, "name": name, "key": k, "color": color, "sort": sort})

    for brand_id, raw in bind.execute(sa.text("SELECT id, series FROM brands ORDER BY sort, id")):
        items = raw if isinstance(raw, list) else []
        for i, name in enumerate(items):
            add(brand_id, str(name), (i + 1) * 10)
    for brand_id, name in bind.execute(sa.text("SELECT DISTINCT brand_id, btrim(series) FROM products WHERE brand_id IS NOT NULL AND series IS NOT NULL AND btrim(series) <> '' ORDER BY 1, 2")):
        add(brand_id, name, 500)
    if rows:
        op.bulk_insert(series, rows)


def downgrade() -> None:
    op.drop_index(op.f('ix_series_brand_id'), table_name='series')
    op.drop_table('series')
