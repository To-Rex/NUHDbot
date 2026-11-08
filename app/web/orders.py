from decimal import Decimal

from fastapi import Depends, Request

from app.deps import DB, Lang, redirect, require_registered, require_user
from app.enums import ORDER_STAGES, PAYMENT_STAGE_STATUSES, order_stage
from app.i18n import t
from app.models import User
from app.services import payment_methods as pm_svc
from app.services.orders import OrderError, customer_confirm_offer, get_order_for_user, user_orders
from app.templating import render
from app.web.common import hx_trigger, toast
from app.web.router import router


@router.get("/orders")
async def orders_page(request: Request, db: DB, lang: Lang, user: User = Depends(require_user), tab: str = "active"):
    active = tab != "history"
    orders = await user_orders(db, user.id, active=active)
    return render(request, "miniapp/orders.html", {"lang": lang, "orders": orders, "tab": "active" if active else "history", "page_title": t(lang, "orders.title"), "back_url": "/app/profile"})


def _progress(order) -> tuple[int, int]:
    """Which of the three stages (Order, Payment, Shipping) the order is in; past the last when shipped, 0 when cancelled."""
    return min(order_stage(order.status), len(ORDER_STAGES)), len(ORDER_STAGES)


async def _chat_url(db, order, user: User) -> str:
    """Payments are agreed in chat: write about this order — it goes to the one conversation, the order number on top."""
    return f"/app/support/new?order_id={order.id}"


async def _detail_ctx(request, db, lang, order, user):
    step, total_steps = _progress(order)
    due = max(Decimal(order.total or 0) - order.paid_amount, Decimal(0))
    pay_amount = due if order.status in PAYMENT_STAGE_STATUSES and due > 0 else None  # the payment stage: what is left to pay
    hint_key = f"orders.status_hint.{order.status.value}"
    return {
        "lang": lang, "order": order, "step": step, "total_steps": total_steps, "pay_amount": pay_amount, "due": due,
        "pay_methods": await pm_svc.list_methods(db, purpose="order") if pay_amount else [], "pm_instructions": lambda m: pm_svc.instructions(m, lang), "pm_icon": pm_svc.icon,
        "chat_url": await _chat_url(db, order, user),
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
