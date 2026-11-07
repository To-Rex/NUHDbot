"""Auction terms: read and accepted before joining a lot (a bid or a deposit); a new version asks everyone again."""
import pytest

from app.services import auction_terms, auctions
from app.services.settings_service import set_setting
from tests.conftest import make_auction, make_user


def test_clean_options():
    assert auction_terms.clean(None) == {"show": True, "version": 1, "title": {}, "body": {}}
    got = auction_terms.clean({"show": False, "version": "3", "title": {"ru": " Условия ", "en": ""}, "body": {"uzl": "a\n\nb"}})
    assert got == {"show": False, "version": 3, "title": {"ru": "Условия"}, "body": {"uzl": "a\n\nb"}}
    assert auction_terms.clean({"version": "x"})["version"] == 1 and auction_terms.clean({"version": 0})["version"] == 1
    assert auction_terms.paragraphs("one\nstill one\n\n\ntwo\r\n\r\nthree ") == ["one\nstill one", "two", "three"]


def test_texts_fall_back_to_the_standard_ones():
    terms = auction_terms.clean({"title": {"ru": "Правила"}, "body": {}})
    assert auction_terms.title(terms, "ru") == "Правила" and auction_terms.title(terms, "uzl") == "Правила"  # the Mini App's usual fallback: any text beats none
    assert auction_terms.title(auction_terms.clean(None), "en") == "Auction terms"  # nothing saved → the standard heading
    assert auction_terms.body(terms, "uzl").startswith("1. ") and "30/70" in auction_terms.body(terms, "en")


async def test_bid_and_deposit_wait_for_the_terms(db):
    fresh = await make_user(db, 21, terms=False)
    a = await make_auction(db)
    with pytest.raises(auctions.AuctionError) as e:
        await auctions.place_bid(db, a.id, fresh)
    assert e.value.code == "terms"
    with pytest.raises(auctions.AuctionError) as e:
        await auctions.claim_deposit(db, a, fresh, None, None)
    assert e.value.code == "terms"
    assert not await auction_terms.is_accepted(db, fresh)
    await auction_terms.accept(db, fresh)
    assert fresh.auction_terms_version == 1 and fresh.auction_terms_at is not None
    a, bid, _ = await auctions.place_bid(db, a.id, fresh)
    assert bid.user_id == fresh.id and a.bids_count == 1
    assert await auction_terms.accepted_count(db, await auction_terms.load(db)) >= 1


async def test_new_version_asks_again_and_off_asks_nobody(db):
    u = await make_user(db, 22)  # accepted v1
    a = await make_auction(db)
    assert await auction_terms.is_accepted(db, u)
    after = await auction_terms.save(db, body={"en": "New rules"}, reaccept=True)
    assert after["version"] == 2 and after["body"] == {"en": "New rules"}
    assert not await auction_terms.is_accepted(db, u)
    with pytest.raises(auctions.AuctionError) as e:
        await auctions.place_bid(db, a.id, u)
    assert e.value.code == "terms"
    await auction_terms.save(db, show=False)  # switched off: nothing to accept
    assert await auction_terms.is_accepted(db, u)
    await auctions.place_bid(db, a.id, u)
    await auction_terms.save(db, show=True)  # back on: v2 still unaccepted
    assert not await auction_terms.is_accepted(db, u)
    await auction_terms.accept(db, u)
    assert u.auction_terms_version == 2
    # saving without reaccept keeps the version
    assert (await auction_terms.save(db, title={"en": "T"}))["version"] == 2
    await set_setting(db, auction_terms.KEY, {"show": True, "version": 1, "title": {}, "body": {}})  # a reset back to v1 keeps v2 acceptances valid
    assert await auction_terms.is_accepted(db, u)
