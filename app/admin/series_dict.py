"""Series dictionary (Catalog → Series): product lines per brand with a colour the product form picks up."""
from fastapi import Depends, Request

from app.admin.common import DB, PRODUCT_EDIT_ROLES, back, f_bool, f_int, render, snapshot, staff_dep
from app.admin.router import router
from app.enums import COLOR_DIRECTION, COLOR_EXAMPLES, ProductColor
from app.i18n import t
from app.models import Series, User
from app.services import audit
from app.services import brands as brand_service
from app.services import series as series_service

FIELDS = ["brand_id", "name", "color"]


def _lang(request: Request, staff: User) -> str:
    return request.cookies.get("nuhd_admin_lang") or staff.lang or "uz"


@router.get("/series")
async def series_page(request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    brands = await brand_service.list_brands(db, active_only=False)
    rows = await series_service.list_series(db)
    by_brand: dict[int, list[Series]] = {}
    for s in rows:
        by_brand.setdefault(s.brand_id, []).append(s)
    names = {b.id: b.name for b in brands}
    return render(request, staff, "admin/series/list.html", {
        "page_title": t(_lang(request, staff), "admin.ser.title"), "brands": brands, "total": len(rows),
        # brands with series first, then active brands still without any
        "groups": [(b, by_brand.get(b.id, [])) for b in brands if by_brand.get(b.id)] + [(b, []) for b in brands if b.is_active and not by_brand.get(b.id)],
        "used": await series_service.product_counts(db), "uncoloured": await series_service.uncoloured_count(db),
        "unlisted": [(b, names.get(b, "?"), n, c) for b, n, c in await series_service.unlisted(db) if b in names],
        "colors": list(ProductColor), "color_dir": COLOR_DIRECTION, "color_examples": COLOR_EXAMPLES,
    })


async def _read(request: Request, db, staff: User, s: Series | None):
    """Validated (brand, name, colour, apply) from the dialog, or an error message."""
    form = await request.form()
    lang = _lang(request, staff)
    brand = await brand_service.get_brand(db, f_int(form, "brand_id", 0) or 0)
    name = series_service.norm_name(form.get("name"))
    if not brand:
        return None, t(lang, "admin.ser.err.brand")
    if not name:
        return None, t(lang, "admin.ser.err.name")
    if await series_service.find(db, brand.id, name, exclude_id=s.id if s else None):
        return None, t(lang, "admin.ser.err.taken", name=name, brand=brand.name)
    return (brand, name, series_service.clean_color(form.get("color")), f_bool(form, "apply")), None


def _done(lang: str, msg_key: str, name: str, changed: int) -> str:
    msg = t(lang, msg_key, name=name)
    return msg + (" " + t(lang, "admin.ser.applied", n=changed) if changed else "")


@router.post("/series")
async def series_add(request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    data, err = await _read(request, db, staff, None)
    if err:
        return back(request, "/admin/series", err, "bad")
    brand, name, color, apply = data
    s = Series(brand_id=brand.id, name=name, key=series_service.norm_key(name), color=color, sort=500)
    db.add(s)
    await db.flush()
    changed = await series_service.apply_color(db, s, None) if apply else 0
    await audit.log(db, staff.id, "series.create", "series", s.id, None, {**snapshot(s, FIELDS), "products_recoloured": changed})
    await db.commit()
    return back(request, "/admin/series", _done(_lang(request, staff), "admin.ser.added", name, changed))


@router.post("/series/apply-colours")
async def series_apply_all(request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    """One click: products without a colour take their series colour (hand-picked colours are left alone)."""
    changed = await series_service.apply_all(db)
    await audit.log(db, staff.id, "series.apply_all", "product", None, None, {"products_recoloured": changed})
    await db.commit()
    return back(request, "/admin/series", t(_lang(request, staff), "admin.ser.applied_all", n=changed))


@router.post("/series/{sid}")
async def series_save(sid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    s = await db.get(Series, sid)
    if s is None:
        return back(request, "/admin/series", t(_lang(request, staff), "admin.flash.error"), "bad")
    data, err = await _read(request, db, staff, s)
    if err:
        return back(request, "/admin/series", err, "bad")
    brand, name, color, apply = data
    before, old_color = snapshot(s, FIELDS), s.color
    s.brand_id, s.name, s.key, s.color = brand.id, name, series_service.norm_key(name), color
    await db.flush()
    changed = await series_service.apply_color(db, s, old_color) if apply else 0
    await audit.log(db, staff.id, "series.update", "series", s.id, before, {**snapshot(s, FIELDS), "products_recoloured": changed})
    await db.commit()
    return back(request, "/admin/series", _done(_lang(request, staff), "admin.ser.saved", name, changed))


@router.post("/series/{sid}/delete")
async def series_delete(sid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    s = await db.get(Series, sid)
    if s is None:
        return back(request, "/admin/series", t(_lang(request, staff), "admin.flash.error"), "bad")
    await audit.log(db, staff.id, "series.delete", "series", s.id, snapshot(s, FIELDS), None)
    await db.delete(s)  # products keep the series text and colour they have
    await db.commit()
    return back(request, "/admin/series", t(_lang(request, staff), "admin.ser.deleted", name=s.name))
