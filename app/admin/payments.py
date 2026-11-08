"""Payment methods: how customers pay the shop — each with a QR code (uploaded, or generated from a link / address), the
account to copy and instructions per language; shown for auction deposits and/or order payments."""
from fastapi import Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response

from app.admin.common import ADMIN, DB, back, f_bool, f_i18n, f_opt, f_str, render, staff_dep, toast
from app.admin.router import router
from app.enums import PaymentMethodKind, Role
from app.i18n import t
from app.models import PaymentMethod, User
from app.services import audit, media
from app.services import payment_methods as svc

PAY_METHOD_ROLES = ADMIN | {Role.FINANCE}
FIELDS = ("kind", "name", "account", "instructions", "qr_filename", "qr_text", "currency", "for_deposits", "for_orders", "is_active", "sort")


def snapshot(m: PaymentMethod) -> dict:
    return {k: (getattr(m, k).value if hasattr(getattr(m, k), "value") else getattr(m, k)) for k in FIELDS}


async def _grid_or_back(request: Request, db, staff: User, msg: str | None):
    if request.headers.get("HX-Request") == "true":
        rows = await svc.list_methods(db, active_only=False)
        return render(request, staff, "admin/payments/_grid.html", {"rows": rows}, headers=toast(msg) if msg else None)
    return back(request, "/admin/payments", msg)


@router.get("/payments")
async def payments_list(request: Request, db: DB, staff: User = Depends(staff_dep(*PAY_METHOD_ROLES))):
    rows = await svc.list_methods(db, active_only=False)
    return render(request, staff, "admin/payments/list.html", {"page_title": t(staff.lang, "admin.pm.title"), "rows": rows})


def _form_ctx(m: PaymentMethod, is_new: bool, errors: list[str] | None = None) -> dict:
    return {"m": m, "is_new": is_new, "errors": errors or [], "kinds": list(PaymentMethodKind), "presets": {k.value: v for k, v in svc.PRESETS.items()}, "icon_of": svc.icon}


@router.get("/payments/new")
async def payment_new(request: Request, db: DB, staff: User = Depends(staff_dep(*PAY_METHOD_ROLES))):
    m = PaymentMethod(kind=PaymentMethodKind.ALIPAY, name="Alipay", instructions={}, is_active=True, for_deposits=True, for_orders=True, sort=await svc.next_sort(db))
    return render(request, staff, "admin/payments/form.html", {"page_title": t(staff.lang, "admin.pm.add"), **_form_ctx(m, True)})


@router.get("/payments/qr-preview.svg")
async def payment_qr_preview(text: str = "", staff: User = Depends(staff_dep(*PAY_METHOD_ROLES))):
    """The QR a link / address would give, drawn while the admin types it."""
    text = text.strip()[:1000]
    if not text:
        return Response(status_code=204)
    return Response(svc.qr_svg(text, scale=6), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


async def _apply(m: PaymentMethod, form, qr: UploadFile | None) -> list[str]:
    errors: list[str] = []
    m.kind = svc.kind_of(form.get("kind"))
    m.name = f_str(form, "name", maxlen=80).strip()
    if not m.name:
        errors.append("name")
    m.account = f_opt(form, "account", maxlen=200)
    m.instructions = f_i18n(form, "instructions")
    cur = (f_opt(form, "currency") or "").upper()[:3]
    m.currency = cur if cur.isalpha() else None
    m.for_deposits = f_bool(form, "for_deposits")
    m.for_orders = f_bool(form, "for_orders")
    m.is_active = f_bool(form, "is_active")
    qr_text = (f_opt(form, "qr_text", maxlen=1000) or "").strip() or None
    if form.get("remove_qr") == "1":
        await svc.clear_qr_picture(m)
    if qr is not None and qr.filename:
        try:
            await svc.set_qr_picture(m, qr)
        except media.MediaError:
            errors.append("qr")
    elif qr_text and not m.qr_filename:  # a text QR only while no picture is kept
        m.qr_text = qr_text
    elif not qr_text and not m.qr_filename:
        m.qr_text = None
    return errors


@router.post("/payments/new")
async def payment_create(request: Request, db: DB, staff: User = Depends(staff_dep(*PAY_METHOD_ROLES)), qr: UploadFile | None = File(None)):
    form = await request.form()
    m = PaymentMethod(instructions={}, sort=await svc.next_sort(db))
    errors = await _apply(m, form, qr)
    if errors:
        return render(request, staff, "admin/payments/form.html", {"page_title": t(staff.lang, "admin.pm.add"), **_form_ctx(m, True, errors)}, status_code=400)
    db.add(m)
    await db.flush()
    await audit.log(db, staff.id, "payment_method.create", "payment_method", m.id, None, snapshot(m))
    await db.commit()
    return back(request, "/admin/payments", t(staff.lang, "admin.pm.saved"))


async def _get(db, mid: int) -> PaymentMethod:
    m = await db.get(PaymentMethod, mid)
    if m is None:
        raise HTTPException(404)
    return m


@router.get("/payments/{mid}")
async def payment_edit(mid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*PAY_METHOD_ROLES))):
    m = await _get(db, mid)
    return render(request, staff, "admin/payments/form.html", {"page_title": m.name, **_form_ctx(m, False)})


@router.post("/payments/{mid}")
async def payment_save(mid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*PAY_METHOD_ROLES)), qr: UploadFile | None = File(None)):
    m = await _get(db, mid)
    form = await request.form()
    before = snapshot(m)
    errors = await _apply(m, form, qr)
    if errors:
        return render(request, staff, "admin/payments/form.html", {"page_title": m.name, **_form_ctx(m, False, errors)}, status_code=400)
    await audit.log(db, staff.id, "payment_method.update", "payment_method", m.id, before, snapshot(m))
    await db.commit()
    return back(request, "/admin/payments", t(staff.lang, "admin.pm.saved"))


@router.post("/payments/{mid}/toggle")
async def payment_toggle(mid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*PAY_METHOD_ROLES))):
    m = await _get(db, mid)
    m.is_active = not m.is_active
    await audit.log(db, staff.id, "payment_method.toggle", "payment_method", m.id, {"is_active": not m.is_active}, {"is_active": m.is_active})
    await db.commit()
    return await _grid_or_back(request, db, staff, t(staff.lang, "admin.pm.shown" if m.is_active else "admin.pm.hidden"))


@router.post("/payments/{mid}/move")
async def payment_move(mid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*PAY_METHOD_ROLES))):
    rows = await svc.list_methods(db, active_only=False)
    i = next((n for n, m in enumerate(rows) if m.id == mid), None)
    j = None if i is None else i + (-1 if (await request.form()).get("dir") == "up" else 1)
    if i is not None and 0 <= j < len(rows):
        rows[i], rows[j] = rows[j], rows[i]
        for n, m in enumerate(rows):
            m.sort = (n + 1) * 10
        await db.commit()
    return await _grid_or_back(request, db, staff, None)


@router.post("/payments/{mid}/delete")
async def payment_delete(mid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*PAY_METHOD_ROLES))):
    m = await _get(db, mid)
    await audit.log(db, staff.id, "payment_method.delete", "payment_method", m.id, snapshot(m), None)
    await svc.delete(db, m)
    await db.commit()
    return await _grid_or_back(request, db, staff, t(staff.lang, "admin.pm.deleted"))
