from fastapi import Depends, Request, Response
from fastapi.responses import RedirectResponse

from app.admin.common import staff_dep
from app.admin.router import router
from app.deps import ADMIN_COOKIE, ADMIN_LANG_COOKIE, DB, THEME_COOKIE, THEMES, CurrentStaff, set_pref_cookie
from app.i18n import normalize_lang, t
from app.models import User
from app.security import sign_session
from app.services import audit
from app.services.users import authenticate_staff
from app.templating import render


@router.get("/login")
async def login_form(request: Request, staff: CurrentStaff, next: str | None = None):
    if staff:
        return RedirectResponse(next or "/admin", status_code=302)
    return render(request, "admin/login.html", {"next": next or "/admin", "error": None}, lang="uz")


@router.post("/login")
async def login(request: Request, db: DB):
    form = await request.form()
    login_ = (form.get("login") or "").strip()
    password = form.get("password") or ""
    next_url = form.get("next") or "/admin"
    if not next_url.startswith("/admin"):
        next_url = "/admin"
    user = await authenticate_staff(db, login_, password)
    if user is None:
        return render(request, "admin/login.html", {"next": next_url, "error": t("uz", "admin.login_failed"), "login": login_}, lang="uz", status_code=401)
    await audit.log(db, user.id, "staff.login", "user", user.id)
    await db.commit()
    resp = RedirectResponse(next_url, status_code=303)
    resp.set_cookie(ADMIN_COOKIE, sign_session({"uid": user.id}), max_age=60 * 60 * 12, httponly=True, samesite="strict", secure=request.url.scheme == "https", path="/admin")
    return resp


@router.post("/logout")
@router.get("/logout")
async def logout(request: Request):
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(ADMIN_COOKIE, path="/admin")
    return resp


def _safe_next(next_url: str | None) -> str:
    return next_url if next_url and next_url.startswith("/admin") else "/admin"


@router.get("/lang/{code}")
@router.post("/lang/{code}")
async def admin_set_lang(code: str, request: Request, db: DB, next: str | None = None, staff: User = Depends(staff_dep())):
    code = normalize_lang(code)
    staff.lang = code
    await db.commit()
    resp = RedirectResponse(_safe_next(next), status_code=303)
    set_pref_cookie(resp, ADMIN_LANG_COOKIE, code, path="/admin")
    return resp


@router.post("/theme/{mode}")
@router.get("/theme/{mode}")
async def admin_set_theme(mode: str, request: Request, db: DB, next: str | None = None, staff: User = Depends(staff_dep())):
    if mode not in THEMES:
        mode = "auto"
    staff.theme = mode
    await db.commit()
    resp = Response(status_code=204) if request.method == "POST" else RedirectResponse(_safe_next(next), status_code=303)
    set_pref_cookie(resp, THEME_COOKIE, mode)
    return resp


@router.post("/hint/dismiss")
async def hint_dismiss(request: Request, staff: User = Depends(staff_dep())):
    from app.admin.common import HINT_COOKIE

    resp = Response(status_code=204)
    set_pref_cookie(resp, HINT_COOKIE, "1", path="/admin")
    return resp


@router.get("/search")
async def admin_search(request: Request, db: DB, staff: User = Depends(staff_dep())):
    """Global search box: orders, customers, products, serials. Returns a dropdown partial."""
    from sqlalchemy import cast, or_, select
    from sqlalchemy.types import Text

    from app.admin.common import CUSTOMER_ROLES, ORDER_ROLES, PRODUCT_ROLES, can
    from app.admin.common import render as arender
    from app.models import Order, OrderItem, Product

    q = (request.query_params.get("q") or "").strip()[:60]
    if len(q) < 2:
        return arender(request, staff, "admin/partials/search_results.html", {"q": q, "orders": [], "customers": [], "products": [], "serial_hits": []})
    like = f"%{q}%"
    orders = customers = products = serial_hits = []
    if can(staff, ORDER_ROLES):
        orders = (
            await db.execute(
                select(Order).join(User, User.id == Order.user_id).where(
                    or_(Order.number.ilike(like), Order.receiver_phone.ilike(like), Order.receiver_name.ilike(like), Order.cargo_code.ilike(like), Order.tracking_number.ilike(like), User.first_name.ilike(like), User.last_name.ilike(like), User.phone.ilike(like))
                ).order_by(Order.id.desc()).limit(6)
            )
        ).scalars().unique().all()
        serial_hits = (
            await db.execute(select(OrderItem).where(cast(OrderItem.serials, Text).ilike(like)).order_by(OrderItem.id.desc()).limit(4))
        ).scalars().unique().all()
    if can(staff, CUSTOMER_ROLES):
        customers = (
            await db.execute(
                select(User).where(User.role == "customer", or_(User.first_name.ilike(like), User.last_name.ilike(like), User.phone.ilike(like), User.tg_username.ilike(like))).order_by(User.id.desc()).limit(6)
            )
        ).scalars().all()
    if can(staff, PRODUCT_ROLES):
        products = (
            await db.execute(
                select(Product).where(or_(Product.brand.ilike(like), Product.model.ilike(like), Product.label_model.ilike(like), Product.series.ilike(like))).order_by(Product.is_active.desc(), Product.id.desc()).limit(6)
            )
        ).scalars().unique().all()
    return arender(request, staff, "admin/partials/search_results.html", {"q": q, "orders": orders, "customers": customers, "products": products, "serial_hits": serial_hits})
