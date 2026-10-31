"""Home slider banners: which are live now, and where a click on one goes."""
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Banner, Product
from app.services import discounts

KINDS = ("new", "hot", "sale", "auction", "tips", "catalog", "info")
KIND_ICONS = {"new": "sparkle", "hot": "fire", "sale": "percent", "auction": "gavel", "tips": "lightbulb", "catalog": "grid", "info": "bell"}
# what a new banner of each kind usually points to and looks like (the form fills these in, staff can change them)
KIND_DEFAULTS = {"new": ("/app/new", "green"), "hot": (None, "red"), "sale": (None, "purple"), "auction": ("/app/auctions", "orange"),
                 "tips": ("/app/info", "teal"), "catalog": ("/app/catalog", "blue"), "info": (None, "black")}
COLORS = ("red", "orange", "gold", "green", "teal", "blue", "purple", "black")
SECONDS_MIN, SECONDS_MAX, SECONDS_DEFAULT = 1, 60, 7
SECONDS_CHOICES = (5, 7, 10, 15)
# how the home slider turns (Banners page → Slider animation): the Directions slider's looks; the first is the default
STYLES = ("coverflow", "orbit", "stack", "fan", "cylinder", "spiral", "cascade", "pile")


def clean_style(value: str | None) -> str:
    return value if value in STYLES else STYLES[0]


# the card shape of the home sliders (banners and directions): tall portrait cards or wide landscape ones
SHAPES = ("tall", "wide")


def clean_shape(value: str | None) -> str:
    return value if value in SHAPES else SHAPES[0]


def clean_seconds(value, default: int | None = None) -> int | None:
    """Seconds a slide stays, kept within 1–60; anything else gives the default."""
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(SECONDS_MIN, min(SECONDS_MAX, n))


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


def is_offer(b: Banner) -> bool:
    """Several products (picked, or every discounted one): a tap opens the offers page."""
    return bool(b.auto_sale or b.product_ids)


def target(b: Banner) -> str | None:
    """Where a tap goes: the offers page, the product, the Mini App page, or nowhere (an announcement)."""
    if is_offer(b):
        return f"/app/offers/{b.id}"
    if b.product_id:
        return f"/app/products/{b.product_id}"
    return clean_link(b.link)


async def offer(db: AsyncSession, b: Banner) -> tuple[list[Product], dict[int, Decimal]]:
    """The products of an offers banner (in the order picked; on sale: biggest cut first) and their old prices."""
    if b.auto_sale:
        return await discounts.discounted(db)
    ids = [int(i) for i in (b.product_ids or [])]
    if not ids:
        return [], {}
    found = {p.id: p for p in (await db.execute(select(Product).where(Product.id.in_(ids), Product.is_active.is_(True)))).scalars().unique()}
    rows = [found[i] for i in ids if i in found]
    return rows, await discounts.price_drops(db, [p.id for p in rows])


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
