"""Create a LIVE demo auction from an existing product (QA helper).

    uv run python -m scripts.dev_auction --minutes 10 [--product-id 3] [--qty 20] [--start 500] [--step 1]
"""
import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db import session_scope
from app.enums import AuctionStatus
from app.models import Auction, Product


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=10)
    ap.add_argument("--product-id", type=int, default=None)
    ap.add_argument("--qty", type=int, default=20)
    ap.add_argument("--start", type=Decimal, default=Decimal("500"))
    ap.add_argument("--step", type=Decimal, default=Decimal("1"))
    a = ap.parse_args()
    async with session_scope() as db:
        p = await db.get(Product, a.product_id) if a.product_id else (await db.execute(select(Product).where(Product.is_active.is_(True)).order_by(Product.id))).scalars().first()
        if p is None:
            raise SystemExit("no products; run scripts.seed --demo first")
        now = datetime.now(UTC)
        au = Auction(
            product_id=p.id, brand=p.brand, model=p.model, capacity_gb=p.capacity_gb, condition=p.condition, test_status=p.test_status,
            qty=a.qty, seller_warranty_months=p.seller_warranty_months, factory_warranty_months=p.factory_warranty_months,
            description={"uz": "ДЕМО лот (QA)", "ru": "ДЕМО лот (QA)", "en": "DEMO lot (QA)"}, currency=p.currency,
            start_price_total=a.start, step_per_unit=a.step, current_price_total=a.start, starts_at=now - timedelta(seconds=1),
            ends_at=now + timedelta(minutes=a.minutes), original_ends_at=now + timedelta(minutes=a.minutes), status=AuctionStatus.LIVE,
        )
        db.add(au)
        await db.flush()
        print(f"auction #{au.id} LIVE until {au.ends_at:%H:%M:%S} UTC — {au.title} x{au.qty}, start {au.start_price_total} {au.currency}, step/unit {au.step_per_unit}")


if __name__ == "__main__":
    asyncio.run(main())
