"""Series dictionary: a series colour reaches products that follow it, never ones recoloured by hand."""
from sqlalchemy import select

from app.models import Brand, Product, Series
from app.services import series as svc
from tests.conftest import make_product


async def _setup(db):
    b = Brand(name="Seagate", slug="seagate", series=[], description={}, sort=0, is_active=True)
    db.add(b)
    await db.flush()
    plain, typed, hand, other = [await make_product(db) for _ in range(4)]
    for p, series, color in ((plain, "SkyHawk", None), (typed, "  skyhawk ", None), (hand, "SkyHawk", "gold"), (other, "IronWolf", None)):
        p.brand_id, p.series, p.color = b.id, series, color
    s = Series(brand_id=b.id, name="SkyHawk", key=svc.norm_key("SkyHawk"), color="purple", sort=0)
    db.add(s)
    await db.flush()
    return b, s, plain, typed, hand, other


async def colours(db, *ps):
    return [(await db.execute(select(Product.color).where(Product.id == p.id))).scalar_one() for p in ps]


async def test_counts_and_unlisted(db):
    b, s, *_ = await _setup(db)
    assert (await svc.product_counts(db))[(b.id, "SKYHAWK")] == 3  # spacing and case do not matter
    assert await svc.unlisted(db) == [(b.id, "IronWolf", 1)]
    assert await svc.uncoloured_count(db) == 2


async def test_apply_colour_respects_hand_picked(db):
    b, s, plain, typed, hand, other = await _setup(db)
    assert await svc.apply_color(db, s, None) == 2
    assert await colours(db, plain, typed, hand, other) == ["purple", "purple", "gold", None]
    # the series colour changes: products still on the old series colour follow, the hand-picked one stays
    old, s.color = s.color, "red"
    assert await svc.apply_color(db, s, old) == 2
    assert await colours(db, plain, typed, hand) == ["red", "red", "gold"]


async def test_apply_all_and_dictionary_shape(db):
    b, s, plain, typed, hand, other = await _setup(db)
    assert await svc.apply_all(db) == 2
    assert await colours(db, plain, typed, hand, other) == ["purple", "purple", "gold", None]
    assert await svc.uncoloured_count(db) == 0
    assert svc.as_dict(s) == {"b": b.id, "n": "SkyHawk", "k": "SKYHAWK", "c": "purple"}
    assert svc.clean_color("pink") is None and svc.norm_name("  Iron   Wolf ") == "Iron Wolf"


async def test_colour_for_new_products(db):
    b, s, *_ = await _setup(db)
    assert await svc.colour_for(db, b.id, " skyhawk ") == "purple"  # this brand's series
    assert await svc.colour_for(db, None, "SkyHawk") == "purple"  # no brand: the only colour any brand gives it
    assert await svc.colour_for(db, b.id, "IronWolf Pro") == "red"  # not in the list: the name says NAS
    assert await svc.colour_for(db, b.id, "WD White") == "silver" and await svc.colour_for(db, b.id, "Gold") == "gold"
    assert await svc.colour_for(db, b.id, "Some line", "XYZ123") is None


async def test_home_directions_and_catalog_filter(db):
    """Home 3D slider: every direction with its active models and Series-page picture; a card opens the catalogue of that direction."""
    from starlette.datastructures import QueryParams

    from app.services import catalog
    from app.services.settings_service import set_setting
    from app.web.home import _directions

    nas, cctv, _plain = [await make_product(db) for _ in range(3)]
    nas.color, cctv.color = "red", "purple"
    await db.flush()
    f = catalog.parse_filters(QueryParams("dir=red&dir=pink"))  # unknown directions are dropped
    assert f.colors == ["red"] and f.active_count == 1 and f.to_query()["dir"] == ["red"]
    products, total = await catalog.list_products(db, f)
    assert total == 1 and products[0].id == nas.id
    await set_setting(db, "direction_images", {"red": {"filename": "dir_a.webp", "thumb": "dir_a_t.webp"}})
    cards = {c["color"]: c for c in await _directions(db)}
    assert list(cards) == ["blue", "purple", "red", "gold", "silver", "black"]
    assert cards["red"]["n"] == 1 and cards["red"]["name"] == "NAS" and cards["red"]["img"].endswith("dir_a_t.webp")
    assert cards["blue"]["n"] == 0 and cards["blue"]["img"] is None
