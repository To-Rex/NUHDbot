from decimal import Decimal, InvalidOperation

from fastapi import Depends, File, Form, Request, UploadFile

from app.deps import DB, Lang, redirect, require_registered, require_user
from app.enums import OrderStatus, PaymentKind, PaymentStatus
from app.i18n import t
from app.models import User
from app.services import notifications
from app.services.media import MediaError, save_document
from app.services.orders import (
    OrderError,
    add_payment_claim,
    customer_cancel,
    customer_confirm_offer,
    customer_confirm_tests,
    get_order_for_user,
    user_orders,
)
from app.services.settings_service import get_setting
from app.templating import ORDER_STEPS, render
from app.web.common import hx_trigger, toast
from app.web.router import router

TERMINAL = (OrderStatus.CANCELLED, OrderStatus.RETURNED)


@router.get("/orders")
async def orders_page(request: Request, db: DB, lang: Lang, user: User = Depends(require_user), tab: str = "active"):
    active = tab != "history"
    orders = await user_orders(db, user.id, active=active)
    return render(request, "miniapp/orders.html", {"lang": lang, "orders": orders, "tab": "active" if active else "history", "page_title": t(lang, "orders.title")})


def _progress(order) -> tuple[int, int]:
    if order.status in ORDER_STEPS:
        return ORDER_STEPS.index(order.status) + 1, len(ORDER_STEPS)
    return 0, len(ORDER_STEPS)


async def _detail_ctx(request, db, lang, order):
    step, total_steps = _progress(order)
    pay_kind = None
    pay_amount = None
    if order.status == OrderStatus.AWAITING_ADVANCE:
        pay_kind, pay_amount = PaymentKind.ADVANCE, order.advance_amount
    elif order.status == OrderStatus.AWAITING_BALANCE:
        pay_kind, pay_amount = PaymentKind.BALANCE, order.balance_amount
    # only a pending claim of the *current* stage blocks the "I have paid" button
    pending = next((p for p in order.payments if p.status == PaymentStatus.PENDING and (pay_kind is None or p.kind == pay_kind)), None)
    return {
        "lang": lang, "order": order, "pending_payment": pending, "step": step, "total_steps": total_steps, "pay_kind": pay_kind, "pay_amount": pay_amount,
        "methods": await get_setting(db, "payment_methods", []), "page_title": t(lang, "orders.detail_title", number=order.number), "back_url": "/app/orders",
        "can_cancel": order.status in (OrderStatus.NEW, OrderStatus.AWAITING_ADMIN, OrderStatus.AWAITING_ADVANCE),
        "hint": t(lang, f"orders.status_hint.{order.status.value}") if f"orders.status_hint.{order.status.value}" != t(lang, f"orders.status_hint.{order.status.value}") else None,
    }


@router.get("/orders/{order_id}")
async def order_detail(order_id: int, request: Request, db: DB, lang: Lang, user: User = Depends(require_user)):
    order = await get_order_for_user(db, order_id, user.id)
    if order is None:
        return render(request, "miniapp/not_found.html", {"lang": lang, "message_key": "orders.not_found", "back_url": "/app/orders"}, status_code=404)
    return render(request, "miniapp/order_detail.html", await _detail_ctx(request, db, lang, order))


@router.post("/orders/{order_id}/accept")
async def order_accept(order_id: int, request: Request, db: DB, lang: Lang, user: User = Depends(require_registered)):
    order = await get_order_for_user(db, order_id, user.id)
    if order is None:
        return redirect(request, "/app/orders")
    try:
        await customer_confirm_offer(db, order, user)
        await db.commit()
    except OrderError:
        await db.rollback()
        return toast(redirect(request, f"/app/orders/{order_id}"), t(lang, "misc.error_generic"), "bad", "error")
    return hx_trigger(redirect(request, f"/app/orders/{order_id}"), toast={"msg": t(lang, "orders.accepted"), "type": "ok"}, haptic="success")


@router.post("/orders/{order_id}/cancel")
async def order_cancel(order_id: int, request: Request, db: DB, lang: Lang, user: User = Depends(require_user)):
    order = await get_order_for_user(db, order_id, user.id)
    if order is None:
        return redirect(request, "/app/orders")
    try:
        await customer_cancel(db, order, user)
        await db.commit()
    except OrderError:
        await db.rollback()
        return toast(redirect(request, f"/app/orders/{order_id}"), t(lang, "misc.error_generic"), "bad", "error")
    return hx_trigger(redirect(request, f"/app/orders/{order_id}"), toast={"msg": t(lang, "orders.cancelled"), "type": ""}, haptic="medium")


@router.post("/orders/{order_id}/confirm-tests")
async def order_confirm_tests(order_id: int, request: Request, db: DB, lang: Lang, user: User = Depends(require_registered)):
    order = await get_order_for_user(db, order_id, user.id)
    if order is None:
        return redirect(request, "/app/orders")
    try:
        await customer_confirm_tests(db, order, user)
        await db.commit()
    except OrderError:
        await db.rollback()
        return toast(redirect(request, f"/app/orders/{order_id}"), t(lang, "misc.error_generic"), "bad", "error")
    return hx_trigger(redirect(request, f"/app/orders/{order_id}"), toast={"msg": t(lang, "orders.tests_confirmed"), "type": "ok"}, haptic="success")


@router.post("/orders/{order_id}/pay")
async def order_pay(
    order_id: int, request: Request, db: DB, lang: Lang, user: User = Depends(require_registered),
    kind: str = Form(...), amount: str = Form(...), method: str = Form(""), note: str = Form(""), proof: UploadFile | None = File(None),
):
    order = await get_order_for_user(db, order_id, user.id)
    if order is None:
        return redirect(request, "/app/orders")
    try:
        pay_kind = PaymentKind(kind)
        amt = Decimal(amount.replace(",", ".")).quantize(Decimal("0.01"))
        if amt <= 0:
            raise InvalidOperation
    except (ValueError, InvalidOperation):
        return toast(redirect(request, f"/app/orders/{order_id}"), t(lang, "misc.error_generic"), "bad", "error")
    proof_name = None
    if proof and proof.filename:
        try:
            proof_name = await save_document(proof, prefix="pay")
        except MediaError:
            return toast(redirect(request, f"/app/orders/{order_id}"), t(lang, "support.errors.file"), "bad", "error")
    await add_payment_claim(db, order, user, pay_kind, amt, method or None, proof_name, note or None)
    await db.commit()
    try:
        await notifications.notify_staff(db, t("uz", "notify.new_payment_staff", number=order.number, kind=t("uz", f"payment.{pay_kind.value}"), amount=f"{amt} {order.currency}"), kind="payment_claim")
        await db.commit()
    except Exception:  # noqa: BLE001
        pass
    return hx_trigger(redirect(request, f"/app/orders/{order_id}"), toast={"msg": t(lang, "orders.pay_sent"), "type": "ok"}, haptic="success")
