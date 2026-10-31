"""Series dictionary (Catalog → Series): product lines per brand with a colour the product form picks up."""
from fastapi import Depends, File, HTTPException, Request, UploadFile

from app.admin.common import DB, PRODUCT_EDIT_ROLES, back, f_bool, f_int, render, snapshot, staff_dep
from app.admin.router import router
from app.enums import COLOR_DIRECTION, COLOR_EXAMPLES, ProductColor
from app.i18n import t
from app.models import Series, User
from app.services import audit, media, storage
from app.services import banners as banner_service
from app.services import brands as brand_service
from app.services import series as series_service
from app.services.settings_service import get_setting, set_setting

FIELDS = ["brand_id", "name", "color"]


def _lang(request: Request, staff: User) -> str:
    return request.cookies.get("nuhd_admin_lang") or staff.lang or "uz"


@router.get("/series")
async def series_page(request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    brands = await brand_service.list_brands(db, active_only=False)
    order = {b.id: i for i, b in enumerate(brands)}
    rows = sorted(await series_service.list_series(db), key=lambda s: (order.get(s.brand_id, 999), s.sort, s.name.lower()))
    used = await series_service.product_counts(db)
    names = {b.id: b.name for b in brands}
    # the colour belongs to the direction (NAS is red); a series only says which direction it is in
    directions = []
    for c in ProductColor:
        items = [s for s in rows if s.color == c.value]
        directions.append({"c": c, "items": items, "products": sum(used.get((s.brand_id, s.key), 0) for s in items)})
    return render(request, staff, "admin/series/list.html", {
        "page_title": t(_lang(request, staff), "admin.ser.title"), "brands": brands, "names": names, "total": len(rows),
        "directions": directions, "undirected": [s for s in rows if not s.color], "all_series": rows,
        "used": used, "uncoloured": await series_service.uncoloured_count(db),
        "unlisted": [(b, names.get(b, "?"), n, c) for b, n, c in await series_service.unlisted(db) if b in names],
        "colors": list(ProductColor), "color_dir": COLOR_DIRECTION, "color_examples": COLOR_EXAMPLES,
        "dir_images": {c: {"thumb": storage.url(v.get("thumb") or v.get("filename")), "full": storage.url(v.get("filename"))} for c, v in (await get_setting(db, "direction_images") or {}).items() if v},
        "dir_styles": series_service.DIR_STYLES, "dir_style": series_service.clean_style(await get_setting(db, "dir_slider_style")),
        "shapes": banner_service.SHAPES, "dir_shape": banner_service.clean_shape(await get_setting(db, "dir_slider_shape")),
    })


@router.post("/series/slider-shape")
async def slider_shape(request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    """The directions slider's card shape on the Mini App home: tall portrait cards or wide landscape ones."""
    before = await get_setting(db, "dir_slider_shape")
    shape = banner_service.clean_shape((await request.form()).get("shape"))
    await set_setting(db, "dir_slider_shape", shape)
    await audit.log(db, staff.id, "settings.update", "settings", None, {"dir_slider_shape": before}, {"dir_slider_shape": shape})
    await db.commit()
    lang = _lang(request, staff)
    return back(request, "/admin/series", t(lang, "admin.shape.saved", name=t(lang, "admin.shape." + shape)))


@router.post("/series/slider-style")
async def slider_style(request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    """How the directions slider moves on the Mini App home (cover-flow, orbit, card stack, fan)."""
    before = await get_setting(db, "dir_slider_style")
    style = series_service.clean_style((await request.form()).get("style"))
    await set_setting(db, "dir_slider_style", style)
    await audit.log(db, staff.id, "settings.update", "settings", None, {"dir_slider_style": before}, {"dir_slider_style": style})
    await db.commit()
    lang = _lang(request, staff)
    return back(request, "/admin/series", t(lang, "admin.ser.style_saved", name=t(lang, "admin.ser.style." + style)))


def _direction(color: str) -> ProductColor:
    try:
        return ProductColor(color)
    except ValueError:
        raise HTTPException(404) from None


@router.post("/series/direction/{color}/image")
async def direction_image(color: str, request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES)), image: UploadFile = File(...)):
    """A picture for a catalogue direction (shown on its card)."""
    c = _direction(color)
    lang = _lang(request, staff)
    try:
        meta = await media.save_image(image, "dir")
    except media.MediaError:
        return back(request, "/admin/series", t(lang, "admin.ser.err.image"), "bad")
    images = dict(await get_setting(db, "direction_images") or {})
    images[c.value] = {"filename": meta["filename"], "thumb": meta["thumb"]}
    await set_setting(db, "direction_images", images)
    await audit.log(db, staff.id, "series.direction_image", "direction", c.value, None, images[c.value])
    await db.commit()
    return back(request, "/admin/series", t(lang, "admin.ser.image_saved", name=COLOR_DIRECTION[c]))


@router.post("/series/direction/{color}/image/delete")
async def direction_image_delete(color: str, request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    c = _direction(color)
    images = dict(await get_setting(db, "direction_images") or {})
    before = images.pop(c.value, None)
    await set_setting(db, "direction_images", images)
    await audit.log(db, staff.id, "series.direction_image_delete", "direction", c.value, before, None)
    await db.commit()
    return back(request, "/admin/series", t(_lang(request, staff), "admin.ser.image_removed", name=COLOR_DIRECTION[c]))


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
