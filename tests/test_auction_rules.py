"""Lot rules: one common text for every lot (the standard one until the admin writes theirs); a lot may carry its own instead."""
from app.services import auction_rules
from tests.conftest import make_auction


def test_clean_and_fallbacks():
    assert auction_rules.clean(None) == {"body": {}}
    assert auction_rules.clean({"body": {"ru": " Правила ", "en": "", "uzl": None}}) == {"body": {"ru": "Правила"}}
    empty = auction_rules.clean(None)
    assert "2" in auction_rules.common_text(empty, "en")  # the standard text (anti-sniping minutes)
    assert auction_rules.common_text({"body": {"ru": "Свои"}}, "uzl") == "Свои"  # any text beats the standard one


async def test_lot_shows_its_own_rules_else_the_common_ones(db):
    a = await make_auction(db)
    common = await auction_rules.save(db, body={"ru": "Общие правила", "en": "Common rules"})
    assert not auction_rules.has_own(a) and auction_rules.text_for(a, common, "en") == "Common rules"
    a.rules = {"en": "Pickup only", "ru": ""}
    assert auction_rules.has_own(a) and auction_rules.text_for(a, common, "en") == "Pickup only" and auction_rules.text_for(a, common, "ru") == "Pickup only"
    assert await auction_rules.own_count(db) == 1 and await auction_rules.total_count(db) == 1
    a.rules = {}
    assert auction_rules.text_for(a, common, "ru") == "Общие правила"
