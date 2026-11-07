"""The admin panel's live events: queued by the services, delivered after commit, dropped on rollback."""
import asyncio
from decimal import Decimal

from app.enums import OrderStatus, PaymentKind
from app.services import admin_events, auctions
from app.services import orders as osvc
from tests.conftest import make_auction, make_product, make_user


async def drain(q: asyncio.Queue) -> list[dict]:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


async def test_order_events_after_commit(db):
    q = admin_events.listen()
    try:
        u = await make_user(db, 31)
        p = await make_product(db)
        o = await osvc.create_order(db, u, [(p.id, 5)], receiver_name="R", receiver_phone="+998900000000", country="UZ", city="Toshkent", address="a", cargo_company=None, cargo_code=None, customer_note=None)
        assert await drain(q) == []  # nothing before the commit
        await db.commit()
        evs = await drain(q)
        assert [e["type"] for e in evs] == ["order_new"]  # the automatic first step is not announced twice
        assert evs[0]["number"] == o.number and evs[0]["name"] == u.full_name
        await osvc.transition(db, o, OrderStatus.AWAITING_ADVANCE, by=u, note=None, force=True)
        await osvc.add_payment(db, o, u, PaymentKind.ADVANCE, Decimal("10"), "cash", None, None)
        await db.commit()
        types = [e["type"] for e in await drain(q)]
        assert types == ["order_status", "payment_new"]
    finally:
        admin_events.unlisten(q)


async def test_rollback_drops_and_auction_events_pass_through(db):
    q = admin_events.listen()
    try:
        u = await make_user(db, 32)
        a = await make_auction(db)
        a.require_deposit, a.deposit_amount = True, Decimal("50")
        await auctions.claim_deposit(db, a, u, None, None)
        await db.rollback()
        assert await drain(q) == []
        auctions.publish(a.id, {"type": "bid", "id": a.id, "version": 3})  # lot events reach the admin stream as "auction"
        ev = await drain(q)
        assert ev == [{"type": "auction", "kind": "bid", "id": a.id, "version": 3}]
    finally:
        admin_events.unlisten(q)
