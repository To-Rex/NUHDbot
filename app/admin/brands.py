"""Brand dictionary management (Каталог → Брендлар)."""
from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response

from app.admin.common import (
    DB,
    PRODUCT_EDIT_ROLES,
    back,
    f_bool,
    f_i18n,
    f_int,
    f_opt,
    f_str,
    render,
    staff_dep,
    toast,
)
from app.admin.router import router
from app.i18n import t
from app.models import Brand, User
from app.services import audit
from app.services import brands as svc

BRAND_FIELDS = ["name", "slug", "warranty_url", "sort", "is_active"]


def _snap(b: Brand) -> dict:
    return {k: getattr(b, k) for k in BRAND_FIELDS}


def _lang(request: Request, staff: User) -> str:
    return request.cookies.get("nuhd_admin_lang") or staff.lang or "uz"


async def _list_ctx(db) -> dict:
    brands = await svc.list_brands(db, active_only=False)
    counts = await svc.product_counts(db)
    return {"brands": brands, "counts": counts}


@router.get("/brands")
async def brands_list(request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    ctx = await _list_ctx(db)
    return render(request, staff, "admin/brands/list.html", {"page_title": t(_lang(request, staff), "admin.brands.title"), **ctx})


@router.get("/brands/new")
async def brand_new(request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    b = Brand(name="", slug="", series=[], description={}, sort=0, is_active=True)
    return render(request, staff, "admin/brands/form.html", {"page_title": t(_lang(request, staff), "admin.brands.new"), "b": b, "is_new": True, "count": 0})


@router.post("/brands/new")
async def brand_create(request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    form = await request.form()
    lang = _lang(request, staff)
    try:
        b = await svc.create_brand(
            db, name=f_str(form, "name", maxlen=60), warranty_url=f_opt(form, "warranty_url", 500),
            description=f_i18n(form, "description"), sort=f_int(form, "sort", None), is_active=f_bool(form, "is_active"),
        )
    except svc.BrandError as e:
        b = Brand(name=f_str(form, "name", maxlen=60), slug="", series=[], description=f_i18n(form, "description"), warranty_url=f_opt(form, "warranty_url", 500), sort=f_int(form, "sort", 0) or 0, is_active=f_bool(form, "is_active"))
        return render(request, staff, "admin/brands/form.html", {"page_title": t(lang, "admin.brands.new"), "b": b, "is_new": True, "count": 0, "error": t(lang, f"admin.brands.{e.code}")}, status_code=400)
    await audit.log(db, staff.id, "brand.create", "brand", b.id, None, _snap(b))
    await db.commit()
    return back(request, f"/admin/brands/{b.id}", t(lang, "admin.brands.saved"))


@router.get("/brands/{bid}")
async def brand_edit(bid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    b = await svc.get_brand(db, bid)
    if not b:
        raise HTTPException(404)
    count = (await svc.product_counts(db)).get(b.id, 0)
    return render(request, staff, "admin/brands/form.html", {"page_title": b.name, "b": b, "is_new": False, "count": count})


@router.post("/brands/{bid}")
async def brand_update(bid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    b = await svc.get_brand(db, bid)
    if not b:
        raise HTTPException(404)
    form = await request.form()
    lang = _lang(request, staff)
    before = _snap(b)
    try:
        await svc.update_brand(
            db, b, name=f_str(form, "name", maxlen=60), warranty_url=f_str(form, "warranty_url", "", 500),
            description=f_i18n(form, "description"), sort=f_int(form, "sort", b.sort), is_active=f_bool(form, "is_active"),
        )
    except svc.BrandError as e:
        await db.rollback()
        await db.refresh(staff)
        b = await svc.get_brand(db, bid)
        count = (await svc.product_counts(db)).get(b.id, 0)
        return render(request, staff, "admin/brands/form.html", {"page_title": b.name, "b": b, "is_new": False, "count": count, "error": t(lang, f"admin.brands.{e.code}")}, status_code=400)
    await audit.log(db, staff.id, "brand.update", "brand", b.id, before, _snap(b))
    await db.commit()
    return back(request, f"/admin/brands/{b.id}", t(lang, "admin.brands.saved"))


@router.post("/brands/{bid}/toggle")
async def brand_toggle(bid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    b = await svc.get_brand(db, bid)
    if not b:
        raise HTTPException(404)
    before = b.is_active
    b.is_active = not before
    await audit.log(db, staff.id, "brand.toggle", "brand", b.id, {"is_active": before}, {"is_active": b.is_active})
    await db.commit()
    counts = await svc.product_counts(db)
    return render(request, staff, "admin/brands/_row.html", {"b": b, "counts": counts}, headers=toast(t(_lang(request, staff), "admin.brands.saved")))


@router.post("/brands/{bid}/delete")
async def brand_delete(bid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    b = await svc.get_brand(db, bid)
    if not b:
        raise HTTPException(404)
    lang = _lang(request, staff)
    try:
        snap = _snap(b)
        await svc.delete_brand(db, b)
    except svc.BrandError as e:
        return back(request, f"/admin/brands/{bid}", t(lang, "admin.brands.delete_blocked", n=e.ctx.get("count", 0)), "warn")
    await audit.log(db, staff.id, "brand.delete", "brand", bid, snap, None)
    await db.commit()
    return back(request, "/admin/brands", t(lang, "admin.brands.deleted"))


@router.post("/brands-reorder")
async def brands_reorder(request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    form = await request.form()
    ids = [int(x) for x in (form.get("order") or "").split(",") if x.strip().isdigit()]
    await svc.reorder(db, ids)
    await audit.log(db, staff.id, "brand.reorder", "brand", None, None, {"order": ids})
    await db.commit()
    return Response(status_code=204)
