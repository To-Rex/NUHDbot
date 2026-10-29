"""Model dictionary (Каталог → Моделлар): bulk entry per brand, used by the product form autocomplete."""
from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.admin.common import DB, PRODUCT_EDIT_ROLES, back, f_int, render, staff_dep
from app.admin.router import router
from app.i18n import t
from app.models import User
from app.services import audit, model_dict
from app.services import brands as brand_service


def _lang(request: Request, staff: User) -> str:
    return request.cookies.get("nuhd_admin_lang") or staff.lang or "uz"


def _wants_json(request: Request) -> bool:
    return request.headers.get("X-Requested-With") == "fetch" or "application/json" in request.headers.get("accept", "")


async def _payload(db, brand_id: int | None) -> dict:
    return {"models": [model_dict.as_dict(m) for m in await model_dict.list_models(db, brand_id)], "known": await model_dict.known_models(db)}


@router.get("/models")
async def models_page(request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    brands = await brand_service.list_brands(db, active_only=False)
    bid = f_int(request.query_params, "brand_id", None)
    models = await model_dict.list_models(db, bid)
    by_brand: dict[int, list] = {}
    for m in models:
        by_brand.setdefault(m.brand_id, []).append(m)
    return render(request, staff, "admin/models/list.html", {"page_title": t(_lang(request, staff), "admin.models.title"), "brands": brands, "by_brand": by_brand, "counts": await model_dict.counts(db), "brand_id": bid, "total": len(models)})


@router.get("/models/known")
async def models_known(request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    return JSONResponse(await _payload(db, f_int(request.query_params, "brand_id", None)))


@router.post("/models/bulk")
async def models_bulk(request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    form = await request.form()
    lang = _lang(request, staff)
    brand = await brand_service.get_brand(db, f_int(form, "brand_id", 0) or 0)
    if not brand:
        if _wants_json(request):
            return JSONResponse({"error": t(lang, "admin.models.pick_brand")}, status_code=400)
        return back(request, "/admin/models", t(lang, "admin.models.pick_brand"), "bad")
    added, skipped = await model_dict.bulk_add(db, brand, form.get("lines") or "")
    if added:
        await audit.log(db, staff.id, "model.bulk_add", "brand", brand.id, None, {"added": [m.name for m in added], "skipped": skipped})
    await db.commit()
    msg = t(lang, "admin.models.added", n=len(added), s=skipped)
    if _wants_json(request):
        return JSONResponse({"ok": True, "added": len(added), "skipped": skipped, "msg": msg, **(await _payload(db, brand.id))})
    return back(request, f"/admin/models?brand_id={brand.id}", msg, "ok" if added else "warn")


@router.post("/models/{mid}/delete")
async def model_delete(mid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*PRODUCT_EDIT_ROLES))):
    m = await model_dict.get_model(db, mid)
    if not m:
        raise HTTPException(404)
    lang = _lang(request, staff)
    brand_id, snap = m.brand_id, model_dict.as_dict(m)
    await model_dict.delete_model(db, m)
    await audit.log(db, staff.id, "model.delete", "brand_model", mid, snap, None)
    await db.commit()
    if _wants_json(request):
        return JSONResponse({"ok": True, "msg": t(lang, "admin.models.deleted"), **(await _payload(db, brand_id))})
    return back(request, f"/admin/models?brand_id={brand_id}", t(lang, "admin.models.deleted"))
