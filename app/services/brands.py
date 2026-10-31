"""Brand dictionary: CRUD, ordering, product counts, product/auction sync and the idempotent backfill."""
import re
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Auction, Brand, Product


class BrandError(Exception):
    def __init__(self, code: str, **ctx):
        super().__init__(code)
        self.code = code
        self.ctx = ctx


# Spec brands in display order: (name, series, warranty_url, aliases)
DEFAULT_BRANDS: list[tuple[str, list[str], str | None, tuple[str, ...]]] = [
    ("Western Digital", ["Blue", "Purple", "Red", "Red Pro", "Gold", "Black", "White"], "https://support-en.wd.com/app/warrantystatusweb", ("wd", "western digital", "westerndigital")),
    ("Seagate", ["BarraCuda", "SkyHawk", "SkyHawk AI", "IronWolf", "IronWolf Pro", "Exos"], "https://www.seagate.com/support/warranty-and-replacements/", ("seagate",)),
    ("Toshiba", ["P300", "S300", "N300", "MG"], None, ("toshiba",)),
    ("HGST / Ultrastar", ["Ultrastar"], None, ("hgst", "hgst / ultrastar", "hgst/ultrastar", "ultrastar")),
    ("Hikvision", [], None, ("hikvision",)),
    ("Dahua", [], None, ("dahua",)),
]


def slugify(name: str) -> str:
    base = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    return slug[:60] or "brand"


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


async def list_brands(db: AsyncSession, active_only: bool = True) -> list[Brand]:
    stmt = select(Brand)
    if active_only:
        stmt = stmt.where(Brand.is_active.is_(True))
    return list((await db.execute(stmt.order_by(Brand.sort, Brand.name))).scalars().all())


async def get_brand(db: AsyncSession, brand_id: int) -> Brand | None:
    return await db.get(Brand, brand_id)


async def find_by_name(db: AsyncSession, name: str) -> Brand | None:
    n = _norm(name)
    if not n:
        return None
    return (await db.execute(select(Brand).where(func.lower(Brand.name) == n))).scalar_one_or_none()


async def _unique_slug(db: AsyncSession, name: str, exclude_id: int | None = None) -> str:
    base = slugify(name)
    slug, i = base, 2
    while True:
        stmt = select(Brand.id).where(Brand.slug == slug)
        if exclude_id:
            stmt = stmt.where(Brand.id != exclude_id)
        if (await db.execute(stmt)).scalar_one_or_none() is None:
            return slug
        slug = f"{base}-{i}"
        i += 1


def clean_series(items) -> list[str]:
    out: list[str] = []
    for raw in items or []:
        for part in str(raw).replace("\r", "").split("\n"):
            s = part.strip()[:60]
            if s and s.lower() not in (x.lower() for x in out):
                out.append(s)
    return out[:40]


async def create_brand(db: AsyncSession, *, name: str, series=None, warranty_url: str | None = None, description: dict | None = None, sort: int | None = None, is_active: bool = True, logo: str | None = None, logo_thumb: str | None = None) -> Brand:
    name = (name or "").strip()[:60]
    if not name:
        raise BrandError("name_required")
    if await find_by_name(db, name):
        raise BrandError("duplicate", name=name)
    if sort is None:
        sort = ((await db.execute(select(func.max(Brand.sort)))).scalar_one() or 0) + 10
    b = Brand(name=name, slug=await _unique_slug(db, name), series=clean_series(series), warranty_url=(warranty_url or "").strip() or None, description=description or {}, sort=sort, is_active=is_active, logo=logo, logo_thumb=logo_thumb)
    db.add(b)
    await db.flush()
    return b


async def update_brand(db: AsyncSession, b: Brand, *, name: str | None = None, series=None, warranty_url: str | None = None, description: dict | None = None, sort: int | None = None, is_active: bool | None = None) -> Brand:
    if name is not None:
        name = name.strip()[:60]
        if not name:
            raise BrandError("name_required")
        other = await find_by_name(db, name)
        if other and other.id != b.id:
            raise BrandError("duplicate", name=name)
        if name != b.name:
            b.name = name
            b.slug = await _unique_slug(db, name, exclude_id=b.id)
            # keep denormalised names in sync
            for p in (await db.execute(select(Product).where(Product.brand_id == b.id))).scalars().unique().all():
                p.brand = name
            for a in (await db.execute(select(Auction).where(Auction.brand_id == b.id))).scalars().unique().all():
                a.brand = name
    if series is not None:
        b.series = clean_series(series)
    if warranty_url is not None:
        b.warranty_url = warranty_url.strip() or None
    if description is not None:
        b.description = description
    if sort is not None:
        b.sort = sort
    if is_active is not None:
        b.is_active = is_active
    await db.flush()
    return b


async def product_counts(db: AsyncSession, *, active_only: bool = False) -> dict[int, int]:
    stmt = select(Product.brand_id, func.count()).where(Product.brand_id.is_not(None))
    if active_only:
        stmt = stmt.where(Product.is_active.is_(True))
    rows = (await db.execute(stmt.group_by(Product.brand_id))).all()
    return {int(bid): int(n) for bid, n in rows}


async def delete_brand(db: AsyncSession, b: Brand) -> None:
    n = (await db.execute(select(func.count()).select_from(Product).where(Product.brand_id == b.id))).scalar_one()
    if n:
        raise BrandError("in_use", count=int(n))
    # auctions keep their denormalised brand string; just detach
    for a in (await db.execute(select(Auction).where(Auction.brand_id == b.id))).scalars().unique().all():
        a.brand_id = None
    await db.delete(b)
    await db.flush()


async def reorder(db: AsyncSession, ids: list[int]) -> None:
    rows = {b.id: b for b in (await db.execute(select(Brand).where(Brand.id.in_(ids)))).scalars().all()}
    for i, bid in enumerate(ids):
        if bid in rows:
            rows[bid].sort = (i + 1) * 10
    await db.flush()


async def resolve_brand(db: AsyncSession, brand_id: str | int | None, other_name: str | None) -> Brand | None:
    """Brand chosen in a form: by id, or by free-text name (reused if it exists, otherwise created so filters stay complete)."""
    if brand_id not in (None, "", "__other__"):
        try:
            b = await get_brand(db, int(brand_id))
        except (TypeError, ValueError):
            b = None
        if b:
            return b
    name = (other_name or "").strip()
    if not name:
        return None
    return await find_by_name(db, name) or await create_brand(db, name=name)


def sync_product_brand(product: Product, brand: Brand | None, fallback_name: str | None = None) -> None:
    """Set brand_id + denormalised brand name on a product (or auction — same two attributes)."""
    if brand is not None:
        product.brand_id = brand.id
        product.brand = brand.name
    else:
        product.brand_id = None
        if fallback_name is not None:
            product.brand = fallback_name.strip()[:60]


async def catalog_brands(db: AsyncSession) -> list[tuple[Brand, int]]:
    """Brands for customer-facing filters: active brands, plus inactive ones that still have visible products; with counts."""
    counts = await product_counts(db, active_only=True)
    out = []
    for b in await list_brands(db, active_only=False):
        n = counts.get(b.id, 0)
        if b.is_active or n > 0:
            out.append((b, n))
    return out


async def backfill(db: AsyncSession) -> dict[str, int]:
    """Idempotent: create spec brands, then one brand per unknown product brand string, then link products/auctions."""
    created = linked = 0
    existing = {_norm(b.name): b for b in await list_brands(db, active_only=False)}
    alias_map: dict[str, Brand] = {}
    for i, (name, series, url, aliases) in enumerate(DEFAULT_BRANDS):
        b = existing.get(_norm(name))
        if b is None:
            b = Brand(name=name, slug=await _unique_slug(db, name), series=series, warranty_url=url, sort=(i + 1) * 10)
            db.add(b)
            await db.flush()
            existing[_norm(name)] = b
            created += 1
        for a in aliases:
            alias_map[a] = b
    for b in existing.values():
        alias_map.setdefault(_norm(b.name), b)
    # unknown brand strings from products
    names = [n for (n,) in (await db.execute(select(Product.brand).distinct())).all() if n]
    for n in names:
        if _norm(n) not in alias_map:
            b = Brand(name=n.strip()[:60], slug=await _unique_slug(db, n), series=[], sort=(len(existing) + 1) * 10)
            db.add(b)
            await db.flush()
            existing[_norm(b.name)] = b
            alias_map[_norm(n)] = b
            created += 1
    for p in (await db.execute(select(Product).where(Product.brand_id.is_(None)))).scalars().unique().all():
        b = alias_map.get(_norm(p.brand))
        if b:
            p.brand_id = b.id
            linked += 1
    for a in (await db.execute(select(Auction).where(Auction.brand_id.is_(None)))).scalars().unique().all():
        b = alias_map.get(_norm(a.brand))
        if b:
            a.brand_id = b.id
            linked += 1
    await db.flush()
    return {"created": created, "linked": linked}
