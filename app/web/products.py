from fastapi import Request
from sqlalchemy import update

from app.deps import DB, CurrentUser, Lang
from app.models import Product
from app.services import banners, catalog, interests
from app.services.settings_service import get_setting
from app.templating import render
from app.web.router import router


@router.get("/products/{product_id}")
async def product_page(product_id: int, request: Request, db: DB, user: CurrentUser, lang: Lang):
    p = await catalog.get_product(db, product_id)
    if p is None:
        return render(request, "miniapp/not_found.html", {"lang": lang, "message_key": "product.not_found", "back_url": "/app/catalog"}, status_code=404)
    await db.execute(update(Product).where(Product.id == p.id).values(views=Product.views + 1))
    await interests.track(db, user, "view", product=p)  # a sign of interest (signed-in customers, once per half hour)
    await db.commit()
    prof = await interests.profile(db, user.id) if interests.counts_as(user) else None
    similar = interests.rerank(await catalog.similar_products(db, p, limit=8), prof)  # the better fits for this customer first
    for_you = await interests.recommend(db, user, limit=6, exclude={p.id, *(s.id for s in similar)}, prof=prof) if prof else []
    delivery = await get_setting(db, "delivery_text")
    payment = await get_setting(db, "payment_text")
    step = p.box_qty if (p.full_box_only and p.box_qty) else 1
    min_qty = max(1, p.min_order)  # 0 = no minimum of its own
    if step > 1 and min_qty % step:
        min_qty = ((min_qty // step) + 1) * step
    return render(
        request,
        "miniapp/product.html",
        {
            "lang": lang,
            "p_": p,
            "similar": similar,
            "for_you": for_you,
            "delivery": delivery,
            "cond_texts": banners.clean_conditions(await get_setting(db, "home_conditions"))["desc"],  # the Banners page descriptions
            "payment": payment,
            "step": step,
            "min_qty": min_qty,
            "page_title": p.model,
            "back_url": "/app/catalog",
            "refresh_mismatch": bool(p.label_model and p.label_model != p.model),
        },
    )
