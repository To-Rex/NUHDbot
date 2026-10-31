"""Discounts read from the price history: a product whose last price change was a cut (recently) and that
still sells at that price is on sale; the price before the cut is shown struck through."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PriceHistory, Product

WINDOW_DAYS = 60  # an older cut is just the price now


async def price_drops(db: AsyncSession, product_ids: list[int] | None = None) -> dict[int, Decimal]:
    """{product id: old price} for products on sale now."""
    if product_ids is not None and not product_ids:
        return {}
    latest = select(func.max(PriceHistory.id)).group_by(PriceHistory.product_id)  # each product's last price change
    cur = select(Product.id, Product.price).where(Product.is_active.is_(True))
    if product_ids is not None:
        latest, cur = latest.where(PriceHistory.product_id.in_(product_ids)), cur.where(Product.id.in_(product_ids))
    last = select(PriceHistory.product_id, PriceHistory.old_price, PriceHistory.new_price, PriceHistory.created_at).where(PriceHistory.id.in_(latest))
    prices = {pid: price for pid, price in (await db.execute(cur)).all()}
    since = datetime.now(UTC) - timedelta(days=WINDOW_DAYS)
    out = {}
    for pid, old, new, at in (await db.execute(last)).all():
        if old is not None and new is not None and old > new and at and at >= since and prices.get(pid) == new:
            out[pid] = old
    return out


def percent(old: Decimal | None, new: Decimal | None) -> int:
    """How much cheaper, in whole percent (0 when there is nothing to compare)."""
    if not old or new is None or old <= new:
        return 0
    return int(round((old - new) / old * 100))


async def discounted(db: AsyncSession) -> tuple[list[Product], dict[int, Decimal]]:
    """Every product on sale now, biggest cut first, and their old prices."""
    drops = await price_drops(db)
    if not drops:
        return [], {}
    rows = (await db.execute(select(Product).where(Product.id.in_(list(drops)), Product.is_active.is_(True)))).scalars().unique().all()
    rows = sorted(rows, key=lambda p: (-percent(drops[p.id], p.price), p.id))
    return list(rows), drops
