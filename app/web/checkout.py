from fastapi import Depends, Form, Request
from sqlalchemy import select

from app.deps import DB, Lang, redirect, require_registered
from app.i18n import t
from app.models import Country, Order, User
from app.services import notifications
from app.services.orders import OrderError, create_order
from app.services.settings_service import get_setting
from app.templating import render
from app.web.cart import _cart_lines
from app.web.common import current_cart, hx_trigger, save_cart
from app.web.router import router


async def _ctx(request, db, user, lang, form: dict | None = None, errors: dict | None = None):
    cart = current_cart(request)
    lines, total, currency = await _cart_lines(db, cart)
    countries = (await db.execute(select(Country).where(Country.is_active.is_(True)).order_by(Country.sort))).scalars().all()
    form = form or {
        "receiver_name": user.last_receiver_name or user.full_name,
        "receiver_phone": user.last_receiver_phone or user.phone or "",
        "country": user.country or "UZ",
        "city": user.city or "",
        "address": user.last_address or "",
        "cargo_company": user.last_cargo_company or "",
        "cargo_code": user.last_cargo_code or "",
        "note": "",
    }
    return {
        "lang": lang, "lines": lines, "total": total, "currency": currency, "countries": countries, "form": form, "errors": errors or {},
        "payment": await get_setting(db, "payment_text"), "delivery": await get_setting(db, "delivery_text"),
        "advance_percent": await get_setting(db, "advance_percent", 30), "page_title": t(lang, "checkout.title"), "back_url": "/app/cart", "hide_nav": True,
    }


@router.get("/checkout")
async def checkout_page(request: Request, db: DB, lang: Lang, user: User = Depends(require_registered)):
    ctx = await _ctx(request, db, user, lang)
    if not ctx["lines"]:
        return redirect(request, "/app/cart")
    return render(request, "miniapp/checkout.html", ctx)


@router.post("/checkout")
async def checkout_submit(
    request: Request, db: DB, lang: Lang, user: User = Depends(require_registered),
    receiver_name: str = Form(""), receiver_phone: str = Form(""), country: str = Form(""), city: str = Form(""), address: str = Form(""),
    cargo_company: str = Form(""), cargo_code: str = Form(""), note: str = Form(""),
):
    form = {"receiver_name": receiver_name, "receiver_phone": receiver_phone, "country": country, "city": city, "address": address, "cargo_company": cargo_company, "cargo_code": cargo_code, "note": note}
    errors = {}
    if not receiver_name.strip():
        errors["receiver_name"] = t(lang, "checkout.errors.receiver_name")
    if not receiver_phone.strip():
        errors["receiver_phone"] = t(lang, "checkout.errors.receiver_phone")
    if not address.strip():
        errors["address"] = t(lang, "checkout.errors.address")
    cart = current_cart(request)
    if errors:
        ctx = await _ctx(request, db, user, lang, form, errors)
        return hx_trigger(render(request, "miniapp/checkout.html", ctx, status_code=422), haptic="error")
    try:
        order = await create_order(
            db, user, list(cart.items()), receiver_name=receiver_name, receiver_phone=receiver_phone, country=country[:2].upper() or None,
            city=city.strip()[:100] or None, address=address, cargo_company=cargo_company, cargo_code=cargo_code, customer_note=note,
        )
        await db.commit()
    except OrderError as e:
        await db.rollback()
        await db.refresh(user)
        ctx = await _ctx(request, db, user, lang, form, {"general": t(lang, f"checkout.errors.{e.code}", **e.ctx)})
        return hx_trigger(render(request, "miniapp/checkout.html", ctx, status_code=422), toast={"msg": ctx["errors"]["general"], "type": "bad"}, haptic="error")
    # staff alert (never blocks the customer)
    try:
        await notifications.notify_staff(
            db, t("uz", "notify.new_order_staff", number=order.number, customer=notifications.esc(user.full_name), qty=order.total_qty, total=f"{order.total} {order.currency}"), kind="new_order"
        )
        await db.commit()
    except Exception:  # noqa: BLE001
        pass
    resp = redirect(request, f"/app/orders/{order.id}/success")
    save_cart(request, resp, {})
    return resp


@router.get("/orders/{order_id}/success")
async def order_success(order_id: int, request: Request, db: DB, lang: Lang, user: User = Depends(require_registered)):
    order = await db.get(Order, order_id)
    if order is None or order.user_id != user.id:
        return redirect(request, "/app/orders")
    return render(request, "miniapp/order_success.html", {"lang": lang, "order": order, "hide_nav": True})
