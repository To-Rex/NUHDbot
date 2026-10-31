import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.enums import AuctionStatus
from app.models import Auction
from app.services import auctions
from tests.conftest import make_auction, make_product, make_user


async def test_first_bid_equals_start_then_step_enforced(db):
    u1 = await make_user(db, 1)
    u2 = await make_user(db, 2)
    a = await make_auction(db, qty=20, start="500", step="1")
    assert a.next_bid_total == Decimal("500")
    with pytest.raises(auctions.AuctionError) as e:
        await auctions.place_bid(db, a.id, u1, Decimal("499"))
    assert e.value.code == "bid_too_low"
    a, bid, prev = await auctions.place_bid(db, a.id, u1)  # default = minimum
    assert bid.amount_total == Decimal("500") and prev is None and a.bids_count == 1
    assert a.next_bid_total == Decimal("520") and a.current_price_unit == Decimal("25.00")
    with pytest.raises(auctions.AuctionError) as e:
        await auctions.place_bid(db, a.id, u2, Decimal("530"))  # not a multiple of the 20$ lot step
    assert e.value.code == "bid_step"
    with pytest.raises(auctions.AuctionError) as e:
        await auctions.place_bid(db, a.id, u1, Decimal("520"))
    assert e.value.code == "already_leading"
    a, bid2, prev = await auctions.place_bid(db, a.id, u2, Decimal("540"))
    assert prev.id == u1.id and a.current_price_total == Decimal("540") and a.bids_count == 2
    await db.commit()


async def test_unregistered_and_not_live(db):
    u = await make_user(db, 5, registered=False)
    a = await make_auction(db)
    with pytest.raises(auctions.AuctionError) as e:
        await auctions.place_bid(db, a.id, u)
    assert e.value.code == "not_registered"
    u2 = await make_user(db, 6)
    ended = await make_auction(db, status=AuctionStatus.ENDED)
    with pytest.raises(auctions.AuctionError) as e:
        await auctions.place_bid(db, ended.id, u2)
    assert e.value.code == "not_live"


async def test_anti_sniping_extends_end(db):
    u = await make_user(db, 7)
    a = await make_auction(db, minutes=1)  # ends in 60s -> inside the 120s window
    before = a.ends_at
    a, _, _ = await auctions.place_bid(db, a.id, u)
    assert a.ends_at > before
    assert (a.ends_at - datetime.now(UTC)).total_seconds() > 110


async def test_concurrent_bids_serialize(sessionmaker):
    async with sessionmaker() as s:
        u1 = await make_user(s, 11)
        u2 = await make_user(s, 12)
        a = await make_auction(s, qty=10, start="100", step="1")
        await s.commit()
        aid, uid1, uid2 = a.id, u1.id, u2.id

    async def bid(uid: int):
        async with sessionmaker() as s:
            from app.models import User

            user = await s.get(User, uid)
            try:
                await auctions.place_bid(s, aid, user, Decimal("100"))
                await s.commit()
                return "ok"
            except auctions.AuctionError as e:
                await s.rollback()
                return e.code

    results = await asyncio.gather(bid(uid1), bid(uid2))
    assert sorted(results) == ["bid_too_low", "ok"]  # exactly one wins the 100$ opening bid
    async with sessionmaker() as s:
        a = await s.get(Auction, aid)
        assert a.bids_count == 1 and a.current_price_total == Decimal("100")


async def test_tick_ends_auction_and_sets_winner(db):
    u = await make_user(db, 21)
    a = await make_auction(db, minutes=30)
    a, bid, _ = await auctions.place_bid(db, a.id, u)
    a.ends_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    ended = await auctions.tick(db)
    await db.commit()
    assert [x.id for x in ended] == [a.id]
    assert a.status == AuctionStatus.ENDED and a.winner_user_id == u.id and a.winner_bid_id == bid.id
    participants = await auctions.participants(db, a.id)
    assert [p.id for p in participants] == [u.id]


async def test_scheduled_auction_goes_live_on_tick(db):
    a = await make_auction(db, status=AuctionStatus.SCHEDULED)
    await db.commit()
    await auctions.tick(db)
    await db.commit()
    await db.refresh(a)
    assert a.status == AuctionStatus.LIVE


async def test_lot_takes_its_details_from_the_product(db):
    """Admin auction form: the lot is a catalogue product — brand, model, capacity, condition, warranty and currency come from it."""
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from starlette.datastructures import FormData

    from app.admin.auctions import _apply
    from app.enums import AuctionStatus
    from app.models import Auction

    p = await make_product(db)
    p.seller_warranty_months, p.factory_warranty_months, p.description = 6, 24, {"uz": "Sinovdan o'tgan"}
    start = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=1)
    times = {"starts_at": start.strftime("%Y-%m-%dT%H:%M"), "ends_at": (start + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")}
    a = Auction(status=AuctionStatus.DRAFT, bids_count=0, brand="", model="", current_price_total=Decimal(0))
    assert "product" in await _apply(db, a, FormData({"qty": "3", "start_price_total": "90", **times}))  # a new lot needs a product
    errors = await _apply(db, a, FormData({"product_id": str(p.id), "qty": "3", "start_price_total": "90", "brand": "Ignored", **times}))
    assert errors == []
    assert (a.product_id, a.brand, a.model, a.capacity_gb, a.condition) == (p.id, p.brand, p.model, p.capacity_gb, p.condition)
    assert (a.seller_warranty_months, a.factory_warranty_months, a.currency, a.description) == (6, 24, "USD", {"uz": "Sinovdan o'tgan"})
    assert a.qty == 3 and a.start_price_total == Decimal("90") and a.current_price_total == Decimal("90")


async def test_bidders_are_numbered_not_named(db):
    """On the lot page customers see "Participant №N" (the order of each bidder's first bid), never names."""
    from app.services import auctions as svc

    a = await make_auction(db, qty=2, start="100", step="1")
    u1, u2, u3 = await make_user(db, 3101), await make_user(db, 3102), await make_user(db, 3103)
    for u in (u2, u1, u2, u3):
        await svc.place_bid(db, a.id, u, None)
    await db.flush()
    assert await svc.bidder_numbers(db, a.id) == {u2.id: 1, u1.id: 2, u3.id: 3}
    assert await svc.best_bid(db, a.id, u2.id) == a.current_price_total - a.step_total * 1
