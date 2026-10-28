from dataclasses import dataclass, field

from sqlalchemy import Text, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import Condition, FormFactor, Interface, TestStatus
from app.models import Product

CAPACITY_PRESETS_GB = [500, 1000, 2000, 3000, 4000, 6000, 8000, 10000, 12000, 14000, 16000, 18000, 20000]
PAGE_SIZE = 20


@dataclass
class CatalogFilters:
    q: str = ""
    brands: list[str] = field(default_factory=list)
    capacities: list[int] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)
    form_factors: list[str] = field(default_factory=list)
    purposes: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    in_stock: bool = False
    warranty: bool = False
    price_min: float | None = None
    price_max: float | None = None
    sort: str = "default"  # default | price_asc | price_desc | newest | capacity
    page: int = 1

    @property
    def active_count(self) -> int:
        n = 0
        for v in (self.brands, self.capacities, self.conditions, self.interfaces, self.form_factors, self.purposes, self.tests):
            n += len(v)
        n += int(self.in_stock) + int(self.warranty) + int(self.price_min is not None) + int(self.price_max is not None)
        return n

    def to_query(self, **override) -> dict:
        d = {
            "q": self.q or None,
            "brand": self.brands or None,
            "gb": self.capacities or None,
            "cond": self.conditions or None,
            "iface": self.interfaces or None,
            "ff": self.form_factors or None,
            "use": self.purposes or None,
            "test": self.tests or None,
            "in_stock": 1 if self.in_stock else None,
            "warranty": 1 if self.warranty else None,
            "price_min": self.price_min,
            "price_max": self.price_max,
            "sort": self.sort if self.sort != "default" else None,
        }
        d.update(override)
        return {k: v for k, v in d.items() if v not in (None, [], "", False)}


def parse_filters(params) -> CatalogFilters:
    def ints(key):
        out = []
        for v in params.getlist(key):
            try:
                out.append(int(v))
            except ValueError:
                pass
        return out

    def num(key):
        v = params.get(key)
        try:
            return float(v) if v not in (None, "") else None
        except ValueError:
            return None

    try:
        page = max(1, int(params.get("page", 1)))
    except ValueError:
        page = 1
    return CatalogFilters(
        q=(params.get("q") or "").strip()[:80],
        brands=[b for b in params.getlist("brand") if b][:10],
        capacities=ints("gb"),
        conditions=[c for c in params.getlist("cond") if c in [e.value for e in Condition]],
        interfaces=[i for i in params.getlist("iface") if i in [e.value for e in Interface]],
        form_factors=[f for f in params.getlist("ff") if f in [e.value for e in FormFactor]],
        purposes=[p for p in params.getlist("use") if p][:6],
        tests=[s for s in params.getlist("test") if s in [e.value for e in TestStatus]],
        in_stock=params.get("in_stock") in ("1", "true", "on"),
        warranty=params.get("warranty") in ("1", "true", "on"),
        price_min=num("price_min"),
        price_max=num("price_max"),
        sort=params.get("sort") or "default",
        page=page,
    )


def _base_query(f: CatalogFilters):
    stmt = select(Product).where(Product.is_active.is_(True))
    if f.q:
        like = f"%{f.q}%"
        stmt = stmt.where(or_(Product.brand.ilike(like), Product.model.ilike(like), Product.label_model.ilike(like), Product.series.ilike(like)))
    if f.brands:
        stmt = stmt.where(Product.brand.in_(f.brands))
    if f.capacities:
        stmt = stmt.where(Product.capacity_gb.in_(f.capacities))
    if f.conditions:
        stmt = stmt.where(Product.condition.in_(f.conditions))
    if f.interfaces:
        stmt = stmt.where(Product.interface.in_(f.interfaces))
    if f.form_factors:
        stmt = stmt.where(Product.form_factor.in_(f.form_factors))
    if f.tests:
        stmt = stmt.where(Product.test_status.in_(f.tests))
    if f.purposes:
        # JSON array containment is dialect specific; keep portable with text match
        stmt = stmt.where(or_(*[cast(Product.purposes, Text).ilike(f'%"{p}"%') for p in f.purposes]))
    if f.in_stock:
        stmt = stmt.where(and_(Product.sale_allowed.is_(True), Product.stock - Product.reserved > 0))
    if f.warranty:
        stmt = stmt.where(or_(Product.seller_warranty_months > 0, Product.factory_warranty_months > 0))
    if f.price_min is not None:
        stmt = stmt.where(Product.price >= f.price_min)
    if f.price_max is not None:
        stmt = stmt.where(Product.price <= f.price_max)
    return stmt


def _apply_sort(stmt, sort: str):
    if sort == "price_asc":
        return stmt.order_by(Product.price.asc().nulls_last(), Product.id.desc())
    if sort == "price_desc":
        return stmt.order_by(Product.price.desc().nulls_last(), Product.id.desc())
    if sort == "newest":
        return stmt.order_by(Product.arrived_at.desc().nulls_last(), Product.id.desc())
    if sort == "capacity":
        return stmt.order_by(Product.capacity_gb.desc(), Product.price.asc().nulls_last())
    # default: in-stock first, manual sort, newest
    return stmt.order_by(
        ((Product.stock - Product.reserved) > 0).desc(), Product.sort.desc(), Product.arrived_at.desc().nulls_last(), Product.id.desc()
    )


async def list_products(db: AsyncSession, f: CatalogFilters, page_size: int = PAGE_SIZE) -> tuple[list[Product], int]:
    stmt = _base_query(f)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = _apply_sort(stmt, f.sort).offset((f.page - 1) * page_size).limit(page_size)
    rows = (await db.execute(stmt)).scalars().unique().all()
    return list(rows), int(total)


async def get_product(db: AsyncSession, product_id: int, *, active_only: bool = True) -> Product | None:
    p = await db.get(Product, product_id)
    if p is None or (active_only and not p.is_active):
        return None
    return p


async def new_arrivals(db: AsyncSession, limit: int = 12) -> list[Product]:
    stmt = (
        select(Product)
        .where(Product.is_active.is_(True), Product.arrived_at.is_not(None))
        .order_by(Product.arrived_at.desc(), Product.id.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().unique().all())


async def facets(db: AsyncSession) -> dict:
    brands = (
        await db.execute(
            select(Product.brand, func.count()).where(Product.is_active.is_(True)).group_by(Product.brand).order_by(func.count().desc())
        )
    ).all()
    caps = (
        await db.execute(
            select(Product.capacity_gb, func.count()).where(Product.is_active.is_(True)).group_by(Product.capacity_gb).order_by(Product.capacity_gb)
        )
    ).all()
    price = (await db.execute(select(func.min(Product.price), func.max(Product.price)).where(Product.is_active.is_(True)))).one()
    return {
        "brands": [(b, c) for b, c in brands],
        "capacities": [(g, c) for g, c in caps],
        "price_min": float(price[0] or 0),
        "price_max": float(price[1] or 0),
    }


async def similar_products(db: AsyncSession, p: Product, limit: int = 6) -> list[Product]:
    stmt = (
        select(Product)
        .where(Product.is_active.is_(True), Product.id != p.id, or_(Product.capacity_gb == p.capacity_gb, Product.brand == p.brand))
        .order_by((Product.capacity_gb == p.capacity_gb).desc(), (Product.brand == p.brand).desc(), Product.id.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().unique().all())


def capacity_label(gb: int) -> str:
    if gb >= 1000:
        return f"{gb // 1000}TB" if gb % 1000 == 0 else f"{gb / 1000:g}TB"
    return f"{gb}GB"
