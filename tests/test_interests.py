"""Customer interests: signs written down (not for staff, not twice in a row), the profile, the recommendations, the demand view."""
from datetime import UTC, datetime, timedelta

from starlette.datastructures import QueryParams

from app.enums import Role
from app.services import interests
from app.services.catalog import parse_filters
from tests.conftest import make_product, make_user


async def test_track_dedupes_and_skips_staff(db):
    u = await make_user(db, 61)
    staff = await make_user(db, 62, role=Role.ADMIN)
    p = await make_product(db)
    assert await interests.track(db, u, "view", product=p) is not None
    assert await interests.track(db, u, "view", product=p) is None  # the same product again within the window
    assert await interests.track(db, staff, "view", product=p) is None  # staff browsing is not interest
    assert await interests.track(db, u, "cart", product=p, qty=5) is not None  # carting is always a new sign
    ev = await interests.track(db, u, "search", query="wd purple", results=0)
    assert ev is not None and ev.results == 0 and ev.brand is None
    assert await interests.track(db, u, "search", query="wd purple", results=0) is None
    events = await interests.events_for(db, u.id)
    assert [e.kind for e in events] == ["search", "cart", "view"] and events[1].qty == 5 and events[2].brand == "Seagate" and events[2].capacity_gb == 4000


async def test_catalog_signs(db):
    u = await make_user(db, 63)
    f = parse_filters(QueryParams([("q", "toshiba"), ("brand", "WD"), ("gb", "4000"), ("cond", "new")]))
    await interests.track_catalog(db, u, f, 0)
    events = await interests.events_for(db, u.id)
    kinds = {e.kind: e for e in events}
    assert set(kinds) == {"search", "filter"} and kinds["search"].query == "toshiba" and kinds["search"].results == 0
    assert kinds["filter"].brand == "WD" and kinds["filter"].capacity_gb == 4000 and kinds["filter"].condition == "new" and "4TB" in kinds["filter"].query


async def test_profile_and_recommendations(db):
    u = await make_user(db, 64)
    seagate4 = await make_product(db)  # Seagate 4TB used
    other = await make_product(db, price="90")
    other.brand, other.capacity_gb = "Toshiba", 8000
    await db.flush()
    assert await interests.recommend(db, u) == []  # nothing known yet
    await interests.track(db, u, "view", product=seagate4)
    await interests.track(db, u, "cart", product=seagate4, qty=5)
    await interests.track(db, u, "search", query="seagate", results=3)
    prof = await interests.profile(db, u.id)
    assert prof["enough"] and prof["brands"][0]["value"] == "Seagate" and prof["capacities"][0]["value"] == 4000
    assert prof["kinds"] == {"view": 1, "cart": 1, "search": 1} and prof["price_band"]["low"] == 40.0
    assert interests.score_product(seagate4, prof) > interests.score_product(other, prof)
    recs = await interests.recommend(db, u, limit=5)
    assert seagate4 in recs and (other not in recs or recs.index(seagate4) < recs.index(other))
    assert interests.rerank([other, seagate4], prof)[0] is seagate4
    # an old sign weighs less than a fresh one of the same kind
    old = datetime.now(UTC) - timedelta(days=360)
    weight_new = interests.WEIGHT["view"] * interests._decay(datetime.now(UTC), datetime.now(UTC))
    weight_old = interests.WEIGHT["view"] * interests._decay(old, datetime.now(UTC))
    assert weight_old < weight_new / 8


async def test_demand_and_product_interest(db):
    u1, u2 = await make_user(db, 65), await make_user(db, 66)
    p = await make_product(db, stock=0)
    await interests.track(db, u1, "view", product=p)
    await interests.track(db, u2, "order", product=p, qty=10)
    await interests.track(db, u1, "search", query="Hitachi 10TB", results=0)
    d = await interests.demand(db, days=None)
    brand = next(r for r in d["brands"] if r["value"] == "Seagate")
    assert brand["customers"] >= 2 and brand["stock"] is not None
    combo = next(r for r in d["combos"] if r["value"] == ("Seagate", 4000))
    assert combo["models"] >= 1
    assert any(m["query"] == "hitachi 10tb" for m in d["misses"])
    assert any(r["product"].id == p.id for r in d["products"])
    pi = await interests.product_interest(db, p.id)
    assert pi["customers"] == 2 and pi["kinds"] == {"view": 1, "order": 1} and pi["top"][0]["user"].id == u2.id  # the order outweighs the view
