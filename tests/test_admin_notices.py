"""Someone new joining a lot reaches the admin panel: the live event, and the kept notice behind the bell."""
import asyncio

from sqlalchemy import select

from app.admin.common import LIVE_VISIBLE, notice_kinds
from app.enums import Role
from app.models import AdminNotice
from app.services import admin_events, admin_notices, auctions
from tests.conftest import make_auction, make_user


async def drain(q: asyncio.Queue) -> list[dict]:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


async def test_first_bid_announces_the_newcomer_once(db):
    q = admin_events.listen()
    try:
        a = await make_auction(db)
        u1, u2 = await make_user(db, 41), await make_user(db, 42)
        await auctions.place_bid(db, a.id, u1)
        await db.commit()
        evs = await drain(q)
        assert [e["type"] for e in evs] == ["auction_join"]
        assert evs[0]["stage"] == "bid" and evs[0]["auction_id"] == a.id and evs[0]["name"] == u1.full_name and evs[0]["amount"] == "500"
        await auctions.place_bid(db, a.id, u2)  # another newcomer
        await db.commit()
        await auctions.place_bid(db, a.id, u1)  # u1 again: not news
        await db.commit()
        evs = await drain(q)
        assert [(e["type"], e["name"]) for e in evs] == [("auction_join", u2.full_name)]
        rows = (await db.execute(select(AdminNotice).where(AdminNotice.kind == "auction_join").order_by(AdminNotice.id))).scalars().all()
        assert [r.data["name"] for r in rows][-2:] == [u1.full_name, u2.full_name] and rows[-1].href == f"/admin/auctions/{a.id}"
    finally:
        admin_events.unlisten(q)


async def test_terms_join_is_kept_and_counted_per_staff(db):
    a = await make_auction(db)
    u = await make_user(db, 43)
    admin = await make_user(db, 44, role=Role.ADMIN)
    catalog = await make_user(db, 45, role=Role.CATALOG)
    kinds = notice_kinds(admin)
    before = await admin_notices.unread_count(db, admin, kinds)
    auctions.announce_join(db, a, u, stage="terms")
    await db.flush()
    assert await admin_notices.unread_count(db, admin, kinds) == before + 1
    assert "auction_join" not in notice_kinds(catalog)  # the catalogue role does not watch auctions
    assert await admin_notices.unread_count(db, catalog, notice_kinds(catalog)) == 0
    latest = (await admin_notices.recent(db, kinds, limit=1))[0]
    assert latest.kind == "auction_join" and latest.data["stage"] == "terms" and admin_notices.is_new(latest, admin)
    await admin_notices.mark_seen(db, admin)
    assert await admin_notices.unread_count(db, admin, kinds) == 0 and not admin_notices.is_new(latest, admin)
    auctions.announce_join(db, None, u, stage="terms")  # a first-ever acceptance, no lot
    await db.flush()
    assert await admin_notices.unread_count(db, admin, kinds) == 1
    assert (await admin_notices.recent(db, kinds, limit=1))[0].href == f"/admin/customers/{u.id}"


async def test_rollback_drops_the_notice_too(db):
    a = await make_auction(db)
    u = await make_user(db, 46)
    n0 = len((await db.execute(select(AdminNotice.id))).all())
    auctions.announce_join(db, a, u, stage="terms")
    await db.flush()
    await db.rollback()
    assert len((await db.execute(select(AdminNotice.id))).all()) == n0


def test_every_kept_kind_has_a_role_map_and_an_icon():
    for k in admin_notices.STORED:
        assert k in LIVE_VISIBLE and k in admin_notices.ICONS
    assert admin_notices.href_for("order_new", {"id": 7}) == "/admin/orders/7"
    assert admin_notices.href_for("payment_new", {"id": 7}) == "/admin/orders/7#payments"
    assert admin_notices.href_for("deposit_new", {"auction_id": 3}) == "/admin/auctions/deposits"
