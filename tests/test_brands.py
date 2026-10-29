import pytest

from app.models import Product
from app.services import brands
from app.services.catalog import CAPACITY_PRESETS_GB, capacity_presets
from app.services.settings_service import set_setting
from tests.conftest import make_product


async def test_create_and_sync_product_brand(db):
    b = await brands.create_brand(db, name="Western Digital", series=["Blue\nPurple", "Purple"], warranty_url=" https://x.example ")
    assert b.slug == "western-digital" and b.series == ["Blue", "Purple"] and b.warranty_url == "https://x.example"
    p = await make_product(db)
    brands.sync_product_brand(p, b)
    await db.commit()
    assert p.brand_id == b.id and p.brand == "Western Digital"
    await brands.update_brand(db, b, name="WD")
    await db.commit()
    await db.refresh(p)
    assert p.brand == "WD" and b.slug == "wd"
    with pytest.raises(brands.BrandError) as e:
        await brands.create_brand(db, name="wd")
    assert e.value.code == "duplicate"


async def test_delete_blocked_when_products_exist(db):
    b = await brands.create_brand(db, name="Seagate")
    p = await make_product(db)
    brands.sync_product_brand(p, b)
    await db.flush()
    with pytest.raises(brands.BrandError) as e:
        await brands.delete_brand(db, b)
    assert e.value.code == "in_use" and e.value.ctx["count"] == 1
    brands.sync_product_brand(p, None, fallback_name="Seagate")
    await db.flush()
    await brands.delete_brand(db, b)
    await db.commit()
    assert await brands.get_brand(db, b.id) is None


async def test_reorder_and_catalog_visibility(db):
    a = await brands.create_brand(db, name="A")
    b = await brands.create_brand(db, name="B")
    c = await brands.create_brand(db, name="C", is_active=False)
    await brands.reorder(db, [c.id, b.id, a.id])
    assert [x.name for x in await brands.list_brands(db, active_only=False)] == ["C", "B", "A"]
    # inactive brand without products is hidden from the catalogue; with an active product it stays visible
    assert [x.name for x, _ in await brands.catalog_brands(db)] == ["B", "A"]
    p = await make_product(db)
    brands.sync_product_brand(p, c)
    await db.flush()
    assert [(x.name, n) for x, n in await brands.catalog_brands(db)] == [("C", 1), ("B", 0), ("A", 0)]


async def test_backfill_idempotent(db):
    p1 = await make_product(db)  # brand string "Seagate"
    p2 = await make_product(db)
    p2.brand = "HGST"
    p3 = await make_product(db)
    p3.brand = "NoName Drives"
    await db.flush()
    r1 = await brands.backfill(db)
    await db.commit()
    assert r1["created"] == len(brands.DEFAULT_BRANDS) + 1 and r1["linked"] == 3
    r2 = await brands.backfill(db)
    assert r2 == {"created": 0, "linked": 0}
    names = {b.name for b in await brands.list_brands(db, active_only=False)}
    assert {"Western Digital", "Seagate", "HGST / Ultrastar", "NoName Drives"} <= names
    for p in (p1, p2, p3):
        await db.refresh(p)
    hgst = await brands.find_by_name(db, "HGST / Ultrastar")
    assert p2.brand_id == hgst.id and p1.brand_id and p3.brand_id
    assert (await db.get(Product, p3.id)).brand == "NoName Drives"


async def test_capacity_presets_setting_with_fallback(db):
    assert await capacity_presets(db) == list(CAPACITY_PRESETS_GB)
    await set_setting(db, "capacity_presets", [4000, 1000, 1000, 50, 2000])
    await db.commit()
    assert await capacity_presets(db) == [1000, 2000, 4000]
    await set_setting(db, "capacity_presets", "garbage")
    await db.commit()
    assert await capacity_presets(db) == list(CAPACITY_PRESETS_GB)
