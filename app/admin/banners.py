"""Home slider banners (System → Banners): hot offers, sales, new stock and announcements for the Mini App."""
from fastapi import Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import select

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
)
from app.admin.router import router
from app.i18n import t
from app.models import Banner, Product, User
from app.services import audit, discounts, media
from app.services import banners as svc

FIELDS = ["kind", "title", "subtitle", "badge", "color", "product_id", "product_ids", "auto_sale", "link", "old_price", "starts_at", "ends_at", "is_active", "sort"]


async def _ctx(db, staff: User, b: Banner, is_new: bool, errors: list[str] | None = None) -> dict:
    products = (await db.execute(select(Product).where(Product.is_active.is_(True)).order_by(Product.brand, Product.model))).scalars().unique().all()
    if b.product_id and all(p.id != b.product_id for p in products) and b.product:
        products = [b.product, *products]
    drops = await discounts.price_drops(db)
    return {
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


@router.get("/banners")
async def banners_list(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    rows = await svc.all_banners(db)
    offers = {b.id: await svc.offer(db, b) for b in rows if svc.is_offer(b)}
    return render(request, staff, "admin/banners/list.html", {"page_title": t(staff.lang, "admin.ban.title"), "rows": rows, "status": svc.status, "kind_icons": svc.KIND_ICONS, "offers": offers})


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
    return back(request, "/admin/banners", t(staff.lang, "admin.ban.shown" if b.is_active else "admin.ban.hidden"))


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
    return back(request, "/admin/banners")


@router.post("/banners/{bid}/delete")
async def banner_delete(bid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    b = await db.get(Banner, bid)
    if b is None:
        raise HTTPException(404)
    await audit.log(db, staff.id, "banner.delete", "banner", b.id, snapshot(b, FIELDS), None)
    await db.delete(b)
    await db.commit()
    return back(request, "/admin/banners", t(staff.lang, "admin.flash.deleted"))
