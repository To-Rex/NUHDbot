"""Home slider banners (System → Banners): hot offers, sales, new stock and announcements for the Mini App."""
from fastapi import Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import func, select

from app.admin.common import (
    ADS_ROLES,
    DB,
    back,
    dt_local,
    f_bool,
    f_dec,
    f_dt,
    f_i18n,
    f_int,
    f_str,
    render,
    snapshot,
    staff_dep,
    toast,
)
from app.admin.router import router
from app.config import settings
from app.i18n import t
from app.models import Banner, Product, User
from app.services import audit, discounts, media
from app.services import banners as svc
from app.services import series as series_service
from app.services.settings_service import get_setting, set_setting

FIELDS = ["kind", "title", "subtitle", "badge", "color", "product_id", "product_ids", "auto_sale", "link", "old_price", "starts_at", "ends_at", "is_active", "sort"]


async def _ctx(db, staff: User, b: Banner, is_new: bool, errors: list[str] | None = None) -> dict:
    products = (await db.execute(select(Product).where(Product.is_active.is_(True)).order_by(Product.brand, Product.model))).scalars().unique().all()
    if b.product_id and all(p.id != b.product_id for p in products) and b.product:
        products = [b.product, *products]
    drops = await discounts.price_drops(db)
    return {
        "slider_seconds": svc.clean_seconds(await get_setting(db, "slider_seconds"), svc.SECONDS_DEFAULT),
        "drops": drops, "percent": discounts.percent, "on_sale": [p for p in products if p.id in drops],
        "page_title": t(staff.lang, "admin.ban.new" if is_new else "admin.ban.edit"), "b": b, "is_new": is_new, "errors": errors or [],
        "products": products, "kinds": svc.KINDS, "kind_icons": svc.KIND_ICONS, "kind_defaults": svc.KIND_DEFAULTS, "colors": svc.COLORS, "dt_local": dt_local,
    }


async def _apply(db, b: Banner, form, upload: UploadFile | None) -> list[str]:
    errors = []
    b.kind = form.get("kind") if form.get("kind") in svc.KINDS else "hot"
    b.title = f_i18n(form, "title")
    b.subtitle = f_i18n(form, "subtitle")
    if not b.title:
        errors.append("title")
    b.badge = f_str(form, "badge", maxlen=24) or None
    b.color = form.get("color") if form.get("color") in svc.COLORS else "red"
    target = form.get("target")
    pid = f_int(form, "product_id", None) if target == "product" else None
    b.product_id = pid if pid and await db.get(Product, pid) else None
    b.auto_sale = target == "products" and f_bool(form, "auto_sale")
    picked = [int(v) for v in form.getlist("product_ids") if str(v).isdigit()] if target == "products" and not b.auto_sale else []
    known = set((await db.execute(select(Product.id).where(Product.id.in_(picked)))).scalars()) if picked else set()
    b.product_ids = list(dict.fromkeys(i for i in picked if i in known))
    if target == "products" and not b.auto_sale and not b.product_ids:
        errors.append("products")
    b.link = svc.clean_link(form.get("link")) if target == "link" else None
    b.old_price = f_dec(form, "old_price") if b.product_id else None
    b.starts_at, b.ends_at = f_dt(form, "starts_at"), f_dt(form, "ends_at")
    if b.starts_at and b.ends_at and b.ends_at <= b.starts_at:
        errors.append("ends_at")
    b.is_active = f_bool(form, "is_active")
    if f_bool(form, "remove_image"):
        b.image = b.image_thumb = None
    if upload is not None and upload.filename:
        try:
            meta = await media.save_image(upload, "b")
            b.image, b.image_thumb = meta["filename"], meta["thumb"]
        except media.MediaError:
            errors.append("image")
    return errors


SECTION_ICONS = {"banners": "image", "directions": "cube", "auctions": "gavel"}


async def _style_card(db, lang: str, kind: str) -> dict:
    """What a look picker card needs: the looks, the hidden ones, the chosen one and the card shape."""
    if kind == "banner":
        styles, current = svc.STYLES, svc.clean_style(await get_setting(db, "banner_slider_style"))
        hidden = svc.clean_hidden(await get_setting(db, "banner_styles_hidden"), styles, current)
        return {"kind": kind, "styles": styles, "current": current, "hidden": hidden, "shape": svc.clean_shape(await get_setting(db, "banner_slider_shape")),
                "title": t(lang, "admin.ban.style_title"), "hint": t(lang, "admin.ban.style_hint"), "ico": "sparkle", "label": "admin.ban.style",
                "shape_action": "/admin/banners/shape", "style_action": "/admin/banners/style"}
    styles, current = series_service.DIR_STYLES, series_service.clean_style(await get_setting(db, "dir_slider_style"))
    hidden = svc.clean_hidden(await get_setting(db, "dir_styles_hidden"), styles, current)
    return {"kind": kind, "styles": styles, "current": current, "hidden": hidden, "shape": svc.clean_shape(await get_setting(db, "dir_slider_shape")),
            "title": t(lang, "admin.ser.style_title"), "hint": t(lang, "admin.ser.style_hint"), "ico": "cube", "label": "admin.ser.style",
            "shape_action": "/admin/banners/dir-shape", "style_action": "/admin/banners/dir-style"}


async def _card_or_back(request: Request, db, staff: User, kind: str, msg: str, back_to: str = "/admin/banners", kind_: str = "ok"):
    if _hx(request):
        return render(request, staff, "admin/banners/_style_card.html", {"card": await _style_card(db, staff.lang, kind)}, headers=toast(msg, kind_))
    return back(request, back_to, msg, kind_)


async def _terms_ctx(db) -> dict:
    """The home Payment & delivery block: its switch and title, the two shared texts, the standard title per language."""
    return {"terms": svc.clean_terms(await get_setting(db, "home_terms")), "payment_text": await get_setting(db, "payment_text") or {},
            "delivery_text": await get_setting(db, "delivery_text") or {}, "terms_titles": {code: t(code, "home.terms_title") for code in settings.langs},
            "default_lang": settings.default_lang}


async def _conds_ctx(db) -> dict:
    """The home Drive conditions block: its switch, title and descriptions, and the standard texts per language."""
    defaults = {code: {"title": t(code, "home.conditions_title"), **{c: t(code, f"condition.{c}_desc") for c in svc.CONDITIONS}} for code in settings.langs}
    return {"conditions": svc.clean_conditions(await get_setting(db, "home_conditions")), "cond_defaults": defaults, "default_lang": settings.default_lang}


async def _auto_ctx(db) -> dict:
    """The automatic slides' switches and whether each has something to show right now."""
    from datetime import UTC, datetime, timedelta

    from app.enums import AuctionStatus
    from app.models import Auction

    lot = (await db.execute(select(func.count()).select_from(Auction).where(Auction.status.in_((AuctionStatus.LIVE, AuctionStatus.SCHEDULED))))).scalar_one()
    fresh = (await db.execute(select(func.count()).select_from(Product).where(Product.is_active.is_(True), Product.arrived_at >= datetime.now(UTC) - timedelta(days=30)))).scalar_one()
    return {"auto_slides": svc.clean_auto_slides(await get_setting(db, "auto_slides")), "auto_now": {"auction": lot > 0, "new": fresh > 0}}


async def _dir_ctx(db) -> dict:
    """The six directions in their saved order, with the Series page pictures and how many models each has."""
    from app.enums import COLOR_DIRECTION, ProductColor
    from app.services import storage

    pics = await get_setting(db, "direction_images") or {}
    counts = dict((await db.execute(select(Product.color, func.count()).where(Product.is_active.is_(True), Product.color.is_not(None)).group_by(Product.color))).all())
    return {"direction_order": svc.clean_order(await get_setting(db, "direction_order"), svc.DIRECTIONS), "color_dir": {c.value: n for c, n in COLOR_DIRECTION.items()},
            "dir_pics": {c: storage.url(v.get("thumb") or v.get("filename")) for c, v in pics.items() if v}, "dir_counts": counts, "colors": list(ProductColor)}


async def _rows_ctx(db) -> dict:
    rows = await svc.all_banners(db)
    return {"rows": rows, "status": svc.status, "kind_icons": svc.KIND_ICONS, "offers": {b.id: await svc.offer(db, b) for b in rows if svc.is_offer(b)}}


def _hx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


async def _rows_or_back(request: Request, db, staff: User, msg: str | None, kind: str = "ok"):
    """After a move / toggle / delete: the cards swapped in place (htmx), or the page again."""
    if _hx(request):
        return render(request, staff, "admin/banners/_rows.html", await _rows_ctx(db), headers=toast(msg, kind) if msg else None)
    return back(request, "/admin/banners", msg, kind)


@router.get("/banners")
async def banners_list(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    return render(request, staff, "admin/banners/list.html", {
        "page_title": t(staff.lang, "admin.ban.title"), **(await _rows_ctx(db)),
        "slider_seconds": svc.clean_seconds(await get_setting(db, "slider_seconds"), svc.SECONDS_DEFAULT), "seconds_choices": svc.SECONDS_CHOICES,
        "seconds_min": svc.SECONDS_MIN, "seconds_max": svc.SECONDS_MAX,
        "styles": svc.STYLES, "slider_style": svc.clean_style(await get_setting(db, "banner_slider_style")),
        "shapes": svc.SHAPES, "slider_shape": svc.clean_shape(await get_setting(db, "banner_slider_shape")),
        "dir_styles": series_service.DIR_STYLES, "dir_style": series_service.clean_style(await get_setting(db, "dir_slider_style")),
        "dir_shape": svc.clean_shape(await get_setting(db, "dir_slider_shape")),
        "style_cards": {"banner": await _style_card(db, staff.lang, "banner"), "dir": await _style_card(db, staff.lang, "dir")},
        "home_order": svc.clean_order(await get_setting(db, "home_order")), "section_icons": SECTION_ICONS, **(await _dir_ctx(db)), **(await _auto_ctx(db)),
        **(await _terms_ctx(db)), **(await _conds_ctx(db)),
    })


@router.post("/banners/conditions")
async def banners_conditions(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    """The home "Drive conditions" block: on/off, its title and the New / Used / Refresh descriptions (the product page
    shows the same descriptions). An empty field keeps the standard text."""
    form = await request.form()
    before = await get_setting(db, "home_conditions")
    after = svc.clean_conditions({"show": f_bool(form, "show"), "title": f_i18n(form, "cond_title"), "desc": {c: f_i18n(form, "cond_" + c) for c in svc.CONDITIONS}})
    await set_setting(db, "home_conditions", after)
    await audit.log(db, staff.id, "settings.update", "settings", None, {"home_conditions": before}, {"home_conditions": after})
    await db.commit()
    msg = t(staff.lang, "admin.ban.conds_saved")
    if _hx(request):
        return render(request, staff, "admin/banners/_conditions.html", await _conds_ctx(db), headers=toast(msg))
    return back(request, "/admin/banners#home-conditions", msg)


@router.post("/banners/terms")
async def banners_terms(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    """The home "Payment & delivery" block: on/off, its title, and the payment / delivery texts (the same texts the product
    page, the checkout and the bot's help show)."""
    form = await request.form()
    before = {"home_terms": await get_setting(db, "home_terms"), "payment_text": await get_setting(db, "payment_text"), "delivery_text": await get_setting(db, "delivery_text")}
    after = {"home_terms": svc.clean_terms({"show": f_bool(form, "show"), "title": f_i18n(form, "terms_title")}),
             "payment_text": f_i18n(form, "payment_text"), "delivery_text": f_i18n(form, "delivery_text")}
    for key, value in after.items():
        await set_setting(db, key, value)
    await audit.log(db, staff.id, "settings.update", "settings", None, before, after)
    await db.commit()
    msg = t(staff.lang, "admin.ban.terms_saved")
    if _hx(request):
        return render(request, staff, "admin/banners/_terms.html", await _terms_ctx(db), headers=toast(msg))
    return back(request, "/admin/banners#home-terms", msg)


@router.post("/banners/looks")
async def banners_looks(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    """Hide a look from a picker (it stays available under "hidden" and can be restored); the chosen look and the last one cannot go."""
    form = await request.form()
    kind, style, action = form.get("kind") or "", form.get("style") or "", form.get("action") or ""
    if kind not in ("banner", "dir") or action not in ("hide", "show"):
        raise HTTPException(400)
    key = "banner_styles_hidden" if kind == "banner" else "dir_styles_hidden"
    card = await _style_card(db, staff.lang, kind)
    if style not in card["styles"]:
        raise HTTPException(400)
    before = list(card["hidden"])
    if action == "hide" and style == card["current"]:
        return await _card_or_back(request, db, staff, kind, t(staff.lang, "admin.ban.looks_hide_current"), kind_="warn")
    hidden = [h for h in before if h != style] + ([style] if action == "hide" else [])
    hidden = svc.clean_hidden(hidden, card["styles"], card["current"])
    if action == "hide" and style not in hidden:
        return await _card_or_back(request, db, staff, kind, t(staff.lang, "admin.ban.looks_keep_one"), kind_="warn")
    await set_setting(db, key, hidden)
    await audit.log(db, staff.id, "settings.update", "settings", None, {key: before}, {key: hidden})
    await db.commit()
    name = t(staff.lang, card["label"] + "." + style)
    return await _card_or_back(request, db, staff, kind, t(staff.lang, "admin.ban.looks_hidden_msg" if action == "hide" else "admin.ban.looks_restored_msg", name=name))


@router.post("/banners/auto-slides")
async def banners_auto_slides(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    """Switch one automatic slide (the auction, the new arrivals) on or off."""
    key = (await request.form()).get("key") or ""
    if key not in svc.AUTO_SLIDES:
        raise HTTPException(400)
    before = svc.clean_auto_slides(await get_setting(db, "auto_slides"))
    after = before | {key: not before[key]}
    await set_setting(db, "auto_slides", after)
    await audit.log(db, staff.id, "settings.update", "settings", None, {"auto_slides": before}, {"auto_slides": after})
    await db.commit()
    msg = t(staff.lang, "admin.ban.auto_saved", name=t(staff.lang, "admin.ban.auto_" + key), state=t(staff.lang, "admin.ban.on" if after[key] else "admin.ban.off"))
    if _hx(request):
        return render(request, staff, "admin/banners/_auto_slides.html", await _auto_ctx(db), headers=toast(msg))
    return back(request, "/admin/banners#auto-slides", msg)


@router.post("/banners/dir-order")
async def banners_dir_order(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    """The order of the six directions in the Mini App (home slider, catalogue chips) — one step up or down."""
    form = await request.form()
    before = svc.clean_order(await get_setting(db, "direction_order"), svc.DIRECTIONS)
    order = svc.moved(before, form.get("move") or "", form.get("dir") or "", svc.DIRECTIONS)
    await set_setting(db, "direction_order", order)
    await audit.log(db, staff.id, "settings.update", "settings", None, {"direction_order": before}, {"direction_order": order})
    await db.commit()
    from app.enums import COLOR_DIRECTION, ProductColor

    msg = t(staff.lang, "admin.ban.dir_order_saved", name=COLOR_DIRECTION[ProductColor(order[0])])
    if _hx(request):
        return render(request, staff, "admin/banners/_dir_order.html", await _dir_ctx(db), headers=toast(msg))
    return back(request, "/admin/banners#dir-order", msg)


@router.post("/banners/home-order")
async def banners_home_order(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    """Which block the Mini App home opens with: the banner slider, the Directions slider or the Auctions row — one step up or down."""
    form = await request.form()
    before = svc.clean_order(await get_setting(db, "home_order"))
    order = svc.moved(before, form.get("move") or "", form.get("dir") or "")
    await set_setting(db, "home_order", order)
    await audit.log(db, staff.id, "settings.update", "settings", None, {"home_order": before}, {"home_order": order})
    await db.commit()
    msg = t(staff.lang, "admin.ban.home_order_saved", name=t(staff.lang, "admin.ban.sec." + order[0]))
    if _hx(request):  # the card is swapped in place, the page stays where it is
        return render(request, staff, "admin/banners/_home_order.html", {"home_order": order, "section_icons": SECTION_ICONS}, headers=toast(msg))
    return back(request, "/admin/banners#home-order", msg)


@router.post("/banners/settings")
async def banners_settings(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    """The slide time: seconds every slide stays — one for all banners and the auction / new slides."""
    before = await get_setting(db, "slider_seconds")
    n = svc.clean_seconds((await request.form()).get("slider_seconds"), svc.SECONDS_DEFAULT)
    await set_setting(db, "slider_seconds", n)
    await audit.log(db, staff.id, "settings.update", "settings", None, {"slider_seconds": before}, {"slider_seconds": n})
    await db.commit()
    return back(request, "/admin/banners", t(staff.lang, "admin.ban.seconds_saved", n=n))


@router.post("/banners/shape")
async def banners_shape(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    """The banner slider's card shape (tall / wide), separate from the Directions slider's."""
    before = await get_setting(db, "banner_slider_shape")
    shape = svc.clean_shape((await request.form()).get("shape"))
    await set_setting(db, "banner_slider_shape", shape)
    await audit.log(db, staff.id, "settings.update", "settings", None, {"banner_slider_shape": before}, {"banner_slider_shape": shape})
    await db.commit()
    return await _card_or_back(request, db, staff, "banner", t(staff.lang, "admin.shape.saved", name=t(staff.lang, "admin.shape." + shape)))


@router.post("/banners/style")
async def banners_style(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    """How the home slider turns, in the Directions slider's manner: cover flow, orbit, stack, fan, drum, spiral, cascade or pile."""
    before = await get_setting(db, "banner_slider_style")
    style = svc.clean_style((await request.form()).get("style"))
    await set_setting(db, "banner_slider_style", style)
    await audit.log(db, staff.id, "settings.update", "settings", None, {"banner_slider_style": before}, {"banner_slider_style": style})
    await db.commit()
    return await _card_or_back(request, db, staff, "banner", t(staff.lang, "admin.ban.style_saved", name=t(staff.lang, "admin.ban.style." + style)))


@router.post("/banners/dir-style")
async def directions_style(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    """How the Directions slider on the Mini App home moves (cover-flow, orbit, card stack, fan)."""
    before = await get_setting(db, "dir_slider_style")
    style = series_service.clean_style((await request.form()).get("style"))
    await set_setting(db, "dir_slider_style", style)
    await audit.log(db, staff.id, "settings.update", "settings", None, {"dir_slider_style": before}, {"dir_slider_style": style})
    await db.commit()
    return await _card_or_back(request, db, staff, "dir", t(staff.lang, "admin.ser.style_saved", name=t(staff.lang, "admin.ser.style." + style)))


@router.post("/banners/dir-shape")
async def directions_shape(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    """The Directions slider's card shape on the Mini App home: tall portrait cards or wide landscape ones."""
    before = await get_setting(db, "dir_slider_shape")
    shape = svc.clean_shape((await request.form()).get("shape"))
    await set_setting(db, "dir_slider_shape", shape)
    await audit.log(db, staff.id, "settings.update", "settings", None, {"dir_slider_shape": before}, {"dir_slider_shape": shape})
    await db.commit()
    return await _card_or_back(request, db, staff, "dir", t(staff.lang, "admin.shape.saved", name=t(staff.lang, "admin.shape." + shape)))


@router.get("/banners/new")
async def banner_new(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    top = await db.scalar(select(Banner.sort).order_by(Banner.sort.desc()).limit(1))
    b = Banner(kind="hot", title={}, subtitle={}, color="red", is_active=True, sort=(top or 0) + 10)
    return render(request, staff, "admin/banners/form.html", await _ctx(db, staff, b, True))


@router.post("/banners/new")
async def banner_create(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES)), image: UploadFile | None = File(None)):
    form = await request.form()
    top = await db.scalar(select(Banner.sort).order_by(Banner.sort.desc()).limit(1))
    b = Banner(sort=(top or 0) + 10, clicks=0)
    errors = await _apply(db, b, form, image)
    if errors:
        return render(request, staff, "admin/banners/form.html", await _ctx(db, staff, b, True, errors), status_code=400)
    db.add(b)
    await db.flush()
    await audit.log(db, staff.id, "banner.create", "banner", b.id, None, snapshot(b, FIELDS))
    await db.commit()
    return back(request, "/admin/banners", t(staff.lang, "admin.flash.saved"))


@router.get("/banners/{bid}")
async def banner_edit(bid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    b = await db.get(Banner, bid)
    if b is None:
        raise HTTPException(404)
    return render(request, staff, "admin/banners/form.html", await _ctx(db, staff, b, False))


@router.post("/banners/{bid}")
async def banner_save(bid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES)), image: UploadFile | None = File(None)):
    b = await db.get(Banner, bid)
    if b is None:
        raise HTTPException(404)
    form = await request.form()
    before = snapshot(b, FIELDS)
    errors = await _apply(db, b, form, image)
    if errors:
        return render(request, staff, "admin/banners/form.html", await _ctx(db, staff, b, False, errors), status_code=400)
    await audit.log(db, staff.id, "banner.update", "banner", b.id, before, snapshot(b, FIELDS))
    await db.commit()
    return back(request, "/admin/banners", t(staff.lang, "admin.flash.saved"))


@router.post("/banners/{bid}/toggle")
async def banner_toggle(bid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    b = await db.get(Banner, bid)
    if b is None:
        raise HTTPException(404)
    b.is_active = not b.is_active
    await audit.log(db, staff.id, "banner.toggle", "banner", b.id, {"is_active": not b.is_active}, {"is_active": b.is_active})
    await db.commit()
    return await _rows_or_back(request, db, staff, t(staff.lang, "admin.ban.shown" if b.is_active else "admin.ban.hidden"))


@router.post("/banners/{bid}/move")
async def banner_move(bid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    """Swap with the neighbour above / below in the slider order."""
    rows = await svc.all_banners(db)
    i = next((n for n, b in enumerate(rows) if b.id == bid), None)
    j = None if i is None else i + (-1 if (await request.form()).get("dir") == "up" else 1)
    if i is not None and 0 <= j < len(rows):
        rows[i], rows[j] = rows[j], rows[i]
        for n, b in enumerate(rows):
            b.sort = (n + 1) * 10
        await db.commit()
    return await _rows_or_back(request, db, staff, None)


@router.post("/banners/{bid}/delete")
async def banner_delete(bid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    b = await db.get(Banner, bid)
    if b is None:
        raise HTTPException(404)
    await audit.log(db, staff.id, "banner.delete", "banner", b.id, snapshot(b, FIELDS), None)
    await db.delete(b)
    await db.commit()
    return await _rows_or_back(request, db, staff, t(staff.lang, "admin.flash.deleted"))
