import re

from fastapi import Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.deps import DB, Lang, redirect, require_user
from app.i18n import normalize_lang, t
from app.models import City, Country, User
from app.services.users import complete_registration, set_phone_from_contact
from app.templating import render
from app.web.common import hx_trigger, safe_next
from app.web.router import router

PHONE_RE = re.compile(r"^\+?[0-9]{9,15}$")


def _clean_phone(raw: str) -> str | None:
    digits = re.sub(r"[^\d+]", "", raw or "")
    if digits and not digits.startswith("+"):
        digits = "+" + digits
    return digits if PHONE_RE.match(digits or "") else None


async def _countries(db):
    return (await db.execute(select(Country).where(Country.is_active.is_(True)).order_by(Country.sort))).scalars().all()


async def _cities(db, code: str):
    return (await db.execute(select(City).where(City.country_code == code, City.is_active.is_(True)).order_by(City.sort))).scalars().all()


@router.get("/register")
async def register_page(request: Request, db: DB, lang: Lang, user: User = Depends(require_user), next: str | None = None):
    nxt = safe_next(next)
    if user.is_registered:
        return redirect(request, nxt)
    countries = await _countries(db)
    country = user.country or "UZ"
    cities = await _cities(db, country)
    return render(
        request,
        "miniapp/register.html",
        {"lang": lang, "countries": countries, "cities": cities, "country": country, "next": nxt, "hide_nav": True, "errors": {}, "form": {}},
    )


@router.get("/register/cities")
async def register_cities(request: Request, db: DB, lang: Lang, country: str = "UZ", selected: str | None = None):
    cities = await _cities(db, country.upper()[:2])
    return render(request, "miniapp/partials/city_select.html", {"lang": lang, "cities": cities, "selected": selected})


@router.post("/register/phone")
async def register_phone(request: Request, db: DB, lang: Lang, user: User = Depends(require_user), phone: str = Form(...)):
    """Called by the Mini App after Telegram's requestContact resolves (contact phone), or by manual input."""
    clean = _clean_phone(phone)
    if not clean:
        resp = HTMLResponse("", status_code=422)
        return hx_trigger(resp, toast={"msg": t(lang, "register.errors.phone"), "type": "bad"}, haptic="error")
    verified = request.headers.get("X-Phone-Source") == "telegram"
    if verified:
        await set_phone_from_contact(db, user, clean)
    else:
        user.phone = clean
    await db.commit()
    return render(request, "miniapp/partials/phone_ok.html", {"lang": lang, "phone": clean, "verified": verified})


@router.post("/register")
async def register_submit(
    request: Request,
    db: DB,
    lang: Lang,
    user: User = Depends(require_user),
    first_name: str = Form(""),
    last_name: str = Form(""),
    phone: str = Form(""),
    country: str = Form(""),
    city: str = Form(""),
    city_other: str = Form(""),
    ui_lang: str = Form("uz"),
    bought_before: str = Form(""),
    ads_opt_in: str | None = Form(None),
    next: str = Form("/app/home"),
):
    errors: dict[str, str] = {}
    clean_phone = _clean_phone(phone) or user.phone
    if not clean_phone:
        errors["phone"] = t(lang, "register.errors.phone")
    if not first_name.strip():
        errors["name"] = t(lang, "register.errors.name")
    if not country:
        errors["country"] = t(lang, "register.errors.country")
    city_val = city_other.strip() if city == "__other__" else city.strip()
    if not city_val:
        errors["city"] = t(lang, "register.errors.city")
    if errors:
        countries = await _countries(db)
        cities = await _cities(db, country or "UZ")
        form = {"first_name": first_name, "last_name": last_name, "phone": phone, "country": country, "city": city, "city_other": city_other, "ui_lang": ui_lang, "bought_before": bought_before, "ads_opt_in": bool(ads_opt_in)}
        resp = render(request, "miniapp/register.html", {"lang": lang, "countries": countries, "cities": cities, "country": country or "UZ", "next": safe_next(next), "hide_nav": True, "errors": errors, "form": form}, status_code=422)
        return hx_trigger(resp, haptic="error")
    await complete_registration(
        db, user, first_name=first_name, last_name=last_name, phone=clean_phone, country=country, city=city_val, lang=normalize_lang(ui_lang),
        bought_before={"yes": True, "no": False}.get(bought_before), ads_opt_in=bool(ads_opt_in),
    )
    await db.commit()
    resp = redirect(request, safe_next(next))
    resp.set_cookie("nuhd_lang", user.lang, max_age=60 * 60 * 24 * 30)
    return hx_trigger(resp, toast={"msg": t(lang, "register.done"), "type": "ok"}, confetti=True)
