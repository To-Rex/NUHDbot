from fastapi import Request
from sqlalchemy import update

from app.deps import DB, CurrentUser, Lang
from app.models import Product
from app.services import catalog
from app.services.settings_service import get_setting
from app.templating import render
from app.web.router import router


@router.get("/products/{product_id}")
async def product_page(product_id: int, request: Request, db: DB, user: CurrentUser, lang: Lang):
    p = await catalog.get_product(db, product_id)
    if p is None:
        return render(request, "miniapp/not_found.html", {"lang": lang, "message_key": "product.not_found", "back_url": "/app/catalog"}, status_code=404)
    await db.execute(update(Product).where(Product.id == p.id).values(views=Product.views + 1))
    await db.commit()
    similar = await catalog.similar_products(db, p, limit=8)
    delivery = await get_setting(db, "delivery_text")
    payment = await get_setting(db, "payment_text")
    step = p.box_qty if (p.full_box_only and p.box_qty) else 1
    min_qty = p.min_order
    if step > 1 and min_qty % step:
        min_qty = ((min_qty // step) + 1) * step
    return render(
        request,
        "miniapp/product.html",
        {
            "lang": lang,
            "p_": p,
            "similar": similar,
            "delivery": delivery,
            "payment": payment,
            "step": step,
            "min_qty": min_qty,
            "page_title": p.model,
            "back_url": "/app/catalog",
            "refresh_mismatch": bool(p.label_model and p.label_model != p.model),
        },
    )
