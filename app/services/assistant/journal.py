"""Undo journal for assistant actions.

A tool records what it is about to touch — `track(obj)` before changing a row, `created(obj)` after adding one,
`deleted(obj)` before removing one (with the rows that hang off it) — and `entries()` gives JSON that `undo()`
turns back into the previous state: updated rows get their old values, created rows are deleted, deleted rows are
inserted again with their old ids (ids are never reused, so this is safe). Row images are plain column values made
JSON-safe; `coerce` turns them back for the column types.
"""
from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Table, insert, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AdPost,
    Article,
    AssistantUpload,
    Auction,
    AuctionDeposit,
    AuctionImage,
    Banner,
    Bid,
    Brand,
    BrandModel,
    City,
    Country,
    Currency,
    Order,
    OrderItem,
    OrderStatusHistory,
    Payment,
    PriceHistory,
    Product,
    ProductImage,
    Series,
    Setting,
    Subscription,
    SupportMessage,
    SupportThread,
    User,
)

# rows that go with a deleted parent (ON DELETE CASCADE in the schema), so undo can bring them back too
CHILDREN: dict[type, list[tuple[type, str]]] = {
    Product: [(ProductImage, "product_id"), (PriceHistory, "product_id")],
    Order: [(OrderItem, "order_id"), (OrderStatusHistory, "order_id"), (Payment, "order_id")],
    Auction: [(AuctionImage, "auction_id"), (Bid, "auction_id"), (AuctionDeposit, "auction_id")],
    SupportThread: [(SupportMessage, "thread_id")],
    Country: [(City, "country_code")],
    Brand: [(Series, "brand_id"), (BrandModel, "brand_id")],
    User: [(Order, "user_id"), (Payment, "user_id"), (Bid, "user_id"), (AuctionDeposit, "user_id"), (SupportThread, "user_id"), (Subscription, "user_id")],
}
MODELS: dict[str, type] = {m.__tablename__: m for m in (
    Product, ProductImage, PriceHistory, Order, OrderItem, OrderStatusHistory, Payment, Auction, AuctionImage, Bid, AuctionDeposit,
    SupportThread, SupportMessage, Country, City, Brand, Series, BrandModel, User, Subscription, Banner, AdPost, Article, Currency, Setting, AssistantUpload,
)}


def row_image(obj) -> dict:
    out = {}
    for col in inspect(obj).mapper.columns:
        v = getattr(obj, col.key)
        if isinstance(v, PyEnum):
            v = v.value
        elif isinstance(v, Decimal):
            v = str(v)
        elif isinstance(v, datetime):
            v = v.isoformat()
        out[col.key] = v
    return out


def coerce(table: Table, row: dict) -> dict:
    """JSON image → values the columns accept."""
    out = {}
    for k, v in row.items():
        if k not in table.c or v is None:
            if k in table.c:
                out[k] = None
            continue
        t = table.c[k].type
        if isinstance(t, SAEnum) and t.enum_class is not None:
            try:
                v = t.enum_class(v)
            except ValueError:
                pass
        else:
            try:
                py = t.python_type
            except NotImplementedError:
                py = None
            if py is Decimal:
                v = Decimal(str(v))
            elif py is datetime and isinstance(v, str):
                v = datetime.fromisoformat(v)
        out[k] = v
    return out


def _pk(obj) -> dict:
    return {c.key: getattr(obj, c.key) for c in inspect(obj).mapper.primary_key}


class Journal:
    """Collects the row images of one tool call."""

    def __init__(self) -> None:
        self._tracked: list[tuple[object, dict]] = []  # (obj, before)
        self._created: list[object] = []
        self._deleted: list[dict] = []

    def track(self, obj) -> None:
        if obj is not None and all(o is not obj for o, _ in self._tracked):
            self._tracked.append((obj, row_image(obj)))

    def created(self, obj) -> None:
        self._created.append(obj)

    async def deleted(self, db: AsyncSession, obj) -> None:
        self._deleted.append(await self._tree(db, obj))

    async def _tree(self, db: AsyncSession, obj) -> dict:
        node = {"table": obj.__tablename__, "row": row_image(obj), "children": []}
        for model, fk in CHILDREN.get(type(obj), []):
            pk = next(iter(_pk(obj).values()))
            for child in (await db.execute(select(model).where(getattr(model, fk) == pk))).scalars().unique().all():
                node["children"].append(await self._tree(db, child))
        return node

    async def settle(self, db: AsyncSession) -> None:
        """Reload what is still in the session before the after-images are taken: a bulk UPDATE (stock reserve / release)
        expires the rows it touched, and an expired attribute cannot be read lazily in async code."""
        for obj in [o for o, _ in self._tracked] + self._created:
            if inspect(obj).persistent:
                await db.refresh(obj)

    def entries(self) -> list[dict]:
        out = []
        for obj, before in self._tracked:
            after = row_image(obj)
            if after != before and obj not in self._created:
                out.append({"kind": "update", "table": obj.__tablename__, "pk": _pk(obj), "before": before, "after": after})
        for obj in self._created:
            out.append({"kind": "create", "table": obj.__tablename__, "pk": _pk(obj), "after": row_image(obj)})
        for tree in self._deleted:
            out.append({"kind": "delete", "table": tree["table"], "pk": {k: tree["row"][k] for k in _pk_keys(tree["table"])}, "tree": tree})
        return out


def _pk_keys(table: str) -> list[str]:
    return [c.key for c in MODELS[table].__table__.primary_key.columns]


async def _get(db: AsyncSession, table: str, pk: dict):
    model = MODELS[table]
    return await db.get(model, tuple(pk.values()) if len(pk) > 1 else next(iter(pk.values())))


async def _reinsert(db: AsyncSession, node: dict, notes: list[str]) -> None:
    table: Table = MODELS[node["table"]].__table__
    pk = {k: node["row"][k] for k in _pk_keys(node["table"])}
    if await _get(db, node["table"], pk) is not None:
        return  # already back (or never left)
    values = coerce(table, node["row"])
    try:
        async with db.begin_nested():
            await db.execute(insert(table).values(**values))
    except IntegrityError:
        # a link to a row that is gone since (a product under an order line, a user under a bid): drop the link, keep the row
        nullable_fks = [c.key for c in table.c if c.foreign_keys and c.nullable and values.get(c.key) is not None]
        for k in nullable_fks:
            values[k] = None
        try:
            async with db.begin_nested():
                await db.execute(insert(table).values(**values))
        except IntegrityError:
            notes.append(f"{node['table']} {pk} could not be restored")
            return
    for child in node["children"]:
        await _reinsert(db, child, notes)


async def undo(db: AsyncSession, entries: list[dict]) -> list[str]:
    """Put the journal back, newest entry first. Returns what could not be restored (empty = all good)."""
    from app.services import deletion

    notes: list[str] = []
    for e in reversed(entries):
        model = MODELS.get(e["table"])
        if model is None:
            notes.append(f"unknown table {e['table']}")
            continue
        if e["kind"] == "update":
            obj = await _get(db, e["table"], e["pk"])
            if obj is None:
                notes.append(f"{e['table']} {e['pk']} is gone")
                continue
            for k, v in coerce(model.__table__, e["before"]).items():
                if k not in e["pk"]:
                    setattr(obj, k, v)
        elif e["kind"] == "create":
            obj = await _get(db, e["table"], e["pk"])
            if obj is None:
                continue
            await deletion.delete_any(db, obj)
        elif e["kind"] == "delete":
            await _reinsert(db, e["tree"], notes)
        await db.flush()
    return notes
