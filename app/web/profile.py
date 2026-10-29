from fastapi import Depends, Form, Request
from sqlalchemy import func, select

from app.deps import DB, CurrentUser, Lang, redirect, require_user
from app.enums import SubscriptionType
from app.i18n import normalize_lang, t
from app.models import Country, Order, Product, Subscription, User
from app.services.settings_service import get_setting
from app.templating import render
from app.web.common import hx_trigger
from app.web.router import router


async def _subs(db, user_id: int) -> dict:
    rows = (await db.execute(select(Subscription).where(Subscription.user_id == user_id, Subscription.active.is_(True)))).scalars().all()
    out = {"new_arrivals": False, "auction": False, "brands": set(), "capacities": set()}
    for s in rows:
        if s.type == SubscriptionType.NEW_ARRIVALS:
            out["new_arrivals"] = True
        elif s.type == SubscriptionType.AUCTION:
            out["auction"] = True
        elif s.type == SubscriptionType.BRAND:
            out["brands"].add(s.value.get("brand"))
        elif s.type == SubscriptionType.CAPACITY:
            out["capacities"].add(int(s.value.get("gb", 0)))
    return out


@router.get("/profile")
async def profile_page(request: Request, db: DB, lang: Lang, user: CurrentUser):
    if user is None:
        return render(request, "miniapp/profile.html", {"lang": lang, "orders_count": 0, "subs": None, "page_title": t(lang, "profile.title")})
    orders_count = (await db.execute(select(func.count()).select_from(Order).where(Order.user_id == user.id))).scalar_one()
    return render(
        request, "miniapp/profile.html",
        {"lang": lang, "orders_count": orders_count, "subs": await _subs(db, user.id), "working_hours": await get_setting(db, "working_hours"), "reply_time": await get_setting(db, "reply_time"), "page_title": t(lang, "profile.title")},
    )


@router.get("/profile/edit")
async def profile_edit(request: Request, db: DB, lang: Lang, user: User = Depends(require_user)):
    countries = (await db.execute(select(Country).where(Country.is_active.is_(True)).order_by(Country.sort))).scalars().all()
    from app.models import City

    code = (user.country or (countries[0].code if countries else "UZ"))
    cities = (await db.execute(select(City).where(City.country_code == code, City.is_active.is_(True)).order_by(City.sort))).scalars().all()
    return render(request, "miniapp/profile_edit.html", {"lang": lang, "countries": countries, "cities": cities, "page_title": t(lang, "profile.edit_title"), "back_url": "/app/profile"})


@router.post("/profile/edit")
async def profile_edit_submit(request: Request, db: DB, lang: Lang, user: User = Depends(require_user), first_name: str = Form(""), last_name: str = Form(""), phone: str = Form(""), country: str = Form(""), city: str = Form(""), city_other: str = Form(""), ui_lang: str = Form("uz"), ads_opt_in: str | None = Form(None)):
    if city == "__other__":
        city = city_other
    if first_name.strip():
        user.first_name = first_name.strip()[:100]
    user.last_name = last_name.strip()[:100]
    if phone.strip() and phone.strip() != user.phone:
        user.phone = phone.strip()[:32]
        user.phone_verified = False
    if country:
        user.country = country.upper()[:2]
    if city.strip():
        user.city = city.strip()[:100]
    user.lang = normalize_lang(ui_lang)
    user.ads_opt_in = bool(ads_opt_in)
    await db.commit()
    resp = redirect(request, "/app/profile")
    resp.set_cookie("nuhd_lang", user.lang, max_age=60 * 60 * 24 * 30)
    return hx_trigger(resp, toast={"msg": t(lang, "profile.saved"), "type": "ok"}, haptic="success")


@router.get("/profile/subscriptions")
async def subscriptions_page(request: Request, db: DB, lang: Lang, user: User = Depends(require_user)):
    brands = (await db.execute(select(Product.brand).where(Product.is_active.is_(True)).distinct().order_by(Product.brand))).scalars().all()
    caps = (await db.execute(select(Product.capacity_gb).where(Product.is_active.is_(True)).distinct().order_by(Product.capacity_gb))).scalars().all()
    return render(request, "miniapp/subscriptions.html", {"lang": lang, "subs": await _subs(db, user.id), "brands": brands, "caps": caps, "page_title": t(lang, "profile.subscriptions"), "back_url": "/app/profile"})


@router.post("/profile/subscriptions")
async def subscriptions_save(request: Request, db: DB, lang: Lang, user: User = Depends(require_user)):
    form = await request.form()
    rows = (await db.execute(select(Subscription).where(Subscription.user_id == user.id))).scalars().all()
    for r in rows:
        await db.delete(r)
    if form.get("new_arrivals"):
        db.add(Subscription(user_id=user.id, type=SubscriptionType.NEW_ARRIVALS, value={}))
    if form.get("auction"):
        db.add(Subscription(user_id=user.id, type=SubscriptionType.AUCTION, value={}))
    for b in form.getlist("brand"):
        db.add(Subscription(user_id=user.id, type=SubscriptionType.BRAND, value={"brand": b[:60]}))
    for g in form.getlist("gb"):
        try:
            db.add(Subscription(user_id=user.id, type=SubscriptionType.CAPACITY, value={"gb": int(g)}))
        except ValueError:
            pass
    await db.commit()
    return hx_trigger(redirect(request, "/app/profile/subscriptions"), toast={"msg": t(lang, "profile.saved"), "type": "ok"}, haptic="success")


@router.get("/profile/auctions")
async def my_auctions(request: Request, db: DB, lang: Lang, user: User = Depends(require_user)):
    from app.web.auctions import user_auction_summary

    lots, deposits = await user_auction_summary(db, user.id)
    return render(request, "miniapp/my_auctions.html", {"lang": lang, "lots": lots, "deposits": deposits, "page_title": t(lang, "profile.my_auctions"), "back_url": "/app/profile"})
