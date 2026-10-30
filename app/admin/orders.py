from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, or_, select, update

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
from app.models import Order, Payment, Product, SupportThread, User
from app.services import audit, notifications
from app.services import orders as osvc

EDITABLE_ITEMS = (OrderStatus.NEW, OrderStatus.AWAITING_ADMIN, OrderStatus.AWAITING_ADVANCE)
# List tabs mirror the 7-stage journey shown on the order page.
STAGE_GROUPS: dict[str, tuple[OrderStatus, ...]] = {
    "g_order": (OrderStatus.NEW, OrderStatus.AWAITING_ADMIN),
    "g_advance": (OrderStatus.AWAITING_ADVANCE, OrderStatus.ADVANCE_CONFIRMED),
    "g_test": (OrderStatus.TESTING, OrderStatus.TEST_READY, OrderStatus.AWAITING_CUSTOMER),
    "g_balance": (OrderStatus.AWAITING_BALANCE, OrderStatus.PAID),
    "g_ship": (OrderStatus.PACKING, OrderStatus.SHIPPED, OrderStatus.DELIVERED),
    "disputed": (OrderStatus.DISPUTED,),
}
# Orders where money is expected; the customer sends the receipt in the support chat.
AWAITING_PAYMENT = (OrderStatus.AWAITING_ADVANCE, OrderStatus.AWAITING_BALANCE)


@router.get("/orders")
async def orders_list(request: Request, db: DB, staff: User = Depends(staff_dep(*ORDER_ROLES))):
    q = request.query_params
    stmt = select(Order)
    status = q.get("status")
    if status == "active":
        stmt = stmt.where(Order.status.in_(ACTIVE_ORDER_STATUSES))
    elif status == "closed":
        stmt = stmt.where(Order.status.not_in(ACTIVE_ORDER_STATUSES))
    elif status == "awaiting_payment":
        stmt = stmt.where(Order.status.in_(AWAITING_PAYMENT))
    elif status in STAGE_GROUPS:
        stmt = stmt.where(Order.status.in_(STAGE_GROUPS[status]))
    elif status in [s.value for s in OrderStatus]:
        stmt = stmt.where(Order.status == OrderStatus(status))
    if q.get("country"):
        stmt = stmt.where(Order.country == q["country"].upper()[:2])
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
    tabs = [("", sum(counts.values())), ("active", sum(v for k, v in counts.items() if k in ACTIVE_ORDER_STATUSES))]
    tabs += [(g, sum(counts.get(st, 0) for st in members)) for g, members in STAGE_GROUPS.items()]
    tabs.append(("closed", sum(v for k, v in counts.items() if k not in ACTIVE_ORDER_STATUSES)))
    return render(request, staff, "admin/orders/list.html", {"page_title": t(staff.lang, "admin.ord.title"), "items": items, "total": total, "pages": pages, "page": qpage(request), "tabs": tabs, "status": status or "", "statuses": list(OrderStatus), "badges": await nav_badges(db), "countries": countries})


async def _load(db, oid: int) -> Order:
    o = await db.get(Order, oid)
    if not o:
        raise HTTPException(404)
    return o


@router.get("/orders/{oid}")
async def order_detail(oid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ORDER_ROLES))):
    o = await _load(db, oid)
    prev_count = (await db.execute(select(func.count()).select_from(Order).where(Order.user_id == o.user_id, Order.id != o.id))).scalar_one()
    # payments are agreed in chat, so the order page links straight to the conversation about this order
    thread = (await db.execute(select(SupportThread).where(SupportThread.order_id == o.id).order_by(SupportThread.last_message_at.desc().nulls_last(), SupportThread.id.desc()).limit(1))).scalars().first()
    chat_url = f"/admin/support/{thread.id}" if thread else f"/admin/support?user={o.user_id}"
    transitions = osvc.allowed_transitions(o, is_admin=staff.is_admin)
    due = (o.advance_amount if o.status in (OrderStatus.NEW, OrderStatus.AWAITING_ADMIN, OrderStatus.AWAITING_ADVANCE) else Decimal(o.total or 0)) - o.paid_amount
    return render(request, staff, "admin/orders/detail.html", {
        "page_title": o.number, "o": o, "prev_count": prev_count, "transitions": transitions, "chat_url": chat_url, "due": due if due > 0 else None,
        "items_editable": o.status in EDITABLE_ITEMS and can(staff, ORDER_EDIT_ROLES),
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
        # marks the offer as sent: the customer now sees the "accept offer" button
        o.confirmed_at = o.confirmed_at or datetime.now(UTC)
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
    allowed = osvc.allowed_transitions(o, is_admin=staff.is_admin)
    jump = to not in allowed and to != o.status
    if jump and not (staff.is_admin and note):
        return back(request, f"/admin/orders/{oid}", t(staff.lang, "admin.ord.jump_needs_reason"), "bad")
    try:
        await osvc.transition(db, o, to, by=staff, note=note, force=jump)
    except osvc.OrderError as e:
        return back(request, f"/admin/orders/{oid}", t(staff.lang, "admin.flash.error", e=e.code), "bad")
    await notifications.notify_order_status(db, o, o.user)
    await db.commit()
    return back(request, f"/admin/orders/{oid}", t(staff.lang, "admin.ord.status_changed"))


@router.post("/orders/{oid}/payments")
async def order_payment_record(oid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*PAYMENT_ROLES))):
    o = await _load(db, oid)
    form = await request.form()
    # the stage decides what the money is for; staff only type the amount they received
    before_advance = o.status in (OrderStatus.NEW, OrderStatus.AWAITING_ADMIN, OrderStatus.AWAITING_ADVANCE)
    kind = PaymentKind.ADVANCE if before_advance else PaymentKind.BALANCE
    amount = f_dec(form, "amount")
    if amount is None or amount <= 0:
        return back(request, f"/admin/orders/{oid}#payments", t(staff.lang, "admin.required"), "bad")
    pay = await osvc.add_payment(db, o, o.user, kind, amount, f_opt(form, "method", 60), None, f_opt(form, "note"))
    await audit.log(db, staff.id, "payment.record", "payment", pay.id, None, {"order": o.number, "kind": kind, "amount": str(amount)})
    await osvc.confirm_payment(db, pay, staff, True, "recorded by staff")
    await notifications.notify_order_status(db, o, o.user)
    await db.commit()
    if not getattr(pay, "stage_complete", True):
        expected = o.advance_amount if o.status == OrderStatus.AWAITING_ADVANCE else Decimal(o.total or 0)
        return back(request, f"/admin/orders/{oid}#payments", t(staff.lang, "admin.ord.payment_partial", paid=f"{o.paid_amount} {o.currency}", expected=f"{expected} {o.currency}"), "warn")
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
    target = f"/admin/orders/{oid}#payments"
    if action == "confirm" and not getattr(pay, "stage_complete", True):
        expected = o.advance_amount if o.status == OrderStatus.AWAITING_ADVANCE else Decimal(o.total or 0)
        return back(request, target, t(staff.lang, "admin.ord.payment_partial", paid=f"{o.paid_amount} {o.currency}", expected=f"{expected} {o.currency}"), "warn")
    return back(request, target, t(staff.lang, "admin.ord.payment_confirmed" if action == "confirm" else "admin.ord.payment_rejected"))
