from fastapi import Request
from fastapi.responses import RedirectResponse

from app.admin.router import router
from app.deps import ADMIN_COOKIE, DB, CurrentStaff
from app.i18n import t
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
