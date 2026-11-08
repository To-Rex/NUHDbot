"""What the admin assistant can do. Each tool is a function the model may call: a JSON schema for the arguments and
a handler that works on the database the same way the admin pages do (same services, same audit entries).

A handler gets a Ctx: the session, the staff member, the undo journal (track / created / deleted — see journal.py)
and `after_commit` for things that must wait for the commit (Telegram copies, live auction events). It returns the
JSON the model reads back. Mutating tools set `ctx.summary` — the one line shown on the action card.
"""
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.enums import (
    COLOR_DIRECTION,
    ORDER_FLOW,
    AuctionStatus,
    Condition,
    FormFactor,
    Interface,
    MessageKind,
    OrderStatus,
    PaymentKind,
    ProductColor,
    Purpose,
    Role,
    TestStatus,
    ThreadStatus,
)
from app.i18n import pick
from app.models import (
    AdPost,
    Article,
    AssistantAction,
    Auction,
    Banner,
    Bid,
    Brand,
    BrandModel,
    City,
    Country,
    Currency,
    Order,
    PriceHistory,
    Product,
    Series,
    Setting,
    SupportThread,
    User,
)
from app.models.base import utcnow
from app.security import hash_password
from app.services import auctions as asvc
from app.services import banners as bsvc
from app.services import brands as brand_service
from app.services import deletion, model_dict, notifications, reports
from app.services import orders as osvc
from app.services import series as series_service
from app.services import support as ssvc
from app.services.assistant.journal import Journal
from app.services.settings_service import DEFAULTS, get_all_settings, get_setting, set_setting

LANGS = ("uz", "uzl", "ru", "en", "zh")
TZ = ZoneInfo(settings.timezone)
MAX_LIST = 100


class ToolError(Exception):
    """Something the model (and the staff member) should hear about, e.g. 'product 12 not found'."""


@dataclass
class Ctx:
    db: AsyncSession
    staff: User
    journal: Journal = field(default_factory=Journal)
    after_commit: list[Callable[[], Any]] = field(default_factory=list)
    summary: str = ""
    entity: str | None = None
    entity_id: str | None = None


@dataclass
class Tool:
    name: str
    description: str
    params: dict
    handler: Callable[..., Awaitable[dict]]
    mutating: bool = False
    required: tuple[str, ...] = ()

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": {"type": "object", "properties": self.params, "required": list(self.required)}}}


TOOLS: dict[str, Tool] = {}


def tool(name: str, description: str, params: dict | None = None, *, required: tuple[str, ...] = (), mutating: bool = False):
    def deco(fn):
        TOOLS[name] = Tool(name, description, params or {}, fn, mutating, required)
        return fn
    return deco


# ---------- small helpers ----------

def S(desc: str, **kw) -> dict:
    return {"type": "string", "description": desc, **kw}


def I(desc: str, **kw) -> dict:  # noqa: E743
    return {"type": "integer", "description": desc, **kw}


def N(desc: str) -> dict:
    return {"type": "number", "description": desc}


def B(desc: str) -> dict:
    return {"type": "boolean", "description": desc}


def ARR(desc: str, items: dict | None = None) -> dict:
    return {"type": "array", "description": desc, "items": items or {"type": "integer"}}


I18N = {"type": "object", "description": "Text per language: keys uz (Uzbek Cyrillic), uzl (Uzbek Latin), ru, en, zh. Give all five — translate yourself when the user wrote one language. A plain string is accepted and used for every language.", "additionalProperties": {"type": "string"}}


def i18n(v, old: dict | None = None) -> dict:
    if v is None:
        return dict(old or {})
    if isinstance(v, str):
        return dict.fromkeys(LANGS, v.strip()) if v.strip() else {}
    out = dict(old or {})
    for k, s in (v or {}).items():
        if k in LANGS:
            if s is None or not str(s).strip():
                out.pop(k, None)
            else:
                out[k] = str(s).strip()
    return out


def dec(v, name: str) -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError) as e:
        raise ToolError(f"{name}: not a number ({v!r})") from e


def dt(v, name: str) -> datetime:
    """'2026-11-05 18:00' or ISO, in the shop's time zone unless an offset is given."""
    if isinstance(v, datetime):
        return v.astimezone(UTC)
    try:
        d = datetime.fromisoformat(str(v).strip().replace(" ", "T"))
    except ValueError as e:
        raise ToolError(f"{name}: bad date/time ({v!r}); use YYYY-MM-DD HH:MM") from e
    return (d.replace(tzinfo=TZ) if d.tzinfo is None else d).astimezone(UTC)


def local(d: datetime | None) -> str | None:
    return d.astimezone(TZ).strftime("%Y-%m-%d %H:%M") if d else None


def enum(cls, v, name: str, default=None):
    if v is None or v == "":
        if default is not None:
            return default
        raise ToolError(f"{name} is required")
    try:
        return cls(str(v).strip().lower() if cls is not Interface else str(v).strip().upper())
    except ValueError as e:
        raise ToolError(f"{name}: one of {[m.value for m in cls]}") from e


def limit(n) -> int:
    try:
        return max(1, min(MAX_LIST, int(n or 20)))
    except (TypeError, ValueError):
        return 20


async def need(db, model, pk, what: str):
    obj = await db.get(model, pk)
    if obj is None:
        raise ToolError(f"{what} {pk} not found")
    return obj


def money(v, cur: str | None) -> str:
    return f"{Decimal(v or 0):,.2f} {cur or ''}".strip()


# ---------- products ----------

def product_row(p: Product) -> dict:
    return {
        "id": p.id, "brand": p.brand, "model": p.model, "capacity_gb": p.capacity_gb, "condition": p.condition.value, "price": str(p.price) if p.price is not None else None,
        "currency": p.currency, "stock": p.stock, "reserved": p.reserved, "available": p.available, "direction": COLOR_DIRECTION.get(p.color) if p.color else None,
        "series": p.series, "is_active": p.is_active, "sale_allowed": p.sale_allowed,
    }


def product_full(p: Product) -> dict:
    return product_row(p) | {
        "label_model": p.label_model, "interface": p.interface.value if p.interface else None, "form_factor": p.form_factor.value if p.form_factor else None, "color": p.color,
        "rpm": p.rpm, "cache_mb": p.cache_mb, "cost_price": str(p.cost_price) if p.cost_price is not None else None, "min_order": p.min_order, "box_qty": p.box_qty,
        "full_box_only": p.full_box_only, "seller_warranty_months": p.seller_warranty_months, "factory_warranty_months": p.factory_warranty_months,
        "test_status": p.test_status.value if p.test_status else None, "hours_used": p.hours_used, "health": p.health, "purposes": p.purposes or [],
        "description": p.description or {}, "compatibility": p.compatibility or {}, "test_summary": p.test_summary or {}, "delivery_note": p.delivery_note or {},
        "specs": p.specs or {}, "sort": p.sort, "images": len(p.images), "arrived_at": local(p.arrived_at), "views": getattr(p, "views", None),
    }


PRODUCT_FIELDS = {
    "brand": S("Brand name (created in the Brands list when new)"), "model": S("Model, e.g. WD40PURZ"), "label_model": S("Model on the label (Refresh drives)"),
    "series": S("Series, e.g. Purple, IronWolf (the direction colour follows the series)"), "capacity_gb": I("Capacity in GB: 4TB = 4000"),
    "condition": S("new | used | refresh"), "interface": S("SATA | SAS"), "form_factor": S("3.5 | 2.5"), "color": S("Direction colour: " + ", ".join(f"{c.value}={d}" for c, d in COLOR_DIRECTION.items())),
    "price": N("Price per unit"), "currency": S("Price currency code, e.g. USD"), "cost_price": N("Cost price per unit (finance only)"), "stock": I("Units in stock"),
    "min_order": I("Minimum order quantity"), "box_qty": I("Units per box"), "full_box_only": B("Sell full boxes only"), "seller_warranty_months": I("Seller warranty, months"),
    "factory_warranty_months": I("Factory warranty, months"), "test_status": S("untested | testing | tested"), "hours_used": I("Power-on hours (used drives)"), "health": S("SMART health, e.g. 98%"),
    "rpm": I("Spindle speed"), "cache_mb": I("Cache, MB"), "purposes": ARR("pc | cctv | nas | server | storage", {"type": "string"}), "description": I18N, "compatibility": I18N, "test_summary": I18N,
    "delivery_note": I18N, "specs": {"type": "object", "description": "Extra specs as key → value text", "additionalProperties": {"type": "string"}},
    "is_active": B("Visible in the catalogue"), "sale_allowed": B("Can be ordered"), "sort": I("Sort weight"),
}


async def _apply_product(ctx: Ctx, p: Product, a: dict, is_new: bool) -> None:
    db = ctx.db
    if "brand" in a and a["brand"]:
        b = await brand_service.find_by_name(db, a["brand"])
        if b is None:
            b = await brand_service.resolve_brand(db, None, a["brand"])
            ctx.journal.created(b)
        brand_service.sync_product_brand(p, b, a["brand"])
    for k in ("model", "label_model", "series", "health"):
        if k in a:
            p.__setattr__(k, (str(a[k]).strip() or None) if a[k] is not None else None)
    if p.model is None:
        raise ToolError("model is required")
    if "capacity_gb" in a:
        p.capacity_gb = int(a["capacity_gb"])
    if "condition" in a:
        p.condition = enum(Condition, a["condition"], "condition")
    if "interface" in a:
        p.interface = enum(Interface, a["interface"], "interface")
    if "form_factor" in a:
        p.form_factor = enum(FormFactor, str(a["form_factor"]).replace('"', ""), "form_factor")
    if "color" in a:
        p.color = enum(ProductColor, a["color"], "color").value if a["color"] else None
    elif (is_new or "series" in a) and not a.get("color"):
        guess = await series_service.colour_for(db, p.brand_id, p.series, p.model)
        if guess:
            p.color = guess
    if "test_status" in a:
        p.test_status = enum(TestStatus, a["test_status"], "test_status")
    if "purposes" in a:
        p.purposes = [x for x in (a["purposes"] or []) if x in [e.value for e in Purpose]]
    for k in ("rpm", "cache_mb", "stock", "min_order", "box_qty", "seller_warranty_months", "factory_warranty_months", "hours_used", "sort"):
        if k in a:
            p.__setattr__(k, int(a[k]) if a[k] is not None else None)
    if p.stock is None or p.stock < 0:
        p.stock = 0
    p.min_order = max(0, p.min_order or 0)  # 0 = no minimum of its own
    for k in ("full_box_only", "is_active", "sale_allowed"):
        if k in a:
            p.__setattr__(k, bool(a[k]))
    for k in ("description", "compatibility", "test_summary", "delivery_note"):
        if k in a:
            p.__setattr__(k, i18n(a[k], getattr(p, k)))
    if "specs" in a:
        p.specs = {str(k).strip(): str(v).strip() for k, v in (a["specs"] or {}).items() if str(k).strip()}
    if "currency" in a and a["currency"]:
        p.currency = str(a["currency"]).upper()[:3]
    if "cost_price" in a:
        p.cost_price = dec(a["cost_price"], "cost_price") if a["cost_price"] is not None else None
    if "price" in a:
        old = p.price
        p.price = dec(a["price"], "price") if a["price"] is not None else None
        if not is_new and (old or 0) != (p.price or 0):
            ph = PriceHistory(product_id=p.id, old_price=old, new_price=p.price, currency=p.currency, changed_by=ctx.staff.id, note="assistant")
            db.add(ph)
            await db.flush()
            ctx.journal.created(ph)


@tool("list_products", "Search the catalogue. Returns compact rows (id, brand, model, capacity, condition, price, stock, direction, flags).",
      {"query": S("Text to match in brand, model, series"), "brand": S("Brand name"), "direction": S("Direction colour or name: blue/Desktop, purple/Surveillance, red/NAS, gold/Enterprise, silver/Data Center, black/Gaming"),
       "condition": S("new | used | refresh"), "capacity_gb": I("Exact capacity in GB"), "in_stock": B("Only products with units available"), "active": B("true = visible only, false = hidden only, omit = all"),
       "sort": S("newest | price_asc | price_desc | stock (default: brand, model)"), "limit": I("Max rows, default 20, max 100")})
async def list_products(ctx: Ctx, query=None, brand=None, direction=None, condition=None, capacity_gb=None, in_stock=None, active=None, sort=None, limit_=None, **kw):
    stmt = select(Product)
    if query:
        like = f"%{query.strip()}%"
        stmt = stmt.where(or_(Product.brand.ilike(like), Product.model.ilike(like), Product.series.ilike(like), Product.label_model.ilike(like)))
    if brand:
        stmt = stmt.where(Product.brand.ilike(f"%{brand.strip()}%"))
    if direction:
        d = str(direction).strip().lower()
        col = next((c.value for c, name in COLOR_DIRECTION.items() if d in (c.value, name.lower())), None)
        if col is None:
            raise ToolError("direction: one of " + ", ".join(f"{c.value} ({n})" for c, n in COLOR_DIRECTION.items()))
        stmt = stmt.where(Product.color == col)
    if condition:
        stmt = stmt.where(Product.condition == enum(Condition, condition, "condition"))
    if capacity_gb:
        stmt = stmt.where(Product.capacity_gb == int(capacity_gb))
    if in_stock:
        stmt = stmt.where(Product.stock - Product.reserved > 0)
    if active is not None:
        stmt = stmt.where(Product.is_active.is_(bool(active)))
    order = {"newest": Product.id.desc(), "price_asc": Product.price.asc(), "price_desc": Product.price.desc(), "stock": (Product.stock - Product.reserved).desc()}.get(sort or "")
    stmt = stmt.order_by(order) if order is not None else stmt.order_by(Product.brand, Product.model)
    total = (await ctx.db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()
    rows = (await ctx.db.execute(stmt.limit(limit(kw.get("limit", limit_))))).scalars().unique().all()
    return {"total": total, "products": [product_row(p) for p in rows]}


@tool("get_product", "Everything about one product.", {"id": I("Product id")}, required=("id",))
async def get_product(ctx: Ctx, id: int):  # noqa: A002
    p = await need(ctx.db, Product, int(id), "product")
    return product_full(p)


@tool("create_product", "Add a product to the catalogue. Required: brand, model, capacity_gb, condition, price. Other fields are optional (defaults: SATA, 3.5, stock 0, visible, orderable; warranty by condition).",
      PRODUCT_FIELDS, required=("brand", "model", "capacity_gb", "condition", "price"), mutating=True)
async def create_product(ctx: Ctx, **a):
    from app.admin.products import WARRANTY_DEFAULTS

    p = Product(images=[], purposes=[], specs={}, description={}, compatibility={}, test_summary={}, delivery_note={}, stock=0, reserved=0, min_order=1, is_active=True, sale_allowed=True,
                currency=settings.default_currency, interface=Interface.SATA, form_factor=FormFactor.F35, test_status=TestStatus.UNTESTED, sort=0, arrived_at=datetime.now(UTC))
    await _apply_product(ctx, p, {k: v for k, v in a.items() if v is not None}, True)
    sw, fw = WARRANTY_DEFAULTS[p.condition]
    if "seller_warranty_months" not in a or a["seller_warranty_months"] is None:
        p.seller_warranty_months = sw
    if "factory_warranty_months" not in a or a["factory_warranty_months"] is None:
        p.factory_warranty_months = fw
    if p.capacity_gb is None or p.capacity_gb <= 0:
        raise ToolError("capacity_gb must be > 0")
    ctx.db.add(p)
    await ctx.db.flush()
    if p.price is not None:
        ph = PriceHistory(product_id=p.id, old_price=None, new_price=p.price, currency=p.currency, changed_by=ctx.staff.id, note="created")
        ctx.db.add(ph)
        await ctx.db.flush()
        ctx.journal.created(ph)
    ctx.journal.created(p)
    ctx.summary, ctx.entity, ctx.entity_id = f"Product created: {p.brand} {p.model} {p.capacity_label} · {money(p.price, p.currency)}", "product", str(p.id)
    return {"ok": True, "product": product_full(p), "admin_url": f"/admin/products/{p.id}"}


@tool("update_product", "Change fields of a product. Only the fields you pass change. A price change is written to the price history (shown as a discount when lower).",
      {"id": I("Product id"), **PRODUCT_FIELDS}, required=("id",), mutating=True)
async def update_product(ctx: Ctx, id: int, **a):  # noqa: A002
    p = await need(ctx.db, Product, int(id), "product")
    ctx.journal.track(p)
    changes = {k: v for k, v in a.items() if v is not None}
    if not changes:
        raise ToolError("nothing to change")
    await _apply_product(ctx, p, changes, False)
    await ctx.db.flush()
    ctx.summary, ctx.entity, ctx.entity_id = f"Product updated: {p.brand} {p.model} — {', '.join(changes)}", "product", str(p.id)
    return {"ok": True, "product": product_full(p)}


@tool("set_products_flags", "Show / hide or allow / stop sale for several products at once.",
      {"ids": ARR("Product ids"), "is_active": B("Visible in the catalogue"), "sale_allowed": B("Can be ordered")}, required=("ids",), mutating=True)
async def set_products_flags(ctx: Ctx, ids: list, is_active=None, sale_allowed=None):
    rows = (await ctx.db.execute(select(Product).where(Product.id.in_([int(i) for i in ids])))).scalars().unique().all()
    if not rows:
        raise ToolError("no such products")
    for p in rows:
        ctx.journal.track(p)
        if is_active is not None:
            p.is_active = bool(is_active)
        if sale_allowed is not None:
            p.sale_allowed = bool(sale_allowed)
    await ctx.db.flush()
    what = ", ".join(f"{k}={v}" for k, v in (("visible", is_active), ("orderable", sale_allowed)) if v is not None)
    ctx.summary, ctx.entity = f"{len(rows)} products: {what}", "product"
    return {"ok": True, "changed": [p.id for p in rows]}


@tool("delete_products", "Delete products (their photos and price history go too; orders and auctions keep the name).", {"ids": ARR("Product ids")}, required=("ids",), mutating=True)
async def delete_products(ctx: Ctx, ids: list):
    rows = (await ctx.db.execute(select(Product).where(Product.id.in_([int(i) for i in ids])))).scalars().unique().all()
    if not rows:
        raise ToolError("no such products")
    names = []
    for p in rows:
        names.append(f"{p.brand} {p.model}")
        await ctx.journal.deleted(ctx.db, p)
        await deletion.delete_product(ctx.db, p)
    ctx.summary, ctx.entity = f"Deleted {len(rows)} product(s): {', '.join(names[:5])}{'…' if len(names) > 5 else ''}", "product"
    return {"ok": True, "deleted": names}


# ---------- brands, series, models ----------

@tool("list_brands", "Brands with product counts.")
async def list_brands(ctx: Ctx):
    counts = await brand_service.product_counts(ctx.db)
    return {"brands": [{"id": b.id, "name": b.name, "is_active": b.is_active, "products": counts.get(b.id, 0), "warranty_url": b.warranty_url} for b in await brand_service.list_brands(ctx.db, active_only=False)]}


@tool("create_brand", "Add a brand.", {"name": S("Brand name"), "warranty_url": S("Warranty check URL")}, required=("name",), mutating=True)
async def create_brand(ctx: Ctx, name: str, warranty_url=None):
    if await brand_service.find_by_name(ctx.db, name):
        raise ToolError("brand exists")
    b = await brand_service.create_brand(ctx.db, name=name.strip(), warranty_url=warranty_url or None)
    ctx.journal.created(b)
    ctx.summary, ctx.entity, ctx.entity_id = f"Brand created: {b.name}", "brand", str(b.id)
    return {"ok": True, "brand": {"id": b.id, "name": b.name}}


@tool("update_brand", "Rename, hide or show a brand.", {"id": I("Brand id"), "name": S("New name"), "is_active": B("Shown in filters"), "warranty_url": S("Warranty check URL")}, required=("id",), mutating=True)
async def update_brand(ctx: Ctx, id: int, name=None, is_active=None, warranty_url=None):  # noqa: A002
    b = await need(ctx.db, Brand, int(id), "brand")
    ctx.journal.track(b)
    await brand_service.update_brand(ctx.db, b, name=name, is_active=is_active, warranty_url=warranty_url)
    ctx.summary, ctx.entity, ctx.entity_id = f"Brand updated: {b.name}", "brand", str(b.id)
    return {"ok": True}


@tool("delete_brand", "Delete a brand that has no products (its series and dictionary models go too).", {"id": I("Brand id")}, required=("id",), mutating=True)
async def delete_brand(ctx: Ctx, id: int):  # noqa: A002
    b = await need(ctx.db, Brand, int(id), "brand")
    await ctx.journal.deleted(ctx.db, b)
    try:
        await brand_service.delete_brand(ctx.db, b)
    except brand_service.BrandError as e:
        raise ToolError(f"brand has {e.ctx.get('count')} products; delete or move them first") from e
    ctx.summary, ctx.entity, ctx.entity_id = f"Brand deleted: {b.name}", "brand", str(id)
    return {"ok": True}


@tool("list_series", "Series (product lines) per brand with their direction colour.", {"brand": S("Brand name filter")})
async def list_series(ctx: Ctx, brand=None):
    rows = await series_service.list_series(ctx.db)
    brands = {b.id: b.name for b in await brand_service.list_brands(ctx.db, active_only=False)}
    counts = await series_service.product_counts(ctx.db)
    out = [{"id": s.id, "brand": brands.get(s.brand_id), "name": s.name, "color": s.color, "direction": COLOR_DIRECTION.get(s.color) if s.color else None, "products": counts.get((s.brand_id, s.key), 0)} for s in rows]
    if brand:
        out = [x for x in out if (x["brand"] or "").lower() == brand.strip().lower()]
    return {"series": out, "directions": {c.value: d for c, d in COLOR_DIRECTION.items()}}


@tool("create_series", "Add a series to a brand with its direction colour.", {"brand": S("Brand name"), "name": S("Series name"), "color": S("Direction colour: blue purple red gold silver black"), "apply_to_products": B("Give this colour to the brand's products of this series that have none yet")}, required=("brand", "name"), mutating=True)
async def create_series(ctx: Ctx, brand: str, name: str, color=None, apply_to_products=True):
    b = await brand_service.find_by_name(ctx.db, brand)
    if b is None:
        raise ToolError(f"brand {brand!r} not found")
    nm = series_service.norm_name(name)
    if await series_service.find(ctx.db, b.id, nm):
        raise ToolError("series exists")
    s = Series(brand_id=b.id, name=nm, key=series_service.norm_key(nm), color=series_service.clean_color(color) if color else None, sort=500)
    ctx.db.add(s)
    await ctx.db.flush()
    ctx.journal.created(s)
    changed = await series_service.apply_color(ctx.db, s, None) if apply_to_products and s.color else 0
    ctx.summary, ctx.entity, ctx.entity_id = f"Series created: {b.name} {s.name} ({COLOR_DIRECTION.get(s.color, '—') if s.color else 'no direction'})", "series", str(s.id)
    return {"ok": True, "series": {"id": s.id, "name": s.name, "color": s.color}, "products_recoloured": changed}


@tool("update_series", "Rename a series or change its direction colour.", {"id": I("Series id"), "name": S("New name"), "color": S("Direction colour"), "apply_to_products": B("Recolour the series' products too")}, required=("id",), mutating=True)
async def update_series(ctx: Ctx, id: int, name=None, color=None, apply_to_products=True):  # noqa: A002
    s = await need(ctx.db, Series, int(id), "series")
    ctx.journal.track(s)
    old = s.color
    if name:
        s.name, s.key = series_service.norm_name(name), series_service.norm_key(name)
    if color is not None:
        s.color = series_service.clean_color(color) if color else None
    await ctx.db.flush()
    changed = 0
    if apply_to_products and s.color:
        for p in (await ctx.db.execute(select(Product).where(Product.brand_id == s.brand_id, func.upper(Product.series) == s.key))).scalars().unique().all():
            ctx.journal.track(p)
        changed = await series_service.apply_color(ctx.db, s, old)
    ctx.summary, ctx.entity, ctx.entity_id = f"Series updated: {s.name}", "series", str(s.id)
    return {"ok": True, "products_recoloured": changed}


@tool("delete_series", "Delete a series (products keep their series text).", {"id": I("Series id")}, required=("id",), mutating=True)
async def delete_series(ctx: Ctx, id: int):  # noqa: A002
    s = await need(ctx.db, Series, int(id), "series")
    await ctx.journal.deleted(ctx.db, s)
    await ctx.db.delete(s)
    await ctx.db.flush()
    ctx.summary, ctx.entity, ctx.entity_id = f"Series deleted: {s.name}", "series", str(id)
    return {"ok": True}


@tool("list_models", "The model dictionary (autocomplete for the product form).", {"brand": S("Brand name filter")})
async def list_models(ctx: Ctx, brand=None):
    b = await brand_service.find_by_name(ctx.db, brand) if brand else None
    if brand and b is None:
        raise ToolError(f"brand {brand!r} not found")
    rows = await model_dict.list_models(ctx.db, b.id if b else None)
    return {"models": [{"id": m.id, "brand_id": m.brand_id, "name": m.name, "capacity_gb": m.capacity_gb, "interface": m.interface, "form_factor": m.form_factor, "series": m.series} for m in rows[:300]], "total": len(rows)}


@tool("add_models", "Add models to the dictionary of a brand. One per line: 'MODEL | 4TB | SATA | 3.5 | Series' (only the model is required).", {"brand": S("Brand name"), "lines": S("Models, one per line"), "series": S("Series for all lines")}, required=("brand", "lines"), mutating=True)
async def add_models(ctx: Ctx, brand: str, lines: str, series=None):
    b = await brand_service.find_by_name(ctx.db, brand)
    if b is None:
        raise ToolError(f"brand {brand!r} not found")
    added, skipped = await model_dict.bulk_add(ctx.db, b, lines, series)
    for m in added:
        ctx.journal.created(m)
    ctx.summary, ctx.entity = f"{len(added)} model(s) added to {b.name}", "brand_model"
    return {"ok": True, "added": [m.name for m in added], "skipped": skipped}


@tool("delete_model", "Remove a model from the dictionary.", {"id": I("Model id")}, required=("id",), mutating=True)
async def delete_model(ctx: Ctx, id: int):  # noqa: A002
    m = await need(ctx.db, BrandModel, int(id), "model")
    await ctx.journal.deleted(ctx.db, m)
    await model_dict.delete_model(ctx.db, m)
    ctx.summary, ctx.entity, ctx.entity_id = f"Model removed from dictionary: {m.name}", "brand_model", str(id)
    return {"ok": True}


# ---------- banners & home slider ----------

def banner_row(b: Banner) -> dict:
    return {"id": b.id, "kind": b.kind, "title": b.title, "subtitle": b.subtitle, "badge": b.badge, "color": b.color, "product_id": b.product_id, "product_ids": b.product_ids or [],
            "auto_sale": b.auto_sale, "link": b.link, "old_price": str(b.old_price) if b.old_price is not None else None, "starts_at": local(b.starts_at), "ends_at": local(b.ends_at),
            "is_active": b.is_active, "sort": b.sort, "clicks": b.clicks, "status": bsvc.status(b), "has_image": bool(b.image)}


BANNER_FIELDS = {
    "kind": S("new | hot | sale | auction | tips | catalog | info"), "title": I18N, "subtitle": I18N, "badge": S("Short badge, e.g. -15%"), "color": S("red orange gold green teal blue purple black"),
    "product_id": I("One product the banner opens"), "product_ids": ARR("Several products → an offers page"), "auto_sale": B("Offers page lists every discounted product"),
    "link": S("Mini App path when no product, e.g. /app/auctions"), "old_price": N("Struck-through old price next to the product price"), "starts_at": S("Show from (YYYY-MM-DD HH:MM)"),
    "ends_at": S("Show until (YYYY-MM-DD HH:MM)"), "is_active": B("Shown"), "sort": I("Order (smaller first)"),
}


async def _apply_banner(ctx: Ctx, b: Banner, a: dict) -> None:
    if "kind" in a:
        if a["kind"] not in bsvc.KINDS:
            raise ToolError(f"kind: one of {bsvc.KINDS}")
        b.kind = a["kind"]
    if "title" in a:
        b.title = i18n(a["title"], b.title)
    if "subtitle" in a:
        b.subtitle = i18n(a["subtitle"], b.subtitle)
    if not b.title:
        raise ToolError("title is required")
    if "badge" in a:
        b.badge = (str(a["badge"]).strip()[:24] or None) if a["badge"] else None
    if "color" in a:
        c = bsvc.clean_color(a["color"])
        if not c:
            raise ToolError(f"color: one of {bsvc.COLORS}, or any #rrggbb")
        b.color = c
    if "product_id" in a:
        b.product_id = int(a["product_id"]) if a["product_id"] and await ctx.db.get(Product, int(a["product_id"])) else None
        if a["product_id"] and b.product_id is None:
            raise ToolError(f"product {a['product_id']} not found")
    if "product_ids" in a:
        ids = [int(i) for i in (a["product_ids"] or [])]
        known = set((await ctx.db.execute(select(Product.id).where(Product.id.in_(ids)))).scalars()) if ids else set()
        b.product_ids = [i for i in dict.fromkeys(ids) if i in known]
    if "auto_sale" in a:
        b.auto_sale = bool(a["auto_sale"])
    if "link" in a:
        b.link = bsvc.clean_link(a["link"]) if a["link"] else None
    if "old_price" in a:
        b.old_price = dec(a["old_price"], "old_price") if a["old_price"] is not None else None
    if "starts_at" in a:
        b.starts_at = dt(a["starts_at"], "starts_at") if a["starts_at"] else None
    if "ends_at" in a:
        b.ends_at = dt(a["ends_at"], "ends_at") if a["ends_at"] else None
    if b.starts_at and b.ends_at and b.ends_at <= b.starts_at:
        raise ToolError("ends_at must be after starts_at")
    if "is_active" in a:
        b.is_active = bool(a["is_active"])
    if "sort" in a:
        b.sort = int(a["sort"])


@tool("list_banners", "Home slider banners and the slider settings.")
async def list_banners(ctx: Ctx):
    rows = await bsvc.all_banners(ctx.db)
    s = await get_all_settings(ctx.db)
    return {"banners": [banner_row(b) for b in rows], "slider": {k: s.get(k) for k in ("banner_slider_style", "banner_slider_shape", "dir_slider_style", "dir_slider_shape", "slider_seconds", "dir_slider_seconds")}}


@tool("create_banner", "Add a home slider banner (text only; a picture is uploaded on the Banners page).", BANNER_FIELDS, required=("title",), mutating=True)
async def create_banner(ctx: Ctx, **a):
    b = Banner(kind="hot", title={}, subtitle={}, color="red", product_ids=[], auto_sale=False, is_active=True, sort=100, clicks=0)
    await _apply_banner(ctx, b, {k: v for k, v in a.items() if v is not None})
    ctx.db.add(b)
    await ctx.db.flush()
    ctx.journal.created(b)
    ctx.summary, ctx.entity, ctx.entity_id = f"Banner created: {pick(b.title, 'uzl') or next(iter(b.title.values()), '')}", "banner", str(b.id)
    return {"ok": True, "banner": banner_row(b)}


@tool("update_banner", "Change a banner.", {"id": I("Banner id"), **BANNER_FIELDS}, required=("id",), mutating=True)
async def update_banner(ctx: Ctx, id: int, **a):  # noqa: A002
    b = await need(ctx.db, Banner, int(id), "banner")
    ctx.journal.track(b)
    changes = {k: v for k, v in a.items() if v is not None}
    await _apply_banner(ctx, b, changes)
    await ctx.db.flush()
    ctx.summary, ctx.entity, ctx.entity_id = f"Banner updated: {pick(b.title, 'uzl') or b.id} — {', '.join(changes)}", "banner", str(b.id)
    return {"ok": True, "banner": banner_row(b)}


@tool("delete_banner", "Delete a banner.", {"id": I("Banner id")}, required=("id",), mutating=True)
async def delete_banner(ctx: Ctx, id: int):  # noqa: A002
    b = await need(ctx.db, Banner, int(id), "banner")
    await ctx.journal.deleted(ctx.db, b)
    title = pick(b.title, "uzl") or str(b.id)
    await deletion.delete_any(ctx.db, b)
    ctx.summary, ctx.entity, ctx.entity_id = f"Banner deleted: {title}", "banner", str(id)
    return {"ok": True}


@tool("set_slider", "Home slider looks: animation (coverflow orbit stack fan cylinder spiral cascade pile), card shape (tall | wide) for the banner and the Directions sliders, seconds per slide.",
      {"banner_style": S("Banner slider animation"), "banner_shape": S("tall | wide"), "dir_style": S("Directions slider animation"), "dir_shape": S("tall | wide"), "seconds": I("Seconds a banner slide stays (1–60)"), "dir_seconds": I("Seconds a Directions card stays in front before the slider turns (1–60)"),
       "auto_auction": B("Automatic slide for the live / next auction on or off"), "auto_new": B("Automatic 'new arrivals this month' slide on or off")}, mutating=True)
async def set_slider(ctx: Ctx, banner_style=None, banner_shape=None, dir_style=None, dir_shape=None, seconds=None, dir_seconds=None, auto_auction=None, auto_new=None):
    changes = {}
    if auto_auction is not None or auto_new is not None:
        row = await ctx.db.get(Setting, "auto_slides")
        if row is not None:
            ctx.journal.track(row)
        auto = bsvc.clean_auto_slides(await get_setting(ctx.db, "auto_slides"))
        if auto_auction is not None:
            auto["auction"] = bool(auto_auction)
        if auto_new is not None:
            auto["new"] = bool(auto_new)
        await set_setting(ctx.db, "auto_slides", auto)
        if row is None:
            ctx.journal.created(await ctx.db.get(Setting, "auto_slides"))
        changes["auto_slides"] = auto
    for key, v, clean in (("banner_slider_style", banner_style, bsvc.clean_style), ("banner_slider_shape", banner_shape, bsvc.clean_shape), ("dir_slider_style", dir_style, bsvc.clean_style),
                          ("dir_slider_shape", dir_shape, bsvc.clean_shape), ("slider_seconds", seconds, lambda x: bsvc.clean_seconds(x, bsvc.SECONDS_DEFAULT)),
                          ("dir_slider_seconds", dir_seconds, lambda x: bsvc.clean_seconds(x, bsvc.DIR_SECONDS_DEFAULT))):
        if v is None:
            continue
        val = clean(v)
        row = await ctx.db.get(Setting, key)
        if row is not None:
            ctx.journal.track(row)
        await set_setting(ctx.db, key, val)
        if row is None:
            ctx.journal.created(await ctx.db.get(Setting, key))
        changes[key] = val
    if not changes:
        raise ToolError("nothing to change")
    ctx.summary, ctx.entity = "Slider settings: " + ", ".join(f"{k}={v}" for k, v in changes.items()), "setting"
    return {"ok": True, "slider": changes}


# ---------- orders ----------

def order_row(o: Order) -> dict:
    return {"id": o.id, "number": o.number, "status": o.status.value, "customer": o.user.full_name if o.user else None, "customer_id": o.user_id, "phone": o.user.phone if o.user else None,
            "items": [f"{i.brand} {i.model} {i.capacity_gb}GB x{i.qty} @ {i.unit_price}" for i in o.items], "total": str(o.total), "paid": str(o.paid_amount), "currency": o.currency,
            "created_at": local(o.created_at)}


def order_full(o: Order) -> dict:
    return order_row(o) | {"receiver_name": o.receiver_name, "receiver_phone": o.receiver_phone, "country": o.country, "city": o.city, "address": o.address, "cargo_company": o.cargo_company,
                           "cargo_code": o.cargo_code, "tracking_number": o.tracking_number, "customer_note": o.customer_note, "admin_note": o.admin_note, "delivery_terms": o.delivery_terms,
                           "warranty_terms": o.warranty_terms, "subtotal": str(o.subtotal), "lines": [{"id": i.id, "product_id": i.product_id, "brand": i.brand, "model": i.model, "qty": i.qty, "unit_price": str(i.unit_price)} for i in o.items],
                           "payments": [{"id": p.id, "kind": p.kind.value, "status": p.status.value, "amount": str(p.amount), "method": p.method, "at": local(p.created_at)} for p in o.payments],
                           "history": [{"from": h.from_status.value if h.from_status else None, "to": h.to_status.value, "note": h.note, "at": local(h.created_at)} for h in o.history[-10:]],
                           "allowed_statuses": [s.value for s in osvc.allowed_transitions(o, is_admin=True)]}


async def _order(ctx: Ctx, ref) -> Order:
    if isinstance(ref, int) or str(ref).isdigit():
        o = await ctx.db.get(Order, int(ref))
    else:
        o = (await ctx.db.execute(select(Order).where(Order.number == str(ref).strip().upper()))).scalars().first()
    if o is None:
        raise ToolError(f"order {ref} not found")
    return o


@tool("list_orders", "Orders, newest first. Statuses: new, awaiting_admin (order stage), awaiting_advance (payment stage), paid (shipping stage), shipped, cancelled.",
      {"status": S("Filter by status"), "query": S("Order number, customer name or phone"), "customer_id": I("Only this customer's orders"), "limit": I("Max rows, default 20")})
async def list_orders(ctx: Ctx, status=None, query=None, customer_id=None, **kw):
    stmt = select(Order).join(User, User.id == Order.user_id)
    if status:
        stmt = stmt.where(Order.status == enum(OrderStatus, status, "status"))
    if query:
        like = f"%{query.strip()}%"
        stmt = stmt.where(or_(Order.number.ilike(like), Order.receiver_phone.ilike(like), Order.receiver_name.ilike(like), User.phone.ilike(like), User.first_name.ilike(like), User.last_name.ilike(like)))
    if customer_id:
        stmt = stmt.where(Order.user_id == int(customer_id))
    total = (await ctx.db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()
    rows = (await ctx.db.execute(stmt.order_by(Order.id.desc()).limit(limit(kw.get("limit"))))).scalars().unique().all()
    return {"total": total, "orders": [order_row(o) for o in rows], "flow": [s.value for s in ORDER_FLOW]}


@tool("get_order", "One order with lines, payments and history.", {"order": S("Order id or number (NU-2611-0001)")}, required=("order",))
async def get_order(ctx: Ctx, order):
    return order_full(await _order(ctx, order))


@tool("set_order_status", "Move an order to a status (stock is reserved/released like the admin page does; the customer is notified).",
      {"order": S("Order id or number"), "status": S("new | awaiting_admin | awaiting_advance | paid | shipped | cancelled"), "note": S("Reason / note for the history")}, required=("order", "status"), mutating=True)
async def set_order_status(ctx: Ctx, order, status: str, note=None):
    o = await _order(ctx, order)
    to = enum(OrderStatus, status, "status")
    if to not in (OrderStatus.NEW, OrderStatus.AWAITING_ADMIN, OrderStatus.AWAITING_ADVANCE, OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.CANCELLED):
        raise ToolError("status: one of new, awaiting_admin, awaiting_advance, paid, shipped, cancelled")
    if to == OrderStatus.SHIPPED and o.paid_amount < o.total:
        raise ToolError(f"cannot ship: paid {o.paid_amount} of {o.total} {o.currency}")
    ctx.journal.track(o)
    for it in o.items:
        if it.product_id and (p := await ctx.db.get(Product, it.product_id)):
            ctx.journal.track(p)
    before = o.status
    await osvc.transition(ctx.db, o, to, by=ctx.staff, note=note or "assistant", force=True)
    for h in o.history[-1:]:
        ctx.journal.created(h)
    user = o.user
    ctx.after_commit.append(lambda: _notify(o.id, user.id if user else None))
    ctx.summary, ctx.entity, ctx.entity_id = f"Order {o.number}: {before.value} → {to.value}", "order", str(o.id)
    return {"ok": True, "order": order_row(o)}


async def _notify(order_id: int, user_id: int | None) -> None:
    from app.db import session_scope

    if not user_id:
        return
    async with session_scope() as db:
        o, u = await db.get(Order, order_id), await db.get(User, user_id)
        if o and u:
            await notifications.notify_order_status(db, o, u)


@tool("record_payment", "Record money received for an order (the first payment is the advance, later ones the balance). The order moves on by itself once the total is covered.",
      {"order": S("Order id or number"), "amount": N("Amount received, in the order currency"), "method": S("USDT / bank / cash …"), "note": S("Note")}, required=("order", "amount"), mutating=True)
async def record_payment(ctx: Ctx, order, amount, method=None, note=None):
    o = await _order(ctx, order)
    amt = dec(amount, "amount")
    if amt <= 0:
        raise ToolError("amount must be > 0")
    ctx.journal.track(o)
    kind = PaymentKind.ADVANCE if o.paid_amount == 0 else PaymentKind.BALANCE
    pay = await osvc.add_payment(ctx.db, o, o.user, kind, amt, method, None, note)
    await osvc.confirm_payment(ctx.db, pay, ctx.staff, True, "recorded by assistant")
    ctx.journal.created(pay)
    for h in o.history[-1:]:
        ctx.journal.created(h)
    user = o.user
    ctx.after_commit.append(lambda: _notify(o.id, user.id if user else None))
    ctx.summary, ctx.entity, ctx.entity_id = f"Payment {money(amt, o.currency)} recorded on {o.number} (paid {o.paid_amount}/{o.total})", "order", str(o.id)
    return {"ok": True, "order": order_full(o)}


@tool("update_order", "Change an order's offer and delivery details: final total, terms, notes, receiver, address, cargo code, tracking number, or line quantities / prices while the order is before payment.",
      {"order": S("Order id or number"), "total": N("Final total"), "delivery_terms": S(""), "warranty_terms": S(""), "admin_note": S("Internal note"), "receiver_name": S(""), "receiver_phone": S(""),
       "country": S("2-letter code"), "city": S(""), "address": S(""), "cargo_company": S(""), "cargo_code": S(""), "tracking_number": S(""), "customer_note": S(""),
       "lines": ARR("Line changes", {"type": "object", "properties": {"id": I("Line id"), "qty": I("New quantity"), "unit_price": N("New unit price")}, "required": ["id"]})}, required=("order",), mutating=True)
async def update_order(ctx: Ctx, order, lines=None, **a):
    from app.admin.orders import EDITABLE_ITEMS

    o = await _order(ctx, order)
    ctx.journal.track(o)
    changes = {k: v for k, v in a.items() if v is not None}
    for k, v in changes.items():
        if k == "total":
            o.total = dec(v, "total")
        elif k == "country":
            o.country = str(v).upper()[:2] or None
        else:
            setattr(o, k, str(v).strip() or None if k not in ("receiver_name", "receiver_phone", "address") else str(v).strip())
    if lines:
        if o.status not in EDITABLE_ITEMS:
            raise ToolError("lines can only change before the payment is confirmed")
        by_id = {i.id: i for i in o.items}
        for ln in lines:
            it = by_id.get(int(ln.get("id", 0)))
            if it is None:
                raise ToolError(f"line {ln.get('id')} not on this order")
            ctx.journal.track(it)
            if ln.get("qty") is not None:
                q = max(1, int(ln["qty"]))
                if it.product_id and (p := await ctx.db.get(Product, it.product_id)):
                    ctx.journal.track(p)
                    p.reserved = max(0, p.reserved + (q - it.qty))
                it.qty = q
            if ln.get("unit_price") is not None:
                it.unit_price = dec(ln["unit_price"], "unit_price")
        o.subtotal = sum((Decimal(i.unit_price) * i.qty for i in o.items), Decimal(0))
        if "total" not in changes:
            o.total = o.subtotal
        changes["lines"] = len(lines)
    if not changes:
        raise ToolError("nothing to change")
    await ctx.db.flush()
    ctx.summary, ctx.entity, ctx.entity_id = f"Order {o.number} updated: {', '.join(changes)}", "order", str(o.id)
    return {"ok": True, "order": order_full(o)}


@tool("delete_order", "Delete an order with its lines, payments and history (reserved stock is released).", {"order": S("Order id or number")}, required=("order",), mutating=True)
async def delete_order(ctx: Ctx, order):
    o = await _order(ctx, order)
    for it in o.items:
        if it.product_id and (p := await ctx.db.get(Product, it.product_id)):
            ctx.journal.track(p)
    await ctx.journal.deleted(ctx.db, o)
    number = o.number
    await deletion.delete_order(ctx.db, o)
    ctx.summary, ctx.entity, ctx.entity_id = f"Order deleted: {number}", "order", str(o.id)
    return {"ok": True}


# ---------- auctions ----------

def auction_row(a: Auction) -> dict:
    return {"id": a.id, "title": a.title, "capacity_gb": a.capacity_gb, "status": a.status.value, "qty": a.qty, "start_price_total": str(a.start_price_total), "current_price_total": str(a.current_price_total),
            "step_per_unit": str(a.step_per_unit), "bids": a.bids_count, "currency": a.currency, "starts_at": local(a.starts_at), "ends_at": local(a.ends_at), "product_id": a.product_id,
            "deposit_amount": str(a.deposit_amount), "require_deposit": a.require_deposit, "winner_user_id": a.winner_user_id, "location": a.location}


@tool("list_auctions", "Auction lots. Statuses: draft, scheduled, live, ended, cancelled.", {"status": S("Filter"), "limit": I("Max rows")})
async def list_auctions(ctx: Ctx, status=None, **kw):
    stmt = select(Auction)
    if status:
        stmt = stmt.where(Auction.status == enum(AuctionStatus, status, "status"))
    rows = (await ctx.db.execute(stmt.order_by(Auction.id.desc()).limit(limit(kw.get("limit"))))).scalars().unique().all()
    return {"auctions": [auction_row(a) for a in rows]}


@tool("get_auction", "One lot with its recent bids (bidders by id, as the admin page shows them).", {"id": I("Auction id")}, required=("id",))
async def get_auction(ctx: Ctx, id: int):  # noqa: A002
    a = await need(ctx.db, Auction, int(id), "auction")
    bids = await asvc.recent_bids(ctx.db, a.id, 20)
    return auction_row(a) | {"rules": a.rules, "description": a.description, "recent_bids": [{"id": b.id, "user_id": b.user_id, "user": b.user.full_name if b.user else None, "amount_total": str(b.amount_total), "at": local(b.created_at)} for b in bids]}


@tool("create_auction", "Create a lot from a catalogue product. Times are in the shop's time zone. publish=true makes it scheduled/live at once, otherwise it is a draft.",
      {"product_id": I("Catalogue product"), "qty": I("Units in the lot"), "start_price_total": N("Start price for the whole lot"), "step_per_unit": N("Bid step per unit (default 1)"),
       "starts_at": S("YYYY-MM-DD HH:MM"), "ends_at": S("YYYY-MM-DD HH:MM"), "deposit_amount": N("Deposit required to bid (0 = none)"), "rules": I18N, "location": S("Where the drives are: cn (China) | uz (Uzbekistan); empty = not said"), "publish": B("Publish right away")},
      required=("product_id", "qty", "start_price_total", "starts_at", "ends_at"), mutating=True)
async def create_auction(ctx: Ctx, product_id: int, qty: int, start_price_total, starts_at, ends_at, step_per_unit=None, deposit_amount=None, rules=None, location=None, publish=False):
    from app.admin.auctions import _from_product

    p = await need(ctx.db, Product, int(product_id), "product")
    a = Auction(status=AuctionStatus.DRAFT, bids_count=0, current_price_total=Decimal(0), version=0, timezone=settings.timezone)
    _from_product(a, p)
    a.qty = max(1, int(qty))
    a.start_price_total = dec(start_price_total, "start_price_total")
    if a.start_price_total <= 0:
        raise ToolError("start_price_total must be > 0")
    a.current_price_total = a.start_price_total
    a.step_per_unit = dec(step_per_unit, "step_per_unit") if step_per_unit is not None else Decimal(1)
    a.deposit_amount = dec(deposit_amount, "deposit_amount") if deposit_amount is not None else Decimal(0)
    a.require_deposit = a.deposit_amount > 0
    a.starts_at, a.ends_at = dt(starts_at, "starts_at"), dt(ends_at, "ends_at")
    if a.ends_at <= a.starts_at:
        raise ToolError("ends_at must be after starts_at")
    a.original_ends_at = a.ends_at
    a.rules = i18n(rules)
    a.location = asvc.clean_location(location)
    if publish:
        if a.ends_at <= datetime.now(UTC):
            raise ToolError("ends_at is in the past")
        a.status = AuctionStatus.LIVE if a.starts_at <= datetime.now(UTC) else AuctionStatus.SCHEDULED
    ctx.db.add(a)
    await ctx.db.flush()
    ctx.journal.created(a)
    ctx.summary, ctx.entity, ctx.entity_id = f"Auction created: {a.title} ×{a.qty}, start {money(a.start_price_total, a.currency)}, {a.status.value}", "auction", str(a.id)
    return {"ok": True, "auction": auction_row(a), "admin_url": f"/admin/auctions/{a.id}"}


@tool("update_auction", "Change a lot's quantity, prices, times, deposit, rules or location.",
      {"id": I("Auction id"), "qty": I(""), "start_price_total": N(""), "step_per_unit": N(""), "starts_at": S("YYYY-MM-DD HH:MM"), "ends_at": S("YYYY-MM-DD HH:MM"), "deposit_amount": N(""), "rules": I18N, "location": S("cn | uz | empty = not said")}, required=("id",), mutating=True)
async def update_auction(ctx: Ctx, id: int, **a):  # noqa: A002
    au = await need(ctx.db, Auction, int(id), "auction")
    ctx.journal.track(au)
    changes = {k: v for k, v in a.items() if v is not None}
    if "qty" in changes:
        au.qty = max(1, int(changes["qty"]))
    if "start_price_total" in changes:
        au.start_price_total = dec(changes["start_price_total"], "start_price_total")
        if au.bids_count == 0:
            au.current_price_total = au.start_price_total
    if "step_per_unit" in changes:
        au.step_per_unit = dec(changes["step_per_unit"], "step_per_unit")
    if "starts_at" in changes:
        au.starts_at = dt(changes["starts_at"], "starts_at")
    if "ends_at" in changes:
        au.ends_at = dt(changes["ends_at"], "ends_at")
        if au.status in (AuctionStatus.DRAFT, AuctionStatus.SCHEDULED):
            au.original_ends_at = au.ends_at
    if au.ends_at <= au.starts_at:
        raise ToolError("ends_at must be after starts_at")
    if "deposit_amount" in changes:
        au.deposit_amount = dec(changes["deposit_amount"], "deposit_amount")
        au.require_deposit = au.deposit_amount > 0
    if "rules" in changes:
        au.rules = i18n(changes["rules"], au.rules)
    if "location" in a:  # an empty string clears it
        au.location = asvc.clean_location(a["location"])
    if not changes:
        raise ToolError("nothing to change")
    au.version += 1
    await ctx.db.flush()
    ctx.after_commit.append(lambda: asvc.publish(au.id, {"type": "state", **asvc.snapshot(au)}))
    ctx.summary, ctx.entity, ctx.entity_id = f"Auction #{au.id} updated: {', '.join(changes)}", "auction", str(au.id)
    return {"ok": True, "auction": auction_row(au)}


@tool("auction_action", "publish (draft → scheduled/live), start (now), end (now, picks the winner), cancel.", {"id": I("Auction id"), "action": S("publish | start | end | cancel")}, required=("id", "action"), mutating=True)
async def auction_action(ctx: Ctx, id: int, action: str):  # noqa: A002
    a = await need(ctx.db, Auction, int(id), "auction")
    ctx.journal.track(a)
    now = datetime.now(UTC)
    if action == "publish" and a.status == AuctionStatus.DRAFT:
        if a.ends_at <= now:
            raise ToolError("ends_at is in the past")
        a.status = AuctionStatus.LIVE if a.starts_at <= now else AuctionStatus.SCHEDULED
        a.original_ends_at = a.ends_at
    elif action == "start" and a.status in (AuctionStatus.DRAFT, AuctionStatus.SCHEDULED):
        a.status, a.starts_at = AuctionStatus.LIVE, now
        if a.ends_at <= now:
            a.ends_at = a.original_ends_at = now + timedelta(hours=1)
    elif action == "end" and a.status == AuctionStatus.LIVE:
        last = (await ctx.db.execute(select(Bid).where(Bid.auction_id == a.id).order_by(Bid.id.desc()).limit(1))).scalar_one_or_none()
        a.status, a.ends_at = AuctionStatus.ENDED, min(a.ends_at, now)
        if last:
            a.winner_user_id, a.winner_bid_id = last.user_id, last.id
    elif action == "cancel" and a.status != AuctionStatus.ENDED:
        a.status = AuctionStatus.CANCELLED
    else:
        raise ToolError(f"{action!r} is not possible for a {a.status.value} lot")
    a.version += 1
    await ctx.db.flush()
    ctx.after_commit.append(lambda: asvc.publish(a.id, {"type": "ended" if a.status in (AuctionStatus.ENDED, AuctionStatus.CANCELLED) else "state", **asvc.snapshot(a)}))
    ctx.summary, ctx.entity, ctx.entity_id = f"Auction #{a.id} {action}: now {a.status.value}", "auction", str(a.id)
    return {"ok": True, "auction": auction_row(a)}


@tool("delete_auction", "Delete a lot with its bids and deposits.", {"id": I("Auction id")}, required=("id",), mutating=True)
async def delete_auction(ctx: Ctx, id: int):  # noqa: A002
    a = await need(ctx.db, Auction, int(id), "auction")
    await ctx.journal.deleted(ctx.db, a)
    title, gone = a.title, {"type": "ended", **asvc.snapshot(a), "status": AuctionStatus.CANCELLED}
    await deletion.delete_auction(ctx.db, a)
    ctx.after_commit.append(lambda: asvc.publish(int(id), gone))
    ctx.summary, ctx.entity, ctx.entity_id = f"Auction deleted: {title}", "auction", str(id)
    return {"ok": True}


@tool("delete_bid", "Remove one bid (price, leader and winner are recomputed from the rest).", {"auction_id": I(""), "bid_id": I("")}, required=("auction_id", "bid_id"), mutating=True)
async def delete_bid(ctx: Ctx, auction_id: int, bid_id: int):
    a = await need(ctx.db, Auction, int(auction_id), "auction")
    bid = await ctx.db.get(Bid, int(bid_id))
    if bid is None or bid.auction_id != a.id:
        raise ToolError("bid not found on this lot")
    ctx.journal.track(a)
    await ctx.journal.deleted(ctx.db, bid)
    await deletion.delete_bid(ctx.db, a, bid)
    ctx.after_commit.append(lambda: deletion.announce_auction(a))
    ctx.summary, ctx.entity, ctx.entity_id = f"Bid {bid_id} removed from auction #{a.id}; price now {money(a.current_price_total, a.currency)}", "auction", str(a.id)
    return {"ok": True, "auction": auction_row(a)}


# ---------- customers & staff ----------

def user_row(u: User) -> dict:
    return {"id": u.id, "name": u.full_name, "phone": u.phone, "tg_username": u.tg_username, "tg_id": u.tg_id, "country": u.country, "city": u.city, "lang": u.lang, "role": u.role.value,
            "is_blocked": u.is_blocked, "registered": bool(u.registered_at), "last_seen": local(u.last_seen_at), "source": u.source}


@tool("list_customers", "Customers (newest first).", {"query": S("Name, phone, username or city"), "country": S("2-letter code"), "registered": B("Only registered / only not"), "limit": I("Max rows")})
async def list_customers(ctx: Ctx, query=None, country=None, registered=None, **kw):
    stmt = select(User).where(User.role == Role.CUSTOMER)
    if query:
        like = f"%{query.strip()}%"
        stmt = stmt.where(or_(User.first_name.ilike(like), User.last_name.ilike(like), User.phone.ilike(like), User.tg_username.ilike(like), User.city.ilike(like)))
    if country:
        stmt = stmt.where(User.country == country.upper())
    if registered is not None:
        stmt = stmt.where(User.registered_at.is_not(None) if registered else User.registered_at.is_(None))
    total = (await ctx.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await ctx.db.execute(stmt.order_by(User.id.desc()).limit(limit(kw.get("limit"))))).scalars().all()
    counts = dict((await ctx.db.execute(select(Order.user_id, func.count()).where(Order.user_id.in_([u.id for u in rows])).group_by(Order.user_id))).all()) if rows else {}
    return {"total": total, "customers": [user_row(u) | {"orders": counts.get(u.id, 0)} for u in rows]}


@tool("get_customer", "A customer with their orders, bids, chat and what they hold in the Mini App cart right now (not an order yet).", {"id": I("Customer id")}, required=("id",))
async def get_customer(ctx: Ctx, id: int):  # noqa: A002
    from app.services import cart as cart_svc

    u = await need(ctx.db, User, int(id), "customer")
    orders = (await ctx.db.execute(select(Order).where(Order.user_id == u.id).order_by(Order.id.desc()).limit(20))).scalars().unique().all()
    bids = (await ctx.db.execute(select(func.count()).select_from(Bid).where(Bid.user_id == u.id))).scalar_one()
    th = await ssvc.user_thread(ctx.db, u.id)
    cart = cart_svc.user_cart(u)
    products = {p.id: p for p in (await ctx.db.execute(select(Product).where(Product.id.in_(list(cart))))).scalars().unique().all()} if cart else {}
    cart_rows = [{"product_id": pid, "qty": qty, "title": f"{products[pid].title} {products[pid].capacity_label}" if pid in products else None,
                  "price": str(products[pid].price) if pid in products and products[pid].price is not None else None, "available": products[pid].available if pid in products else 0} for pid, qty in cart.items()]
    return user_row(u) | {"last_address": u.last_address, "last_receiver_name": u.last_receiver_name, "last_receiver_phone": u.last_receiver_phone, "last_cargo_code": u.last_cargo_code,
                          "orders": [order_row(o) for o in orders], "bids": bids, "chat_thread_id": th.id if th else None, "cart": cart_rows, "cart_updated_at": u.cart_at}


@tool("update_customer", "Correct a customer's card or block / unblock them.",
      {"id": I("Customer id"), "first_name": S(""), "last_name": S(""), "phone": S(""), "country": S("2-letter code"), "city": S(""), "lang": S("uz | uzl | ru | en | zh"), "is_blocked": B("Blocked customers cannot use the bot / Mini App"),
       "last_receiver_name": S(""), "last_receiver_phone": S(""), "last_address": S(""), "last_cargo_company": S(""), "last_cargo_code": S("")}, required=("id",), mutating=True)
async def update_customer(ctx: Ctx, id: int, **a):  # noqa: A002
    u = await need(ctx.db, User, int(id), "customer")
    ctx.journal.track(u)
    changes = {k: v for k, v in a.items() if v is not None}
    if not changes:
        raise ToolError("nothing to change")
    for k, v in changes.items():
        if k == "is_blocked":
            u.is_blocked = bool(v)
        elif k == "country":
            u.country = str(v).upper()[:2] or None
        elif k == "lang":
            u.lang = str(v) if str(v) in LANGS else u.lang
        elif k in ("first_name", "last_name"):
            setattr(u, k, str(v).strip())
        else:
            setattr(u, k, str(v).strip() or None)
    await ctx.db.flush()
    ctx.summary, ctx.entity, ctx.entity_id = f"Customer {u.full_name} updated: {', '.join(changes)}", "user", str(u.id)
    return {"ok": True, "customer": user_row(u)}


@tool("delete_customer", "Delete a customer with their orders, payments, bids and chat.", {"id": I("Customer id")}, required=("id",), mutating=True)
async def delete_customer(ctx: Ctx, id: int):  # noqa: A002
    u = await need(ctx.db, User, int(id), "customer")
    if u.is_staff:
        raise ToolError("that is a staff account; use delete_staff")
    for o in (await ctx.db.execute(select(Order).where(Order.user_id == u.id))).scalars().unique().all():
        for it in o.items:
            if it.product_id and (p := await ctx.db.get(Product, it.product_id)):
                ctx.journal.track(p)
    for a in (await ctx.db.execute(select(Auction).where(Auction.id.in_(select(Bid.auction_id).where(Bid.user_id == u.id))))).scalars().unique().all():
        ctx.journal.track(a)
    await ctx.journal.deleted(ctx.db, u)
    name = u.full_name
    touched = await deletion.delete_customer(ctx.db, u)
    ctx.after_commit.append(lambda: [deletion.announce_auction(a) for a in touched])
    ctx.summary, ctx.entity, ctx.entity_id = f"Customer deleted: {name}", "user", str(id)
    return {"ok": True}


STAFF_ROLES_TXT = "admin | orders | catalog | warehouse | tester | finance | marketing"


@tool("list_staff", "Staff accounts and roles.")
async def list_staff(ctx: Ctx):
    rows = (await ctx.db.execute(select(User).where(User.role != Role.CUSTOMER).order_by(User.id))).scalars().all()
    return {"staff": [{"id": u.id, "name": u.full_name, "login": u.login, "role": u.role.value, "active": not u.is_blocked, "tg_id": u.tg_id} for u in rows]}


@tool("create_staff", "Add a staff account.", {"login": S(""), "password": S("At least 6 characters"), "role": S(STAFF_ROLES_TXT), "first_name": S(""), "last_name": S(""), "tg_id": I("Telegram id for notifications")}, required=("login", "password", "role", "first_name"), mutating=True)
async def create_staff(ctx: Ctx, login: str, password: str, role: str, first_name: str, last_name=None, tg_id=None):
    from app.enums import STAFF_ROLES

    r = enum(Role, role, "role")
    if r not in STAFF_ROLES:
        raise ToolError("role: " + STAFF_ROLES_TXT)
    if len(password) < 6:
        raise ToolError("password: at least 6 characters")
    if (await ctx.db.execute(select(User).where(User.login == login.strip()))).scalar_one_or_none():
        raise ToolError("login taken")
    u = User(first_name=first_name.strip(), last_name=(last_name or "").strip(), login=login.strip(), password_hash=hash_password(password), role=r, tg_id=int(tg_id) if tg_id else None, lang="uz")
    ctx.db.add(u)
    await ctx.db.flush()
    ctx.journal.created(u)
    ctx.summary, ctx.entity, ctx.entity_id = f"Staff created: {u.full_name} ({u.login}, {r.value})", "user", str(u.id)
    return {"ok": True, "id": u.id}


@tool("update_staff", "Change a staff member's role, name, login, password or active state.", {"id": I(""), "role": S(STAFF_ROLES_TXT), "first_name": S(""), "last_name": S(""), "login": S(""), "password": S(""), "active": B(""), "tg_id": I("")}, required=("id",), mutating=True)
async def update_staff(ctx: Ctx, id: int, **a):  # noqa: A002
    from app.enums import STAFF_ROLES

    u = await need(ctx.db, User, int(id), "staff")
    if not u.is_staff:
        raise ToolError("not a staff account")
    changes = {k: v for k, v in a.items() if v is not None}
    if u.id == ctx.staff.id and ({"role", "active"} & set(changes)):
        raise ToolError("you cannot change your own role or deactivate yourself")
    ctx.journal.track(u)
    for k, v in changes.items():
        if k == "role":
            r = enum(Role, v, "role")
            if r not in STAFF_ROLES:
                raise ToolError("role: " + STAFF_ROLES_TXT)
            u.role = r
        elif k == "password":
            if len(str(v)) < 6:
                raise ToolError("password: at least 6 characters")
            u.password_hash = hash_password(str(v))
        elif k == "active":
            u.is_blocked = not bool(v)
        elif k == "login":
            if (await ctx.db.execute(select(User).where(User.login == str(v).strip(), User.id != u.id))).scalar_one_or_none():
                raise ToolError("login taken")
            u.login = str(v).strip()
        elif k == "tg_id":
            u.tg_id = int(v) or None
        else:
            setattr(u, k, str(v).strip())
    if not changes:
        raise ToolError("nothing to change")
    await ctx.db.flush()
    ctx.summary, ctx.entity, ctx.entity_id = f"Staff {u.full_name} updated: {', '.join(k for k in changes if k != 'password')}{' + password' if 'password' in changes else ''}", "user", str(u.id)
    return {"ok": True}


@tool("delete_staff", "Delete a staff account (not yourself, not the last admin).", {"id": I("")}, required=("id",), mutating=True)
async def delete_staff(ctx: Ctx, id: int):  # noqa: A002
    u = await need(ctx.db, User, int(id), "staff")
    if not u.is_staff:
        raise ToolError("not a staff account")
    if u.id == ctx.staff.id:
        raise ToolError("you cannot delete yourself")
    if u.role == Role.ADMIN and (await ctx.db.execute(select(func.count()).select_from(User).where(User.role == Role.ADMIN))).scalar_one() < 2:
        raise ToolError("the last admin cannot be deleted")
    await ctx.journal.deleted(ctx.db, u)
    name = u.full_name
    touched = await deletion.delete_customer(ctx.db, u)
    ctx.after_commit.append(lambda: [deletion.announce_auction(a) for a in touched])
    ctx.summary, ctx.entity, ctx.entity_id = f"Staff deleted: {name}", "user", str(id)
    return {"ok": True}


# ---------- support chat ----------

@tool("list_chats", "Customer conversations (one per customer).", {"status": S("open | closed | all (default open)"), "limit": I("")})
async def list_chats(ctx: Ctx, status="open", **kw):
    st = None if status == "all" else enum(ThreadStatus, status or "open", "status")
    rows = await ssvc.staff_threads(ctx.db, st, limit(kw.get("limit", 50)))
    return {"chats": [{"id": th.id, "customer_id": th.user_id, "customer": th.user.full_name if th.user else None, "status": th.status.value, "unread": th.unread_for_staff,
                       "last_message_at": local(th.last_message_at), "last_text": (th.messages[-1].text or th.messages[-1].kind.value)[:120] if th.messages else None} for th in rows]}


@tool("read_chat", "Messages of a conversation.", {"thread_id": I(""), "limit": I("Last N messages, default 30")}, required=("thread_id",))
async def read_chat(ctx: Ctx, thread_id: int, **kw):
    th = await need(ctx.db, SupportThread, int(thread_id), "chat")
    msgs = th.messages[-limit(kw.get("limit", 30)):]
    return {"customer": th.user.full_name if th.user else None, "customer_lang": th.user.lang if th.user else None, "status": th.status.value,
            "messages": [{"id": m.id, "from": "admin" if m.from_staff else "customer", "text": m.text, "kind": m.kind.value, "at": local(m.created_at)} for m in msgs]}


@tool("reply_chat", "Send a message to the customer in their conversation (write it in the customer's language).", {"thread_id": I(""), "text": S("Message text")}, required=("thread_id", "text"), mutating=True)
async def reply_chat(ctx: Ctx, thread_id: int, text: str):
    import functools

    from app.admin.support import _telegram_copies
    from app.services import support_delivery

    th = await need(ctx.db, SupportThread, int(thread_id), "chat")
    if not text.strip():
        raise ToolError("empty text")
    ctx.journal.track(th)
    msg = await ssvc.add_message(ctx.db, th, sender=ctx.staff, from_staff=True, text=text.strip(), kind=MessageKind.TEXT)
    if not th.assigned_to:
        th.assigned_to = ctx.staff.id
    ctx.journal.created(msg)
    ctx.after_commit.append(lambda: support_delivery.schedule(th.id, msg.id, functools.partial(_telegram_copies, text=text.strip(), attachment=None, kind=MessageKind.TEXT)))
    ctx.summary, ctx.entity, ctx.entity_id = f"Reply sent to {th.user.full_name if th.user else th.id}: {text.strip()[:80]}", "thread", str(th.id)
    return {"ok": True, "message_id": msg.id}


@tool("set_chat_status", "Close or reopen a conversation.", {"thread_id": I(""), "status": S("open | closed")}, required=("thread_id", "status"), mutating=True)
async def set_chat_status(ctx: Ctx, thread_id: int, status: str):
    th = await need(ctx.db, SupportThread, int(thread_id), "chat")
    ctx.journal.track(th)
    th.status = enum(ThreadStatus, status, "status")
    ssvc.thread_changed(ctx.db, th)
    await ctx.db.flush()
    ctx.summary, ctx.entity, ctx.entity_id = f"Chat #{th.id} {th.status.value}", "thread", str(th.id)
    return {"ok": True}


@tool("delete_chat_message", "Delete one message from a conversation (disappears for the customer too).", {"thread_id": I(""), "message_id": I("")}, required=("thread_id", "message_id"), mutating=True)
async def delete_chat_message(ctx: Ctx, thread_id: int, message_id: int):
    th = await need(ctx.db, SupportThread, int(thread_id), "chat")
    m = next((x for x in th.messages if x.id == int(message_id)), None)
    if m is None:
        raise ToolError("message not found")
    ctx.journal.track(th)
    await ctx.journal.deleted(ctx.db, m)
    await deletion.delete_message(ctx.db, th, m)
    ctx.summary, ctx.entity, ctx.entity_id = f"Message {message_id} deleted from chat #{th.id}", "thread", str(th.id)
    return {"ok": True}


# ---------- settings, currencies, geo, articles, ads, reports ----------

SETTING_KEYS = ("advance_percent", "working_hours", "reply_time", "delivery_text", "payment_text", "payment_methods", "auction_deposit_default", "auction_extension_seconds", "free_cities",
                "warehouse_address", "wd_check_url", "seagate_check_url", "chat_notify_delay", "capacity_presets", "slider_seconds", "dir_slider_seconds")


@tool("get_settings", "Shop settings (texts shown to customers, payment methods, auction defaults, chat delay, capacity chips).")
async def get_settings(ctx: Ctx):
    s = await get_all_settings(ctx.db)
    return {k: {"value": s.get(k), "about": DEFAULTS.get(k, {}).get("d")} for k in SETTING_KEYS}


@tool("set_setting", "Change one shop setting. Multilingual texts take {uz, uzl, ru, en, zh}; payment_methods is a list of {name, details}; free_cities and capacity_presets are lists.",
      {"key": S("One of: " + ", ".join(SETTING_KEYS)), "value": {"description": "The new value (type depends on the key)"}}, required=("key", "value"), mutating=True)
async def set_setting_tool(ctx: Ctx, key: str, value):
    if key not in SETTING_KEYS:
        raise ToolError("key: one of " + ", ".join(SETTING_KEYS))
    current = await get_setting(ctx.db, key)
    if isinstance(current, dict) and key in ("working_hours", "reply_time", "delivery_text", "payment_text"):
        value = i18n(value, current)
    elif isinstance(current, (int, float)) and not isinstance(current, bool):
        try:
            value = int(value)
        except (TypeError, ValueError) as e:
            raise ToolError("value must be a number") from e
    elif key in ("free_cities", "capacity_presets"):
        value = [int(x) if key == "capacity_presets" else str(x) for x in (value if isinstance(value, list) else [value])]
    elif key == "payment_methods":
        if not isinstance(value, list) or any(not isinstance(x, dict) or not x.get("name") for x in value):
            raise ToolError("payment_methods: list of {name, details}")
        value = [{"name": str(x["name"]), "details": str(x.get("details") or "")} for x in value]
    else:
        value = str(value)
    row = await ctx.db.get(Setting, key)
    if row is not None:
        ctx.journal.track(row)
    await set_setting(ctx.db, key, value)
    if row is None:
        ctx.journal.created(await ctx.db.get(Setting, key))
    ctx.summary, ctx.entity, ctx.entity_id = f"Setting {key} changed", "setting", key
    return {"ok": True, key: value}


@tool("list_currencies", "Currencies and rates (units per 1 base currency).")
async def list_currencies(ctx: Ctx):
    rows = (await ctx.db.execute(select(Currency).order_by(Currency.sort, Currency.id))).scalars().all()
    return {"currencies": [{"id": c.id, "code": c.code, "name": c.name, "symbol": c.symbol, "rate": str(c.rate), "rate_at": local(c.rate_at), "is_base": c.is_base, "is_default": c.is_default, "is_active": c.is_active} for c in rows]}


@tool("set_currency", "Change a currency's rate (units per 1 base), activity or make it the Mini App default.", {"code": S("Currency code"), "rate": N(""), "is_active": B(""), "is_default": B("")}, required=("code",), mutating=True)
async def set_currency(ctx: Ctx, code: str, rate=None, is_active=None, is_default=None):

    c = (await ctx.db.execute(select(Currency).where(Currency.code == code.upper()))).scalar_one_or_none()
    if c is None:
        raise ToolError(f"currency {code} not found")
    ctx.journal.track(c)
    changes = []
    if rate is not None:
        if c.is_base:
            raise ToolError("the base currency's rate is always 1")
        r = dec(rate, "rate")
        if r <= 0:
            raise ToolError("rate must be > 0")
        c.rate, c.rate_at = r, utcnow()
        changes.append(f"rate={r}")
    if is_active is not None:
        c.is_active = bool(is_active) or c.is_base
        changes.append(f"active={c.is_active}")
    if is_default is not None:
        for other in (await ctx.db.execute(select(Currency).where(Currency.is_default.is_(True)))).scalars().all():
            ctx.journal.track(other)
            other.is_default = False
        c.is_default = bool(is_default)
        changes.append(f"default={c.is_default}")
    if not changes:
        raise ToolError("nothing to change")
    await ctx.db.flush()
    ctx.after_commit.append(lambda: _reload_currencies())
    ctx.summary, ctx.entity, ctx.entity_id = f"Currency {c.code}: {', '.join(changes)}", "currency", c.code
    return {"ok": True}


async def _reload_currencies() -> None:
    from app.db import session_scope
    from app.services import currencies

    async with session_scope() as db:
        await currencies.load(db)


@tool("list_countries", "Delivery countries with their active cities.", {"country": S("2-letter code to list cities of")})
async def list_countries(ctx: Ctx, country=None):
    rows = (await ctx.db.execute(select(Country).order_by(Country.sort))).scalars().all()
    out = {"countries": [{"code": c.code, "name": pick(c.name, "uzl"), "phone_code": c.phone_code, "is_active": c.is_active} for c in rows]}
    if country:
        cities = (await ctx.db.execute(select(City).where(City.country_code == country.upper()).order_by(City.sort))).scalars().all()
        out["cities"] = [{"id": c.id, "name": pick(c.name, "uzl"), "region": pick(c.region, "uzl") if c.region else None, "is_active": c.is_active} for c in cities]
    return out


@tool("add_city", "Add a delivery city.", {"country": S("2-letter code"), "name": I18N, "region": S("Region / oblast")}, required=("country", "name"), mutating=True)
async def add_city(ctx: Ctx, country: str, name, region=None):
    code = country.upper()
    if await ctx.db.get(Country, code) is None:
        raise ToolError(f"country {code} not found")
    names = i18n(name)
    c = City(country_code=code, name=names, region=dict.fromkeys(("uz", "uzl", "ru", "en"), region) if region else None, sort=500, is_active=True)
    ctx.db.add(c)
    await ctx.db.flush()
    ctx.journal.created(c)
    ctx.summary, ctx.entity, ctx.entity_id = f"City added: {pick(names, 'uzl')} ({code})", "city", str(c.id)
    return {"ok": True, "id": c.id}


@tool("set_geo_active", "Show or hide a country or a city for delivery.", {"country": S("2-letter code"), "city_id": I("City id (omit for the country itself)"), "is_active": B("")}, required=("is_active",), mutating=True)
async def set_geo_active(ctx: Ctx, is_active: bool, country=None, city_id=None):
    if city_id:
        c = await need(ctx.db, City, int(city_id), "city")
        ctx.journal.track(c)
        c.is_active = bool(is_active)
        ctx.summary, ctx.entity, ctx.entity_id = f"City {pick(c.name, 'uzl')}: {'shown' if c.is_active else 'hidden'}", "city", str(c.id)
    elif country:
        c = await need(ctx.db, Country, country.upper(), "country")
        ctx.journal.track(c)
        c.is_active = bool(is_active)
        ctx.summary, ctx.entity, ctx.entity_id = f"Country {c.code}: {'shown' if c.is_active else 'hidden'}", "country", c.code
    else:
        raise ToolError("country or city_id is required")
    await ctx.db.flush()
    return {"ok": True}


@tool("list_articles", "Help articles shown in the Mini App.")
async def list_articles(ctx: Ctx):
    rows = (await ctx.db.execute(select(Article).order_by(Article.sort, Article.id))).scalars().all()
    return {"articles": [{"id": a.id, "slug": a.slug, "category": a.category, "title": pick(a.title, "uzl"), "is_published": a.is_published, "sort": a.sort} for a in rows]}


@tool("get_article", "One article in full.", {"id": I("")}, required=("id",))
async def get_article(ctx: Ctx, id: int):  # noqa: A002
    a = await need(ctx.db, Article, int(id), "article")
    return {"id": a.id, "slug": a.slug, "category": a.category, "icon": a.icon, "title": a.title, "summary": a.summary, "body": a.body, "sort": a.sort, "is_published": a.is_published}


ARTICLE_FIELDS = {"slug": S("URL slug, latin letters and dashes"), "category": S("guide | tips | faq"), "title": I18N, "summary": I18N, "body": {**I18N, "description": "Article body per language, simple HTML (<p>, <b>, <ul>)"}, "sort": I(""), "is_published": B("")}


async def _apply_article(a: Article, f: dict) -> None:
    if "slug" in f:
        a.slug = re.sub(r"[^a-z0-9-]", "-", str(f["slug"]).lower()).strip("-")
    if "category" in f:
        a.category = str(f["category"])
    if "title" in f:
        a.title = i18n(f["title"], a.title)
    if "summary" in f:
        a.summary = i18n(f["summary"], a.summary)
    if "body" in f:
        a.body = i18n(f["body"], a.body)
    if "sort" in f:
        a.sort = int(f["sort"])
    if "is_published" in f:
        a.is_published = bool(f["is_published"])
    if not a.slug or not a.title:
        raise ToolError("slug and title are required")


@tool("create_article", "Add a help article.", ARTICLE_FIELDS, required=("slug", "title", "body"), mutating=True)
async def create_article(ctx: Ctx, **f):
    a = Article(category="guide", icon="💡", title={}, summary={}, body={}, sort=100, is_published=True)
    await _apply_article(a, {k: v for k, v in f.items() if v is not None})
    if (await ctx.db.execute(select(Article).where(Article.slug == a.slug))).scalar_one_or_none():
        raise ToolError("slug taken")
    ctx.db.add(a)
    await ctx.db.flush()
    ctx.journal.created(a)
    ctx.summary, ctx.entity, ctx.entity_id = f"Article created: {pick(a.title, 'uzl')}", "article", str(a.id)
    return {"ok": True, "id": a.id}


@tool("update_article", "Change an article.", {"id": I(""), **ARTICLE_FIELDS}, required=("id",), mutating=True)
async def update_article(ctx: Ctx, id: int, **f):  # noqa: A002
    a = await need(ctx.db, Article, int(id), "article")
    ctx.journal.track(a)
    changes = {k: v for k, v in f.items() if v is not None}
    await _apply_article(a, changes)
    await ctx.db.flush()
    ctx.summary, ctx.entity, ctx.entity_id = f"Article updated: {pick(a.title, 'uzl')} — {', '.join(changes)}", "article", str(a.id)
    return {"ok": True}


@tool("delete_article", "Delete an article.", {"id": I("")}, required=("id",), mutating=True)
async def delete_article(ctx: Ctx, id: int):  # noqa: A002
    a = await need(ctx.db, Article, int(id), "article")
    await ctx.journal.deleted(ctx.db, a)
    title = pick(a.title, "uzl")
    await ctx.db.delete(a)
    await ctx.db.flush()
    ctx.summary, ctx.entity, ctx.entity_id = f"Article deleted: {title}", "article", str(id)
    return {"ok": True}


@tool("list_ads", "Telegram ad posts (drafts and sent).")
async def list_ads(ctx: Ctx):
    rows = (await ctx.db.execute(select(AdPost).order_by(AdPost.id.desc()).limit(50))).scalars().all()
    return {"ads": [{"id": p.id, "title": p.title, "campaign": p.campaign, "status": p.status.value, "product_ids": p.product_ids, "clicks": p.clicks, "sent_at": local(p.sent_at)} for p in rows]}


@tool("create_ad", "Draft a Telegram ad post with 3–5 products (sending is done on the Ads page).", {"title": S(""), "text": S("Post text"), "product_ids": ARR("3 to 5 product ids"), "campaign": S("Campaign tag, latin letters/digits")}, required=("title", "text", "product_ids"), mutating=True)
async def create_ad(ctx: Ctx, title: str, text: str, product_ids: list, campaign=None):
    from app.enums import AdPostStatus

    ids = [int(i) for i in product_ids]
    if not 3 <= len(ids) <= 5:
        raise ToolError("3 to 5 products")
    p = AdPost(title=title.strip()[:120], text=text.strip(), product_ids=ids, target_chat_ids=[], campaign=re.sub(r"[^a-zA-Z0-9_-]", "", campaign or "") or f"camp{int(datetime.now(UTC).timestamp())}",
               status=AdPostStatus.DRAFT, clicks=0, created_by=ctx.staff.id)
    ctx.db.add(p)
    await ctx.db.flush()
    ctx.journal.created(p)
    ctx.summary, ctx.entity, ctx.entity_id = f"Ad draft created: {p.title}", "ad_post", str(p.id)
    return {"ok": True, "id": p.id, "admin_url": f"/admin/ads/{p.id}"}


@tool("delete_ad", "Delete an ad post.", {"id": I("")}, required=("id",), mutating=True)
async def delete_ad(ctx: Ctx, id: int):  # noqa: A002
    p = await need(ctx.db, AdPost, int(id), "ad")
    await ctx.journal.deleted(ctx.db, p)
    title = p.title
    await ctx.db.delete(p)
    await ctx.db.flush()
    ctx.summary, ctx.entity, ctx.entity_id = f"Ad deleted: {title}", "ad_post", str(id)
    return {"ok": True}


@tool("dashboard_stats", "Key numbers: orders, revenue, awaiting payments, stock, customers, live auctions, sales by brand and capacity.", {"days": I("Period, default 30")})
async def dashboard_stats(ctx: Ctx, days=30):
    d = await reports.dashboard(ctx.db, int(days or 30))
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in d.items() if k != "daily"} | {"by_brand": [(b, q, str(s)) for b, q, s in d["by_brand"]]}


# ---------- the assistant's own journal ----------

@tool("list_my_actions", "What the assistant changed recently (undoable for 3 days).", {"limit": I("Default 20")})
async def list_my_actions(ctx: Ctx, **kw):
    rows = (await ctx.db.execute(select(AssistantAction).order_by(AssistantAction.id.desc()).limit(limit(kw.get("limit"))))).scalars().all()
    return {"actions": [{"id": a.id, "tool": a.tool, "summary": a.summary, "status": a.status, "at": local(a.created_at), "undo_until": local(a.undo_until), "can_undo": a.can_undo} for a in rows]}


@tool("undo_action", "Put one of the assistant's earlier changes back (by action id).", {"action_id": I("")}, required=("action_id",), mutating=False)
async def undo_action(ctx: Ctx, action_id: int):
    from app.services.assistant.engine import undo as do_undo

    a = await need(ctx.db, AssistantAction, int(action_id), "action")
    ok, note = await do_undo(ctx.db, a, ctx.staff, in_turn=True)
    if not ok:
        raise ToolError(note or "cannot undo")
    return {"ok": True, "undone": a.summary, "note": note}


from app.services.assistant import tools_more  # noqa: E402,F401  (registers the rest of the tools)


def schemas() -> list[dict]:
    return [t.schema() for t in TOOLS.values()]
