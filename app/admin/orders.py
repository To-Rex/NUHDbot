from decimal import Decimal

from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, or_, select, update
from starlette.datastructures import UploadFile

from app.admin.common import (
    DB,
    ORDER_EDIT_ROLES,
    ORDER_ROLES,
    PAYMENT_ROLES,
    SHIP_ROLES,
    TEST_ROLES,
    back,
    can,
    f_dec,
    f_int,
    f_opt,
    nav_badges,
    paginate,
    qpage,
    render,
    staff_dep,
)
from app.admin.router import router
from app.enums import ACTIVE_ORDER_STATUSES, OrderStatus, PaymentKind, PaymentStatus
from app.i18n import t
from app.models import AuditLog, Order, OrderItem, Payment, Product, User
from app.services import audit, media, notifications
from app.services import orders as osvc

EDITABLE_ITEMS = (OrderStatus.NEW, OrderStatus.AWAITING_ADMIN, OrderStatus.AWAITING_ADVANCE)


@router.get("/orders")
async def orders_list(request: Request, db: DB, staff: User = Depends(staff_dep(*ORDER_ROLES))):
    q = request.query_params
    stmt = select(Order)
    status = q.get("status")
    if status == "active":
        stmt = stmt.where(Order.status.in_(ACTIVE_ORDER_STATUSES))
    elif status == "closed":
        stmt = stmt.where(Order.status.not_in(ACTIVE_ORDER_STATUSES))
    elif status in [s.value for s in OrderStatus]:
        stmt = stmt.where(Order.status == OrderStatus(status))
    if q.get("payments") == "pending":
        stmt = stmt.where(Order.id.in_(select(Payment.order_id).where(Payment.status == PaymentStatus.PENDING)))
    if q.get("country"):
        stmt = stmt.where(Order.country == q["country"].upper()[:2])
    from datetime import UTC, datetime, timedelta

    for key, op in (("from", "ge"), ("to", "lt")):
        v = (q.get(key) or "").strip()
        if v:
            try:
                d = datetime.fromisoformat(v).replace(tzinfo=UTC)
            except ValueError:
                continue
            stmt = stmt.where(Order.created_at >= d) if op == "ge" else stmt.where(Order.created_at < d + timedelta(days=1))
    if q.get("q"):
        like = f"%{q['q'].strip()}%"
        stmt = stmt.join(User, User.id == Order.user_id).where(
            or_(Order.number.ilike(like), Order.receiver_phone.ilike(like), Order.receiver_name.ilike(like), User.phone.ilike(like), User.first_name.ilike(like), User.last_name.ilike(like), Order.cargo_code.ilike(like))
        )
    stmt = stmt.order_by(Order.id.desc())
    items, total, pages = await paginate(db, stmt, qpage(request), 30)
    counts = dict((await db.execute(select(Order.status, func.count()).group_by(Order.status))).all())
    countries = [c for (c,) in (await db.execute(select(Order.country).where(Order.country.is_not(None)).distinct().order_by(Order.country))).all()]
    pending_ids = {oid for (oid,) in (await db.execute(select(Payment.order_id).where(Payment.status == PaymentStatus.PENDING).distinct())).all()}
    tabs = [("", sum(counts.values())), ("active", sum(v for k, v in counts.items() if k in ACTIVE_ORDER_STATUSES)), ("awaiting_admin", counts.get(OrderStatus.AWAITING_ADMIN, 0)), ("awaiting_advance", counts.get(OrderStatus.AWAITING_ADVANCE, 0)), ("testing", counts.get(OrderStatus.TESTING, 0)), ("awaiting_balance", counts.get(OrderStatus.AWAITING_BALANCE, 0)), ("paid", counts.get(OrderStatus.PAID, 0)), ("packing", counts.get(OrderStatus.PACKING, 0)), ("shipped", counts.get(OrderStatus.SHIPPED, 0)), ("closed", sum(v for k, v in counts.items() if k not in ACTIVE_ORDER_STATUSES))]
    return render(request, staff, "admin/orders/list.html", {"page_title": t(staff.lang, "admin.ord.title"), "items": items, "total": total, "pages": pages, "page": qpage(request), "tabs": tabs, "status": status or "", "statuses": list(OrderStatus), "badges": await nav_badges(db), "countries": countries, "pending_ids": pending_ids})


async def _load(db, oid: int) -> Order:
    o = await db.get(Order, oid)
    if not o:
        raise HTTPException(404)
    return o


@router.get("/orders/{oid}")
async def order_detail(oid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ORDER_ROLES))):
    o = await _load(db, oid)
    prev_count = (await db.execute(select(func.count()).select_from(Order).where(Order.user_id == o.user_id, Order.id != o.id))).scalar_one()
    logs = (await db.execute(select(AuditLog).where(AuditLog.entity.in_(["order", "payment"]), AuditLog.entity_id.in_([str(o.id)] + [str(p.id) for p in o.payments])).order_by(AuditLog.id.desc()).limit(30))).scalars().all()
    actors = {}
    ids = {lg.actor_id for lg in logs if lg.actor_id}
    if ids:
        actors = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()}
    transitions = osvc.allowed_transitions(o, is_admin=staff.is_admin)
    return render(request, staff, "admin/orders/detail.html", {
        "page_title": o.number, "o": o, "prev_count": prev_count, "logs": logs, "actors": actors, "transitions": transitions,
        "items_editable": o.status in EDITABLE_ITEMS and can(staff, ORDER_EDIT_ROLES), "kinds": list(PaymentKind),
        "can_pay": can(staff, PAYMENT_ROLES), "can_ship": can(staff, SHIP_ROLES), "can_test": can(staff, TEST_ROLES), "can_edit": can(staff, ORDER_EDIT_ROLES),
    })


@router.post("/orders/{oid}/items")
async def order_items(oid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ORDER_EDIT_ROLES))):
    o = await _load(db, oid)
    if o.status not in EDITABLE_ITEMS:
        return back(request, f"/admin/orders/{oid}", t(staff.lang, "admin.ord.no_items_edit"), "bad")
    form = await request.form()
    before = {str(i.id): [i.qty, str(i.unit_price)] for i in o.items}
    subtotal = Decimal(0)
    for it in o.items:
        qty = max(1, f_int(form, f"qty_{it.id}", it.qty) or it.qty)
        price = f_dec(form, f"price_{it.id}")
        if qty != it.qty and it.product_id:
            # keep the stock reservation in sync with the edited quantity (32.06)
            await db.execute(update(Product).where(Product.id == it.product_id).values(reserved=func.greatest(Product.reserved + (qty - it.qty), 0)))
        it.qty = qty
        if price is not None:
            it.unit_price = price
        subtotal += Decimal(it.unit_price) * it.qty
    o.subtotal = subtotal
    o.total = subtotal
    await audit.log(db, staff.id, "order.items", "order", o.id, before, {str(i.id): [i.qty, str(i.unit_price)] for i in o.items})
    await db.commit()
    return back(request, f"/admin/orders/{oid}", t(staff.lang, "admin.ord.items_saved"))


@router.post("/orders/{oid}/offer")
async def order_offer(oid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ORDER_EDIT_ROLES))):
    o = await _load(db, oid)
    form = await request.form()
    before = {"total": str(o.total), "delivery_terms": o.delivery_terms, "warranty_terms": o.warranty_terms}
    total = f_dec(form, "total")
    if total is not None:
        o.total = total
    o.delivery_terms = f_opt(form, "delivery_terms")
    o.warranty_terms = f_opt(form, "warranty_terms")
    o.admin_note = f_opt(form, "admin_note")
    o.advance_percent = max(0, min(100, f_int(form, "advance_percent", o.advance_percent) or o.advance_percent))
    await audit.log(db, staff.id, "order.offer", "order", o.id, before, {"total": str(o.total), "delivery_terms": o.delivery_terms, "warranty_terms": o.warranty_terms, "advance_percent": o.advance_percent})
    msg = t(staff.lang, "admin.flash.saved")
    if form.get("send") == "1":
        if o.status == OrderStatus.NEW:
            await osvc.transition(db, o, OrderStatus.AWAITING_ADMIN, by=staff, note="offer", force=True)
        await notifications.notify_order_status(db, o, o.user)
        await audit.log(db, staff.id, "order.offer.sent", "order", o.id)
        msg = t(staff.lang, "admin.ord.offer_sent")
    await db.commit()
    return back(request, f"/admin/orders/{oid}", msg)


@router.post("/orders/{oid}/status")
async def order_status(oid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ORDER_ROLES))):
    o = await _load(db, oid)
    form = await request.form()
    try:
        to = OrderStatus(form.get("to_status") or "")
    except ValueError:
        raise HTTPException(400) from None
    note = f_opt(form, "note")
    # role gates for sensitive transitions
    if to in (OrderStatus.SHIPPED, OrderStatus.PACKING, OrderStatus.DELIVERED) and not can(staff, SHIP_ROLES):
        raise HTTPException(403)
    if to in (OrderStatus.TESTING, OrderStatus.TEST_READY) and not can(staff, TEST_ROLES | ORDER_EDIT_ROLES):
        raise HTTPException(403)
    if to in (OrderStatus.ADVANCE_CONFIRMED, OrderStatus.PAID) and not can(staff, PAYMENT_ROLES):
        raise HTTPException(403)
    if to == OrderStatus.SHIPPED and o.paid_amount < Decimal(o.total or 0):
        return back(request, f"/admin/orders/{oid}", t(staff.lang, "admin.ord.need_full_payment"), "bad")
    try:
        await osvc.transition(db, o, to, by=staff, note=note)
    except osvc.OrderError as e:
        return back(request, f"/admin/orders/{oid}", t(staff.lang, "admin.flash.error", e=e.code), "bad")
    await notifications.notify_order_status(db, o, o.user)
    await db.commit()
    return back(request, f"/admin/orders/{oid}", t(staff.lang, "admin.ord.status_changed"))


@router.post("/orders/{oid}/payments")
async def order_payment_record(oid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*PAYMENT_ROLES))):
    o = await _load(db, oid)
    form = await request.form()
    kind = PaymentKind(form.get("kind") or "advance")
    amount = f_dec(form, "amount")
    if amount is None or amount <= 0:
        return back(request, f"/admin/orders/{oid}#payments", t(staff.lang, "admin.required"), "bad")
    proof = None
    f = form.get("proof")
    if isinstance(f, UploadFile) and f.filename:
        try:
            proof = await media.save_document(f, prefix=f"pay{o.id}")
        except media.MediaError:
            proof = None
    pay = await osvc.add_payment_claim(db, o, o.user, kind, amount, f_opt(form, "method", 60), proof, f_opt(form, "note"))
    await audit.log(db, staff.id, "payment.record", "payment", pay.id, None, {"order": o.number, "kind": kind, "amount": str(amount)})
    await osvc.confirm_payment(db, pay, staff, True, "recorded by staff")
    await notifications.notify_order_status(db, o, o.user)
    await db.commit()
    return back(request, f"/admin/orders/{oid}#payments", t(staff.lang, "admin.ord.payment_confirmed"))


@router.post("/orders/{oid}/payments/{pid}/{action}")
async def order_payment_action(oid: int, pid: int, action: str, request: Request, db: DB, staff: User = Depends(staff_dep(*PAYMENT_ROLES))):
    o = await _load(db, oid)
    pay = await db.get(Payment, pid)
    if not pay or pay.order_id != o.id or action not in ("confirm", "reject"):
        raise HTTPException(404)
    if pay.status != PaymentStatus.PENDING:
        return back(request, f"/admin/orders/{oid}#payments", t(staff.lang, "admin.flash.error", e="already processed"), "warn")
    form = await request.form()
    await osvc.confirm_payment(db, pay, staff, action == "confirm", f_opt(form, "note"))
    await notifications.notify_order_status(db, o, o.user)
    await db.commit()
    nxt = form.get("next") or ""
    target = nxt if nxt.startswith("/admin") else f"/admin/orders/{oid}#payments"
    return back(request, target, t(staff.lang, "admin.ord.payment_confirmed" if action == "confirm" else "admin.ord.payment_rejected"))


@router.post("/orders/{oid}/items/{iid}/test")
async def order_item_test(oid: int, iid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*TEST_ROLES))):
    o = await _load(db, oid)
    it = await db.get(OrderItem, iid)
    if not it or it.order_id != o.id:
        raise HTTPException(404)
    form = await request.form()
    serials = [s.strip() for s in (form.get("serials") or "").splitlines() if s.strip()]
    # 11.06 — a serial must not be assigned to two active orders
    if serials:
        others = (await db.execute(select(OrderItem).join(Order).where(Order.status.in_(ACTIVE_ORDER_STATUSES), OrderItem.id != it.id))).scalars().all()
        taken = {s for other in others for s in (other.serials or [])}
        dup = [s for s in serials if s in taken]
        if dup:
            return back(request, f"/admin/orders/{oid}#tests", t(staff.lang, "admin.flash.error", e=f"serial already used: {', '.join(dup[:5])}"), "bad")
    before = {"serials": it.serials, "test_note": it.test_note}
    it.serials = serials
    it.test_note = f_opt(form, "test_note")
    await audit.log(db, staff.id, "order.item.test", "order", o.id, before, {"item": it.id, "serials": serials, "test_note": it.test_note})
    await db.commit()
    msg = t(staff.lang, "admin.flash.saved")
    kind = "ok"
    if serials and len(serials) != it.qty:
        msg, kind = t(staff.lang, "admin.ord.serials_count_mismatch", n=len(serials), qty=it.qty), "warn"
    return back(request, f"/admin/orders/{oid}#tests", msg, kind)


@router.post("/orders/{oid}/shipping")
async def order_shipping(oid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*SHIP_ROLES))):
    o = await _load(db, oid)
    form = await request.form()
    before = {"tracking_number": o.tracking_number, "cargo_code": o.cargo_code, "cargo_company": o.cargo_company}
    o.tracking_number = f_opt(form, "tracking_number", 120)
    o.cargo_code = f_opt(form, "cargo_code", 64)  # stored verbatim (15.06)
    o.cargo_company = f_opt(form, "cargo_company", 120)
    await audit.log(db, staff.id, "order.shipping", "order", o.id, before, {"tracking_number": o.tracking_number, "cargo_code": o.cargo_code, "cargo_company": o.cargo_company, "cargo_confirmed": form.get("cargo_confirmed") == "on"})
    msg = t(staff.lang, "admin.flash.saved")
    if form.get("ship") == "1":
        if o.paid_amount < Decimal(o.total or 0):
            await db.commit()
            return back(request, f"/admin/orders/{oid}", t(staff.lang, "admin.ord.need_full_payment"), "bad")
        if form.get("cargo_confirmed") != "on":
            await db.commit()
            return back(request, f"/admin/orders/{oid}", t(staff.lang, "admin.ord.cargo_confirm"), "warn")
        try:
            if o.status == OrderStatus.PAID:
                await osvc.transition(db, o, OrderStatus.PACKING, by=staff, note="packing")
            await osvc.transition(db, o, OrderStatus.SHIPPED, by=staff, note=f"tracking: {o.tracking_number or '-'}")
            await notifications.notify_order_status(db, o, o.user)
            msg = t(staff.lang, "admin.ord.status_changed")
        except osvc.OrderError as e:
            await db.commit()
            return back(request, f"/admin/orders/{oid}", t(staff.lang, "admin.flash.error", e=e.code), "bad")
    await db.commit()
    return back(request, f"/admin/orders/{oid}", msg)


@router.get("/payments")
async def payments_queue(request: Request, db: DB, staff: User = Depends(staff_dep(*PAYMENT_ROLES))):
    """Finance queue: pending payment claims first, then recent decisions."""
    from sqlalchemy.orm import selectinload

    status = request.query_params.get("status") or "pending"
    stmt = select(Payment).options(selectinload(Payment.order))
    if status in ("pending", "confirmed", "rejected"):
        stmt = stmt.where(Payment.status == PaymentStatus(status))
    stmt = stmt.order_by(Payment.id.desc())
    items, total, pages = await paginate(db, stmt, qpage(request), 30)
    counts = dict((await db.execute(select(Payment.status, func.count()).group_by(Payment.status))).all())
    return render(request, staff, "admin/payments/list.html", {
        "page_title": t(staff.lang, "admin.nav.payments"), "items": items, "total": total, "pages": pages, "page": qpage(request),
        "status": status, "counts": {k.value if hasattr(k, "value") else k: v for k, v in counts.items()},
    })
