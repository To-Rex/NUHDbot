from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import urlencode

from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import and_, func, or_, select
from starlette.datastructures import UploadFile

from app.admin.common import (
    DB,
    FINANCE_VIEW,
    PRODUCT_EDIT_ROLES,
    PRODUCT_ROLES,
    back,
    can,
    f_bool,
    f_dec,
    f_i18n,
    f_int,
    f_opt,
    f_str,
    nav_badges,
    paginate,
    qpage,
    render,
    snapshot,
    staff_dep,
    toast,
)
from app.admin.router import router
from app.config import settings
from app.enums import (
    COLOR_DIRECTION,
    COLOR_EXAMPLES,
    Condition,
    FormFactor,
    ImageKind,
    Interface,
    ProductColor,
    Purpose,
    Role,
    TestStatus,
)
from app.i18n import t
from app.models import PriceHistory, Product, ProductImage, User
from app.services import audit, media, model_dict
from app.services import brands as brand_service
from app.services.catalog import capacity_presets

PRODUCT_FIELDS = ["brand", "brand_id", "model", "label_model", "series", "capacity_gb", "interface", "form_factor", "condition", "color", "price", "currency", "cost_price", "stock", "min_order", "box_qty", "full_box_only", "seller_warranty_months", "factory_warranty_months", "test_status", "hours_used", "health", "is_active", "sale_allowed", "arrived_at", "sort", "rpm", "cache_mb"]
WARRANTY_DEFAULTS = {Condition.NEW: (12, 36), Condition.USED: (6, 0), Condition.REFRESH: (6, 0)}


def _ctx_lists():
    return {"conditions": list(Condition), "interfaces": list(Interface), "form_factors": list(FormFactor), "tests": list(TestStatus), "purposes": list(Purpose),
            "colors": list(ProductColor), "color_dir": COLOR_DIRECTION, "color_examples": COLOR_EXAMPLES}


async def _form_ctx(db, p: Product | None = None) -> dict:
    """Brands (active + the product's own even if hidden) and capacity presets for the product form."""
    brands = await brand_service.list_brands(db, active_only=True)
    if p is not None and p.brand_id and all(b.id != p.brand_id for b in brands):
        own = await brand_service.get_brand(db, p.brand_id)
        if own:
            brands.append(own)
    return {"brands": brands, "capacities": await capacity_presets(db), "models": await model_dict.known_models(db), **_ctx_lists()}


def parse_capacity(form) -> int:
    """Capacity entered as value + unit (TB default, 1 TB = 1000 GB); legacy plain `capacity_gb` still accepted. Returns 0 when invalid."""
    raw = (form.get("capacity_value") or "").strip().replace(",", ".")
    if not raw:
        return f_int(form, "capacity_gb", 0) or 0
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return 0
    if value <= 0:
        return 0
    gb = value * (1000 if (form.get("capacity_unit") or "tb").lower() == "tb" else 1)
    return int(gb.to_integral_value(rounding=ROUND_HALF_UP)) if gb <= 1_000_000 else 0


@router.get("/products")
async def products_list(request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_ROLES))):
    q = request.query_params
    base = []  # search, brand and condition narrow every tab
    if q.get("q"):
        like = f"%{q['q'].strip()}%"
        base.append(or_(Product.brand.ilike(like), Product.model.ilike(like), Product.label_model.ilike(like), Product.series.ilike(like)))
    if q.get("brand_id", "").isdigit():
        base.append(Product.brand_id == int(q["brand_id"]))
    elif q.get("brand"):
        base.append(Product.brand == q["brand"])
    if q.get("cond"):
        base.append(Product.condition == q["cond"])
    avail = Product.stock - Product.reserved
    views = {
        "sale": and_(Product.is_active.is_(True), Product.sale_allowed.is_(True), avail > 0),
        "out": avail <= 0,
        "stopped": Product.sale_allowed.is_(False),
        "hidden": Product.is_active.is_(False),
    }
    # older links (?stock=out, ?active=0) land on the matching tab
    view = q.get("view") or ("out" if q.get("stock") == "out" else "hidden" if q.get("active") == "0" else "")
    view = view if view in views else ""
    counts = (await db.execute(select(func.count(Product.id), *(func.count(Product.id).filter(c) for c in views.values())).where(*base))).one()
    keep = urlencode({k: q[k] for k in ("q", "brand_id", "cond") if q.get(k)})
    tabs = [(key, n, "?" + "&".join(filter(None, [keep, f"view={key}" if key else ""]))) for key, n in zip(["", *views], counts, strict=True)]
    stmt = select(Product).where(*base, *([views[view]] if view else []))
    stmt = stmt.order_by(Product.is_active.desc(), Product.sort.desc(), Product.id.desc())
    items, total, pages = await paginate(db, stmt, qpage(request), 40)
    brands = await brand_service.list_brands(db, active_only=False)
    return render(
        request, staff, "admin/products/list.html",
        {"page_title": t(staff.lang, "admin.prod.title"), "items": items, "total": total, "pages": pages, "page": qpage(request), "brands": brands,
         "tabs": tabs, "view": view, "filtered": bool(keep), "badges": await nav_badges(db), **_ctx_lists()},
    )


@router.get("/products/new")
async def product_new(request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    p = Product(brand="", model="", capacity_gb=1000, condition=Condition.NEW, currency=settings.default_currency, seller_warranty_months=12, factory_warranty_months=36, min_order=1, stock=0, purposes=[], specs={}, description={}, compatibility={}, test_summary={}, delivery_note={}, arrived_at=datetime.now(UTC))
    return render(request, staff, "admin/products/form.html", {"page_title": t(staff.lang, "admin.prod.new"), "prod": p, "is_new": True, "history": [], **(await _form_ctx(db, p))})


async def _apply_form(db, p: Product, form, staff: User, is_new: bool) -> list[str]:
    errors = []
    b = await brand_service.resolve_brand(db, form.get("brand_id"), f_str(form, "brand_other", maxlen=60) or f_str(form, "brand", maxlen=60))
    brand_service.sync_product_brand(p, b, fallback_name="")
    p.model = f_str(form, "model", maxlen=120)
    if not p.brand or not p.model:
        errors.append("brand/model")
    p.label_model = f_opt(form, "label_model", 120)
    p.series = f_opt(form, "series", 60)
    p.capacity_gb = parse_capacity(form)
    if p.capacity_gb <= 0:
        errors.append("capacity_gb")
    p.interface = Interface(form.get("interface") or "SATA")
    p.form_factor = FormFactor(form.get("form_factor") or "3.5")
    p.condition = Condition(form.get("condition") or "new")
    if p.condition == Condition.REFRESH and not p.label_model:
        errors.append("label_model")
    p.purposes = [x for x in form.getlist("purposes") if x in [e.value for e in Purpose]]
    p.color = form.get("color") if form.get("color") in [c.value for c in ProductColor] else None
    p.rpm = f_int(form, "rpm", None)
    p.cache_mb = f_int(form, "cache_mb", None)
    old_price = p.price
    p.price = f_dec(form, "price")
    p.currency = (f_str(form, "currency", settings.default_currency, 3) or "USD").upper()
    if can(staff, FINANCE_VIEW):
        p.cost_price = f_dec(form, "cost_price")
    p.stock = max(0, f_int(form, "stock", 0) or 0)
    p.min_order = max(1, f_int(form, "min_order", 1) or 1)
    p.box_qty = f_int(form, "box_qty", None)
    p.full_box_only = f_bool(form, "full_box_only")
    sw, fw = WARRANTY_DEFAULTS[p.condition]
    p.seller_warranty_months = f_int(form, "seller_warranty_months", sw)
    p.factory_warranty_months = f_int(form, "factory_warranty_months", fw)
    p.test_status = TestStatus(form.get("test_status") or "untested")
    p.hours_used = f_int(form, "hours_used", None)
    p.health = f_opt(form, "health", 40)
    p.test_summary = f_i18n(form, "test_summary")
    p.description = f_i18n(form, "description")
    p.compatibility = f_i18n(form, "compatibility")
    p.delivery_note = f_i18n(form, "delivery_note")
    keys, vals = form.getlist("spec_key"), form.getlist("spec_value")
    p.specs = {k.strip(): v.strip() for k, v in zip(keys, vals, strict=False) if k.strip()}
    p.is_active = f_bool(form, "is_active")
    p.sale_allowed = f_bool(form, "sale_allowed")
    p.sort = f_int(form, "sort", 0) or 0
    arrived = (form.get("arrived_at") or "").strip()
    p.arrived_at = datetime.fromisoformat(arrived).replace(tzinfo=UTC) if arrived else None
    if not is_new and (old_price or 0) != (p.price or 0):
        db.add(PriceHistory(product_id=p.id, old_price=old_price, new_price=p.price, currency=p.currency, changed_by=staff.id))
        await audit.log(db, staff.id, "product.price", "product", p.id, {"price": str(old_price)}, {"price": str(p.price)})
    return errors


@router.post("/products/new")
async def product_create(request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    form = await request.form()
    p = Product(purposes=[], specs={}, description={}, compatibility={}, test_summary={}, delivery_note={})
    errors = await _apply_form(db, p, form, staff, True)
    if errors:
        return render(request, staff, "admin/products/form.html", {"page_title": t(staff.lang, "admin.prod.new"), "prod": p, "is_new": True, "errors": errors, "history": [], **(await _form_ctx(db, p))}, status_code=400)
    db.add(p)
    await db.flush()
    if p.price is not None:
        db.add(PriceHistory(product_id=p.id, old_price=None, new_price=p.price, currency=p.currency, changed_by=staff.id, note="created"))
    added, img_msg, img_kind = await _add_images(db, p, form.getlist("images"), form.get("images_kind"), staff.lang)
    await audit.log(db, staff.id, "product.create", "product", p.id, None, {**snapshot(p, PRODUCT_FIELDS), "images": added})
    await db.commit()
    return back(request, f"/admin/products/{p.id}", t(staff.lang, "admin.flash.saved") if img_kind == "ok" else img_msg, "ok" if img_kind == "ok" else img_kind)


@router.get("/products/{pid}")
async def product_edit(pid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_ROLES))):
    p = await db.get(Product, pid)
    if not p:
        raise HTTPException(404)
    history = (await db.execute(select(PriceHistory).where(PriceHistory.product_id == pid).order_by(PriceHistory.id.desc()).limit(20))).scalars().all()
    return render(request, staff, "admin/products/form.html", {"page_title": f"{p.brand} {p.model}", "prod": p, "is_new": False, "history": history, "readonly": not can(staff, PRODUCT_EDIT_ROLES | {Role.TESTER}), **(await _form_ctx(db, p))})


@router.post("/products/{pid}")
async def product_update(pid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES, Role.TESTER))):
    p = await db.get(Product, pid)
    if not p:
        raise HTTPException(404)
    form = await request.form()
    before = snapshot(p, PRODUCT_FIELDS)
    if staff.role == Role.TESTER:
        # tester may only touch test related fields
        p.test_status = TestStatus(form.get("test_status") or p.test_status)
        p.hours_used = f_int(form, "hours_used", None)
        p.health = f_opt(form, "health", 40)
        p.test_summary = f_i18n(form, "test_summary")
        errors = []
    else:
        errors = await _apply_form(db, p, form, staff, False)
    if errors:
        history = (await db.execute(select(PriceHistory).where(PriceHistory.product_id == pid).order_by(PriceHistory.id.desc()).limit(20))).scalars().all()
        return render(request, staff, "admin/products/form.html", {"page_title": f"{p.brand} {p.model}", "prod": p, "is_new": False, "errors": errors, "history": history, **(await _form_ctx(db, p))}, status_code=400)
    await audit.log(db, staff.id, "product.update", "product", p.id, before, snapshot(p, PRODUCT_FIELDS))
    await db.commit()
    return back(request, f"/admin/products/{p.id}", t(staff.lang, "admin.flash.saved"))


@router.post("/products/{pid}/toggle")
async def product_toggle(pid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES, Role.WAREHOUSE))):
    p = await db.get(Product, pid)
    if not p:
        raise HTTPException(404)
    form = await request.form()
    field = form.get("field")
    if field not in ("is_active", "sale_allowed"):
        raise HTTPException(400)
    before = getattr(p, field)
    setattr(p, field, not before)
    await audit.log(db, staff.id, f"product.{field}", "product", p.id, {field: before}, {field: not before})
    await db.commit()
    return render(request, staff, "admin/products/_row.html", {"prod": p}, headers=toast(t(staff.lang, "admin.flash.saved")))


@router.post("/products-bulk")
async def product_bulk(request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    form = await request.form()
    ids = [int(x) for x in form.getlist("ids") if x.isdigit()]
    action = form.get("action")
    if ids and action in ("activate", "deactivate", "allow_sale", "stop_sale"):
        rows = (await db.execute(select(Product).where(Product.id.in_(ids)))).scalars().all()
        for p in rows:
            if action == "activate":
                p.is_active = True
            elif action == "deactivate":
                p.is_active = False
            elif action == "allow_sale":
                p.sale_allowed = True
            else:
                p.sale_allowed = False
        await audit.log(db, staff.id, f"product.bulk.{action}", "product", ",".join(map(str, ids)))
        await db.commit()
    return back(request, request.headers.get("referer") or "/admin/products", t(staff.lang, "admin.flash.saved"))


# ---------------- images ----------------

async def _add_images(db, p: Product, uploads, kind_raw, lang: str) -> tuple[int, str, str]:
    """Convert + store uploaded files as product images. Returns (added, toast message, toast kind)."""
    kind = ImageKind(kind_raw or "sample")
    files = [f for f in uploads if isinstance(f, UploadFile) and f.filename]
    existing = len(p.images) if p.id and "images" in p.__dict__ else 0
    msg, mkind, added = t(lang, "admin.flash.saved"), "ok", 0
    for f in files:
        if existing + added >= settings.max_images_per_product:
            msg, mkind = t(lang, "admin.prod.too_many_images"), "warn"
            break
        try:
            meta = await media.save_image(f, prefix=f"p{p.id}")
        except media.MediaError as e:
            msg, mkind = t(lang, "admin.prod.image_error", e=str(e)), "bad"
            continue
        db.add(ProductImage(product_id=p.id, kind=kind, is_cover=existing == 0 and added == 0, sort=existing + added, **meta))
        added += 1
    return added, msg, mkind


@router.post("/products/{pid}/images")
async def product_images_upload(pid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    p = await db.get(Product, pid)
    if not p:
        raise HTTPException(404)
    form = await request.form()
    added, msg, mkind = await _add_images(db, p, form.getlist("files"), form.get("kind"), staff.lang)
    await audit.log(db, staff.id, "product.images.add", "product", p.id, None, {"added": added})
    await db.commit()
    await db.refresh(p)
    return render(request, staff, "admin/products/_images.html", {"prod": p}, headers=toast(msg, mkind))


@router.post("/products/{pid}/images/{iid}/{action}")
async def product_image_action(pid: int, iid: int, action: str, request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    p = await db.get(Product, pid)
    img = await db.get(ProductImage, iid)
    if not p or not img or img.product_id != p.id:
        raise HTTPException(404)
    if action == "cover":
        for i in p.images:
            i.is_cover = i.id == img.id
    elif action == "delete":
        await media.delete_files(img.filename, img.thumb)
        was_cover = img.is_cover
        await db.delete(img)
        await db.flush()
        await db.refresh(p)
        if was_cover and p.images:
            p.images[0].is_cover = True
    elif action == "kind":
        img.kind = ImageKind.REAL if img.kind == ImageKind.SAMPLE else ImageKind.SAMPLE
    else:
        raise HTTPException(400)
    await audit.log(db, staff.id, f"product.images.{action}", "product", p.id, None, {"image": iid})
    await db.commit()
    await db.refresh(p)
    return render(request, staff, "admin/products/_images.html", {"prod": p}, headers=toast(t(staff.lang, "admin.flash.saved")))


@router.post("/products/{pid}/images-reorder")
async def product_images_reorder(pid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    p = await db.get(Product, pid)
    if not p:
        raise HTTPException(404)
    form = await request.form()
    order = [int(x) for x in (form.get("order") or "").split(",") if x.strip().isdigit()]
    for i in p.images:
        if i.id in order:
            i.sort = order.index(i.id)
    await db.commit()
    return Response(status_code=204)


@router.post("/products-samples")
async def product_load_samples(request: Request, db: DB, staff: User = Depends(staff_dep(Role.ADMIN))):
    """Load the SAMPLE catalogue (clearly marked images) so a fresh deployment has something to look at."""
    from scripts.seed import seed_demo

    existing = (await db.execute(select(Product.id).limit(1))).scalar_one_or_none()
    if existing is not None:
        return back(request, "/admin/products", t(_lang(request), "admin.prod.samples_exist"), "warn")
    await seed_demo()
    await audit.log(db, staff.id, "product.load_samples", "product", None, None, {"by": staff.login})
    await db.commit()
    return back(request, "/admin/products", t(_lang(request), "admin.prod.samples_loaded"))


def _lang(request: Request) -> str:
    return getattr(request.state, "admin_lang", None) or request.cookies.get("nuhd_admin_lang") or "uz"
