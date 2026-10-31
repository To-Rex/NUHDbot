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
