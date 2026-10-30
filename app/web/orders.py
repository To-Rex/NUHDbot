from fastapi import Depends, Request
from sqlalchemy import select

from app.deps import DB, Lang, redirect, require_registered, require_user
from app.enums import OrderStatus, PaymentKind, ThreadStatus
from app.i18n import t
from app.models import SupportThread, User
from app.services.orders import OrderError, customer_confirm_offer, get_order_for_user, user_orders
from app.services.settings_service import get_setting
from app.templating import ORDER_STEPS, render
from app.web.common import hx_trigger, toast
from app.web.router import router


@router.get("/orders")
async def orders_page(request: Request, db: DB, lang: Lang, user: User = Depends(require_user), tab: str = "active"):
    active = tab != "history"
    orders = await user_orders(db, user.id, active=active)
    return render(request, "miniapp/orders.html", {"lang": lang, "orders": orders, "tab": "active" if active else "history", "page_title": t(lang, "orders.title")})


def _progress(order) -> tuple[int, int]:
    if order.status in ORDER_STEPS:
        return ORDER_STEPS.index(order.status) + 1, len(ORDER_STEPS)
    return 0, len(ORDER_STEPS)


async def _chat_url(db, order, user: User) -> str:
    """Payments are agreed in chat: open the conversation about this order, or start one."""
    th = (
        await db.execute(
            select(SupportThread)
            .where(SupportThread.user_id == user.id, SupportThread.order_id == order.id, SupportThread.status == ThreadStatus.OPEN)
            .order_by(SupportThread.id.desc())
            .limit(1)
        )
    ).scalars().first()
    return f"/app/support/{th.id}" if th else f"/app/support/new?order_id={order.id}"


async def _detail_ctx(request, db, lang, order, user):
    step, total_steps = _progress(order)
    pay_kind = pay_amount = None
    if order.status == OrderStatus.AWAITING_ADVANCE:
        pay_kind, pay_amount = PaymentKind.ADVANCE, order.advance_amount
    elif order.status == OrderStatus.AWAITING_BALANCE:
        pay_kind, pay_amount = PaymentKind.BALANCE, order.balance_amount
    hint_key = f"orders.status_hint.{order.status.value}"
    return {
        "lang": lang, "order": order, "step": step, "total_steps": total_steps, "pay_kind": pay_kind, "pay_amount": pay_amount,
        "methods": await get_setting(db, "payment_methods", []), "chat_url": await _chat_url(db, order, user),
        "page_title": t(lang, "orders.detail_title", number=order.number), "back_url": "/app/orders",
        "hint": t(lang, hint_key) if t(lang, hint_key) != hint_key else None,
    }


@router.get("/orders/{order_id}")
async def order_detail(order_id: int, request: Request, db: DB, lang: Lang, user: User = Depends(require_user)):
    order = await get_order_for_user(db, order_id, user.id)
    if order is None:
        return render(request, "miniapp/not_found.html", {"lang": lang, "message_key": "orders.not_found", "back_url": "/app/orders"}, status_code=404)
    return render(request, "miniapp/order_detail.html", await _detail_ctx(request, db, lang, order, user))


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
