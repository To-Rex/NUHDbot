"""Series dictionary: product lines per brand with a colour; the product form takes the colour from the series."""
import re

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ProductColor
from app.models import Product, Series

COLORS = {c.value for c in ProductColor}


def norm_name(name: str | None) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())[:60]


def norm_key(name: str | None) -> str:
    return norm_name(name).upper()


def clean_color(value: str | None) -> str | None:
    return value if value in COLORS else None


async def list_series(db: AsyncSession, brand_id: int | None = None) -> list[Series]:
    stmt = select(Series).order_by(Series.brand_id, Series.sort, Series.name)
    if brand_id:
        stmt = stmt.where(Series.brand_id == brand_id)
    return list((await db.execute(stmt)).scalars().all())


async def find(db: AsyncSession, brand_id: int, name: str, exclude_id: int | None = None) -> Series | None:
    stmt = select(Series).where(Series.brand_id == brand_id, Series.key == norm_key(name))
    if exclude_id:
        stmt = stmt.where(Series.id != exclude_id)
    return (await db.execute(stmt)).scalar_one_or_none()


def _of_series(brand_id: int, key: str):
    return (Product.brand_id == brand_id, func.upper(func.regexp_replace(func.btrim(Product.series), r"\s+", " ", "g")) == key)


async def product_counts(db: AsyncSession) -> dict[tuple[int, str], int]:
    """How many products each (brand, series key) is typed on."""
    key = func.upper(func.regexp_replace(func.btrim(Product.series), r"\s+", " ", "g"))
    rows = await db.execute(select(Product.brand_id, key, func.count()).where(Product.brand_id.is_not(None), Product.series.is_not(None)).group_by(Product.brand_id, key))
    return {(b, k): n for b, k, n in rows.all() if k}


async def unlisted(db: AsyncSession) -> list[tuple[int, str, int]]:
    """Series typed on products that are not in the dictionary yet: (brand_id, name, products)."""
    have = {(s.brand_id, s.key) for s in await list_series(db)}
    name = func.min(func.btrim(Product.series))
    key = func.upper(func.regexp_replace(func.btrim(Product.series), r"\s+", " ", "g"))
    rows = await db.execute(
        select(Product.brand_id, key, name, func.count()).where(Product.brand_id.is_not(None), Product.series.is_not(None), func.btrim(Product.series) != "").group_by(Product.brand_id, key)
    )
    return [(b, n, c) for b, k, n, c in rows.all() if k and (b, k) not in have]


async def apply_color(db: AsyncSession, s: Series, old_color: str | None) -> int:
    """Give the series colour to its products that still follow the series (no colour yet, or the old series colour).
    A product someone recoloured by hand keeps its own colour. Returns how many products changed."""
    if not s.color:
        return 0
    follows = or_(Product.color.is_(None), Product.color == old_color) if old_color else Product.color.is_(None)
    res = await db.execute(update(Product).where(*_of_series(s.brand_id, s.key), follows, or_(Product.color.is_(None), Product.color != s.color)).values(color=s.color).execution_options(synchronize_session=False))
    return res.rowcount or 0


def _series_colour_for_product():
    """The colour of the dictionary series a product row is typed with (correlated)."""
    key = func.upper(func.regexp_replace(func.btrim(Product.series), r"\s+", " ", "g"))
    return select(Series.color).where(Series.brand_id == Product.brand_id, Series.key == key, Series.color.is_not(None))


async def uncoloured_count(db: AsyncSession) -> int:
    """Products without a colour whose series has one."""
    return await db.scalar(select(func.count()).select_from(Product).where(Product.color.is_(None), exists(_series_colour_for_product()))) or 0


async def apply_all(db: AsyncSession) -> int:
    """Give every product without a colour the colour of its series. Returns how many changed."""
    res = await db.execute(
        update(Product).where(Product.color.is_(None), exists(_series_colour_for_product())).values(color=_series_colour_for_product().scalar_subquery()).execution_options(synchronize_session=False)
    )
    return res.rowcount or 0


def as_dict(s: Series) -> dict:
    """Shape used by the product form: brand, name, key, colour."""
    return {"b": s.brand_id, "n": s.name, "k": s.key, "c": s.color}
