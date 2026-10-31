"""Model dictionary (Каталог → Моделлар): bulk entry per brand, used by the product form autocomplete."""
from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.admin.common import DB, PRODUCT_EDIT_ROLES, back, f_int, render, staff_dep
from app.admin.router import router
from app.enums import COLOR_DIRECTION, ProductColor
from app.i18n import t
from app.models import User
from app.services import audit, model_dict
from app.services import brands as brand_service
from app.services import series as series_service


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
    by_brand: dict[int, list] = {}
    for m in await model_dict.list_models(db, bid):
        by_brand.setdefault(m.brand_id, []).append(m)
    counts = await model_dict.counts(db)
    series = await series_service.list_series(db)
    listed = {(x.brand_id, x.key): x for x in series}

    def by_series(b, models) -> list[dict]:
        """A brand's models under their series, in the Series page order; typed series after, no series last."""
        subs: dict[str, dict] = {}
        for m in models:
            key = series_service.norm_key(m.series)
            if key not in subs:
                x = listed.get((b.id, key))
                subs[key] = {"name": x.name if x else (m.series or "").strip(), "color": x.color if x else None, "models": [],
                             "order": (0, x.sort, x.name.lower()) if x else ((1, 0, key.lower()) if key else (2, 0, ""))}
            subs[key]["models"].append(m)
        return sorted(subs.values(), key=lambda g: g["order"])

    return render(request, staff, "admin/models/list.html", {
        "series": [series_service.as_dict(x) for x in series],
        "colors": list(ProductColor), "color_dir": COLOR_DIRECTION,
        "page_title": t(_lang(request, staff), "admin.models.title"), "brands": brands, "brand_id": bid,
        # brand tabs: only brands that already have models, plus the one being viewed
        "tabs": [(b, counts.get(b.id, 0)) for b in brands if counts.get(b.id) or b.id == bid],
        "groups": [(b, by_series(b, by_brand[b.id]), len(by_brand[b.id])) for b in brands if by_brand.get(b.id)],
        "grand_total": sum(counts.values()),
    })


def _next_url(form, fallback: str) -> str:
    nxt = str(form.get("next") or "")
    return nxt if nxt.startswith("/admin/models") and "#" not in nxt else fallback


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
    added, skipped = await model_dict.bulk_add(db, brand, form.get("lines") or "", series_service.norm_name(form.get("series")) or None)
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
    # stay on the view the user deleted from (all brands or one brand)
    return back(request, _next_url(await request.form(), f"/admin/models?brand_id={brand_id}"), t(lang, "admin.models.deleted"))
