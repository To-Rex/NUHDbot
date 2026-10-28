from decimal import Decimal

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select

from app.deps import DB, CurrentUser, Lang
from app.i18n import t
from app.models import Product
from app.services.orders import OrderError, validate_line
from app.templating import render
from app.web.common import current_cart, hx_trigger, save_cart, toast
from app.web.router import router


async def _cart_lines(db, cart: dict[int, int]):
    if not cart:
        return [], Decimal(0), "USD"
    products = (await db.execute(select(Product).where(Product.id.in_(list(cart.keys()))))).scalars().unique().all()
    by_id = {p.id: p for p in products}
    lines, total, currency = [], Decimal(0), "USD"
    for pid, qty in cart.items():
        p = by_id.get(pid)
        if p is None or not p.is_active:
            continue
        line_total = Decimal(p.price or 0) * qty
        total += line_total
        currency = p.currency
        lines.append({"p": p, "qty": qty, "total": line_total, "max": p.available, "step": p.box_qty if (p.full_box_only and p.box_qty) else 1})
    return lines, total, currency


def _error_message(lang: str, e: OrderError) -> str:
    return t(lang, f"checkout.errors.{e.code}", **e.ctx)


@router.get("/cart")
async def cart_page(request: Request, db: DB, user: CurrentUser, lang: Lang):
    cart = current_cart(request)
    lines, total, currency = await _cart_lines(db, cart)
    return render(request, "miniapp/cart.html", {"lang": lang, "lines": lines, "total": total, "currency": currency, "page_title": t(lang, "cart.title"), "back_url": "/app/catalog"})


@router.post("/cart/add")
async def cart_add(request: Request, db: DB, user: CurrentUser, lang: Lang, product_id: int = Form(...), qty: int = Form(1)):
    cart = current_cart(request)
    new_qty = cart.get(product_id, 0) + max(1, qty)
    try:
        await validate_line(db, product_id, new_qty)
    except OrderError as e:
        if e.code == "not_enough_stock" and cart.get(product_id):
            # already in cart; cap to available
            try:
                await validate_line(db, product_id, e.ctx.get("available", 0))
                new_qty = e.ctx["available"]
            except OrderError:
                resp = HTMLResponse("", status_code=200)
                return toast(resp, _error_message(lang, e), "bad", "error")
        else:
            resp = HTMLResponse("", status_code=200)
            return toast(resp, _error_message(lang, e), "bad", "error")
    cart[product_id] = new_qty
    resp = HTMLResponse("")
    save_cart(request, resp, cart)
    count = sum(cart.values())
    return hx_trigger(resp, cartUpdated={"count": count}, toast={"msg": t(lang, "product.added"), "type": "ok"}, haptic="success")


@router.post("/cart/update")
async def cart_update(request: Request, db: DB, user: CurrentUser, lang: Lang, product_id: int = Form(...), qty: int = Form(...)):
    cart = current_cart(request)
    if qty <= 0:
        cart.pop(product_id, None)
    else:
        try:
            await validate_line(db, product_id, qty)
        except OrderError as e:
            lines, total, currency = await _cart_lines(db, cart)
            resp = render(request, "miniapp/partials/cart_body.html", {"lang": lang, "lines": lines, "total": total, "currency": currency})
            return toast(resp, _error_message(lang, e), "bad", "error")
        cart[product_id] = qty
    lines, total, currency = await _cart_lines(db, cart)
    resp = render(request, "miniapp/partials/cart_body.html", {"lang": lang, "lines": lines, "total": total, "currency": currency})
    save_cart(request, resp, cart)
    return hx_trigger(resp, cartUpdated={"count": sum(cart.values())}, haptic="select")


@router.post("/cart/remove")
async def cart_remove(request: Request, db: DB, user: CurrentUser, lang: Lang, product_id: int = Form(...)):
    cart = current_cart(request)
    cart.pop(product_id, None)
    lines, total, currency = await _cart_lines(db, cart)
    resp = render(request, "miniapp/partials/cart_body.html", {"lang": lang, "lines": lines, "total": total, "currency": currency})
    save_cart(request, resp, cart)
    return hx_trigger(resp, cartUpdated={"count": sum(cart.values())}, toast={"msg": t(lang, "cart.removed"), "type": ""}, haptic="light")


@router.post("/cart/clear")
async def cart_clear(request: Request, db: DB, user: CurrentUser, lang: Lang):
    resp = render(request, "miniapp/partials/cart_body.html", {"lang": lang, "lines": [], "total": Decimal(0), "currency": "USD"})
    save_cart(request, resp, {})
    return hx_trigger(resp, cartUpdated={"count": 0}, toast={"msg": t(lang, "cart.cleared"), "type": ""}, haptic="light")


@router.get("/cart/count")
async def cart_count(request: Request, user: CurrentUser):
    return Response(str(sum(current_cart(request).values())), media_type="text/plain")
