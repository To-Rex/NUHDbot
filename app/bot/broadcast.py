"""Subscription broadcasts (new arrivals). Marketing-type messages respect ads_opt_in and subscriptions."""
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import SubscriptionType
from app.i18n import t
from app.models import Product, Subscription, User
from app.services import notifications
from app.services.notifications import esc
from app.templating import money

RATE = 20  # messages per second (Telegram broadcast guidance ~30/s)


def _matches(sub: Subscription, p: Product) -> bool:
    v = sub.value or {}
    if sub.type == SubscriptionType.NEW_ARRIVALS:
        return True
    if sub.type == SubscriptionType.BRAND:
        return str(v.get("brand", "")).lower() == p.brand.lower()
    if sub.type == SubscriptionType.CAPACITY:
        return int(v.get("gb", 0) or 0) == p.capacity_gb
    if sub.type == SubscriptionType.PRICE_RANGE and p.price is not None:
        lo, hi = float(v.get("min", 0) or 0), float(v.get("max", 10**9) or 10**9)
        return lo <= float(p.price) <= hi
    return False


async def recipients_for_product(db: AsyncSession, p: Product) -> list[User]:
    rows = (
        await db.execute(
            select(Subscription, User)
            .join(User, User.id == Subscription.user_id)
            .where(Subscription.active.is_(True), User.tg_id.is_not(None), User.is_blocked.is_(False), User.ads_opt_in.is_(True))
        )
    ).all()
    seen: dict[int, User] = {}
    for sub, user in rows:
        if sub.type != SubscriptionType.AUCTION and _matches(sub, p):
            seen.setdefault(user.id, user)
    return list(seen.values())


async def broadcast_new_arrival(db: AsyncSession, p: Product) -> int:
    users = await recipients_for_product(db, p)
    sent = 0
    for i, u in enumerate(users):
        lang = u.lang
        text = t(lang, "bot.new_arrival", title=esc(p.title), capacity=p.capacity_label, cond=t(lang, f"condition.{p.condition}"),
                 price=money(p.price, p.currency) if p.price is not None else t(lang, "common.price_on_request"),
                 stock=t(lang, "bot.new_arrival_stock", n=p.available))
        text += "\n\n<i>" + t(lang, "bot.unsubscribe_hint") + "</i>"
        ok = await notifications.send(db, u, text, kind="new_arrival", reply_markup=notifications.miniapp_button(t(lang, "common.details"), f"/app/products/{p.id}"))
        sent += int(ok)
        if (i + 1) % RATE == 0:
            await asyncio.sleep(1)
    return sent


async def broadcast_recent_arrivals(db: AsyncSession, since_hours: int = 24) -> dict[int, int]:
    since = datetime.now(UTC) - timedelta(hours=since_hours)
    products = (await db.execute(select(Product).where(Product.is_active.is_(True), Product.arrived_at >= since))).scalars().unique().all()
    return {p.id: await broadcast_new_arrival(db, p) for p in products}
