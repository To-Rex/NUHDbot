"""Home slider banners: which are live now, and where a click on one goes."""
from datetime import UTC, datetime

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Banner

KINDS = ("new", "hot", "sale", "auction", "tips", "catalog", "info")
KIND_ICONS = {"new": "sparkle", "hot": "fire", "sale": "percent", "auction": "gavel", "tips": "lightbulb", "catalog": "grid", "info": "bell"}
# what a new banner of each kind usually points to and looks like (the form fills these in, staff can change them)
KIND_DEFAULTS = {"new": ("/app/new", "green"), "hot": (None, "red"), "sale": (None, "purple"), "auction": ("/app/auctions", "orange"),
                 "tips": ("/app/info", "teal"), "catalog": ("/app/catalog", "blue"), "info": (None, "black")}
COLORS = ("red", "orange", "gold", "green", "teal", "blue", "purple", "black")


def clean_link(value: str | None) -> str | None:
    """Only Mini App paths: /app/... (no protocol-relative or external URLs)."""
    v = (value or "").strip()
    return v[:255] if v.startswith("/app") and "//" not in v else None


def status(b: Banner, now: datetime | None = None) -> str:
    """off | scheduled | ended | live"""
    now = now or datetime.now(UTC)
    if not b.is_active:
        return "off"
    if b.starts_at and b.starts_at > now:
        return "scheduled"
    if b.ends_at and b.ends_at <= now:
        return "ended"
    return "live"


def target(b: Banner) -> str | None:
    """Where a tap goes: the product, the Mini App page, or nowhere (an announcement)."""
    if b.product_id:
        return f"/app/products/{b.product_id}"
    return clean_link(b.link)


async def live(db: AsyncSession) -> list[Banner]:
    now = datetime.now(UTC)
    stmt = (
        select(Banner)
        .where(Banner.is_active.is_(True), or_(Banner.starts_at.is_(None), Banner.starts_at <= now), or_(Banner.ends_at.is_(None), Banner.ends_at > now))
        .order_by(Banner.sort, Banner.id)
    )
    return list((await db.execute(stmt)).scalars().all())


async def all_banners(db: AsyncSession) -> list[Banner]:
    return list((await db.execute(select(Banner).order_by(Banner.sort, Banner.id))).scalars().all())


async def count_click(db: AsyncSession, bid: int) -> None:
    await db.execute(update(Banner).where(Banner.id == bid).values(clicks=Banner.clicks + 1))
