"""Home slider banners: what is live now, where a tap goes, links stay inside the Mini App."""
from datetime import UTC, datetime, timedelta

from app.models import Banner
from app.services import banners as svc
from tests.conftest import make_product


async def test_live_respects_schedule_and_order(db):
    now = datetime.now(UTC)
    rows = [
        Banner(title={"uz": "a"}, sort=20, is_active=True),
        Banner(title={"uz": "b"}, sort=10, is_active=True, ends_at=now + timedelta(days=1)),
        Banner(title={"uz": "later"}, sort=5, is_active=True, starts_at=now + timedelta(hours=2)),
        Banner(title={"uz": "over"}, sort=5, is_active=True, ends_at=now - timedelta(minutes=1)),
        Banner(title={"uz": "off"}, sort=1, is_active=False),
    ]
    db.add_all(rows)
    await db.flush()
    assert [b.title["uz"] for b in await svc.live(db)] == ["b", "a"]
    assert [svc.status(b, now) for b in rows] == ["live", "live", "scheduled", "ended", "off"]


async def test_target_and_clicks(db):
    p = await make_product(db)
    to_product = Banner(title={"uz": "p"}, product_id=p.id, link="/app/new")
    to_page = Banner(title={"uz": "l"}, link="/app/catalog?use=nas")
    notice = Banner(title={"uz": "n"})
    db.add_all([to_product, to_page, notice])
    await db.flush()
    assert svc.target(to_product) == f"/app/products/{p.id}"  # the product wins over a link
    assert svc.target(to_page) == "/app/catalog?use=nas" and svc.target(notice) is None
    await svc.count_click(db, to_page.id)
    await svc.count_click(db, to_page.id)
    await db.refresh(to_page)
    assert to_page.clicks == 2


def test_links_stay_in_the_mini_app():
    assert svc.clean_link(" /app/new ") == "/app/new"
    for bad in ("https://evil.example", "//evil.example", "/admin", "/app//evil.example", "", None):
        assert svc.clean_link(bad) is None


def test_every_kind_has_an_icon_and_a_valid_default_page():
    assert set(svc.KINDS) == set(svc.KIND_ICONS) == set(svc.KIND_DEFAULTS)
    assert {"new", "hot", "sale", "auction", "tips", "catalog", "info"} == set(svc.KINDS)
    for link, color in svc.KIND_DEFAULTS.values():
        assert color in svc.COLORS and (link is None or svc.clean_link(link) == link)


async def test_offer_banners(db):
    from decimal import Decimal

    from app.models import PriceHistory
    from app.services import discounts

    cut, same, picked = await make_product(db, price="40"), await make_product(db, price="50"), await make_product(db, price="60")
    db.add_all([PriceHistory(product_id=cut.id, old_price=Decimal("50"), new_price=Decimal("40"), currency="USD"),
                PriceHistory(product_id=same.id, old_price=Decimal("45"), new_price=Decimal("55"), currency="USD")])  # a rise, and the price moved on
    await db.flush()
    assert await discounts.price_drops(db) == {cut.id: Decimal("50")} and discounts.percent(Decimal("50"), Decimal("40")) == 20
    sale = Banner(title={"uz": "s"}, auto_sale=True)
    hand = Banner(title={"uz": "h"}, product_ids=[picked.id, cut.id, 999999])
    db.add_all([sale, hand])
    await db.flush()
    assert svc.is_offer(sale) and svc.target(sale) == f"/app/offers/{sale.id}"
    rows, drops = await svc.offer(db, sale)
    assert [p.id for p in rows] == [cut.id] and drops == {cut.id: Decimal("50")}
    rows, drops = await svc.offer(db, hand)  # the order picked; unknown ids dropped
    assert [p.id for p in rows] == [picked.id, cut.id] and set(drops) == {cut.id}


def test_slide_seconds_stay_in_range():
    assert svc.clean_seconds("10") == 10 and svc.clean_seconds(" 12 ") == 12
    assert svc.SECONDS_MIN == 1 and svc.clean_seconds("1") == 1  # one second is allowed
    assert svc.clean_seconds("0") == svc.SECONDS_MIN and svc.clean_seconds("-5") == svc.SECONDS_MIN and svc.clean_seconds("999") == svc.SECONDS_MAX
    assert svc.clean_seconds("", 7) == 7 and svc.clean_seconds(None) is None and svc.clean_seconds("abc", 7) == 7


def test_slider_looks():
    """The slider look picked on the Banners page: parallax by default, anything unknown falls back to it."""
    assert svc.STYLES[:5] == ("parallax", "coverflow", "orbit", "stack", "fan") and len(set(svc.STYLES)) == 14 and set(svc.DIR_LIKE) <= set(svc.STYLES)
    assert [svc.clean_style(v) for v in ("cube", "peek", "fade", None, "", "spin")] == ["cube", "peek", "fade", "parallax", "parallax", "parallax"]


def test_banner_designs():
    """The banner design picked on the Banners page: classic by default, anything unknown falls back to it."""
    assert svc.DESIGNS == ("classic", "card", "glass", "light", "neon", "poster")
    assert [svc.clean_design(v) for v in ("neon", "card", None, "", "gradient")] == ["neon", "card", "classic", "classic", "classic"]
