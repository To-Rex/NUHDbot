"""Currencies typed in by staff: rate conversion and price formatting for the Mini App."""
from decimal import Decimal

import pytest

from app.admin.currencies import parse_rate
from app.models import Currency
from app.services import currencies as cur

NB = " "


@pytest.fixture
async def rates(db):
    db.add_all([
        Currency(code="USD", name="Dollar", symbol="$", symbol_first=True, rate=Decimal(1), decimals=2, is_base=True, is_active=True, sort=0),
        Currency(code="UZS", name="So'm", symbol="so'm", symbol_first=False, rate=Decimal(12800), decimals=0, is_base=False, is_active=True, sort=1),
        Currency(code="RUB", name="Rubl", symbol="₽", symbol_first=False, rate=Decimal("96.5"), decimals=0, is_base=False, is_active=True, sort=2),
        Currency(code="EUR", name="Euro", symbol="€", symbol_first=True, rate=Decimal("0.92"), decimals=2, is_base=False, is_active=False, sort=3),
    ])
    await db.commit()
    await cur.load(db)
    yield
    cur._cache, cur._loaded_at = {}, 0.0


async def test_convert_and_format(rates):
    assert cur.convert(68, "USD", "UZS") == Decimal(870400)
    assert cur.convert(870400, "UZS", "USD") == Decimal(68)
    assert cur.convert(10, "USD", "XXX") is None
    assert cur.display(68, "USD", "UZS") == f"870{NB}400{NB}so'm"
    assert cur.display(Decimal("40.5"), "USD") == "$40.50"
    assert cur.display(40, "USD") == "$40"
    assert cur.display(40, "USD", "EUR") == "$40"  # hidden from customers: shown as priced
    assert cur.display(40, "CNY", "UZS") == "40 CNY"  # no rate for it: as priced
    assert cur.display(None, "USD", "UZS") == "—"


async def test_prices_helper(rates):
    p = cur.Prices("UZS")
    assert p(68, "USD") == f"870{NB}400{NB}so'm"
    assert p.converts("USD") and not p.converts("UZS")
    assert p.original(68, "USD") == "$68"
    assert p.rate_line("USD") == f"$1 = 12{NB}800{NB}so'm"
    assert p.rate_line("USD", "RUB") == f"$1 = 96.5{NB}₽"  # rates keep their decimals
    assert p.range(17, 229, "USD") == f"217{NB}600–2{NB}931{NB}200{NB}so'm"
    assert p.to_base(1280000) == 100.0  # the catalogue price filter is typed in so'm
    assert p.js("USD") == {"sym": "so'm", "first": False, "dec": 0}
    assert [c.code for c in p.choices] == ["USD", "UZS", "RUB"]
    plain = cur.Prices(None)
    assert plain(68, "USD") == "$68" and plain.to_base(50) == 50 and plain.shown.code == "USD"


def test_parse_rate():
    assert parse_rate("12 800") == Decimal(12800)
    assert parse_rate("96,5") == Decimal("96.5")
    assert parse_rate("0.0001") == Decimal("0.0001")
    for bad in ("", "abc", "0", "-5", "1e20"):
        assert parse_rate(bad) is None


async def test_price_in_every_currency(rates):
    p = cur.Prices("UZS")
    got = [(x["code"], x["text"], x["on"]) for x in p.all(68, "USD")]
    assert got == [("USD", "$68", False), ("UZS", f"870{NB}400{NB}so'm", True), ("RUB", f"6{NB}562{NB}₽", False)]  # hidden EUR left out
    assert p.others(68, "USD") == f"$68 · 6{NB}562{NB}₽"
    assert p.rates("USD") == f"$1 = 12{NB}800{NB}so'm · $1 = 96.5{NB}₽"
    plain = cur.Prices(None)  # nothing picked: the main price stays as priced
    assert plain.others(68, "USD") == f"870{NB}400{NB}so'm · 6{NB}562{NB}₽"
    assert plain.all(68, "CNY") == [] and p.all(None, "USD") == []  # no rate for it / price on request


async def test_main_currency_shown_first(rates, db):
    from sqlalchemy import update

    await db.execute(update(Currency).where(Currency.code == "RUB").values(is_default=True))
    await db.commit()
    await cur.load(db)
    p = cur.Prices(None)  # a customer who never picked: the shop's main currency
    assert p.cur.code == "RUB" and [c.code for c in p.choices] == ["RUB", "USD", "UZS"]
    assert p(68, "USD") == f"6{NB}562{NB}₽" and p.others(68, "USD") == f"$68 · 870{NB}400{NB}so'm"
    assert cur.Prices("UZS")(68, "USD") == f"870{NB}400{NB}so'm"  # their own pick still wins
    await db.execute(update(Currency).values(is_default=False))
    await db.execute(update(Currency).where(Currency.code == "EUR").values(is_default=True))  # hidden: ignored
    await db.commit()
    await cur.load(db)
    assert cur.Prices(None)(68, "USD") == "$68"
