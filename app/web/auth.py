"""Splash + Telegram bootstrap, language switch, logout."""
from fastapi import Request
from fastapi.responses import RedirectResponse, Response

from app.config import settings
from app.deps import DB, THEME_COOKIE, THEMES, CurrentUser, Lang, is_secure, redirect, set_pref_cookie
from app.i18n import normalize_lang
from app.services import currencies
from app.templating import render
from app.web.router import router


@router.get("")
@router.get("/")
async def splash(request: Request, user: CurrentUser, lang: Lang, next: str | None = None):
    """First screen. If a session already exists we skip straight to home (fast path)."""
    target = next if next and next.startswith("/app") else "/app/home"
    if user is not None and not request.query_params.get("force"):
        return RedirectResponse(target, status_code=302)
    return render(request, "miniapp/splash.html", {"next": target, "lang": lang, "hide_nav": True})


@router.post("/lang/{code}")
@router.get("/lang/{code}")
async def set_lang(code: str, request: Request, user: CurrentUser, db: DB, next: str | None = None):
    code = normalize_lang(code)
    if user is not None:
        user.lang = code
        await db.commit()
    target = next if next and next.startswith("/app") else (request.headers.get("referer") or "/app/home")
    resp = redirect(request, target)
    resp.set_cookie("nuhd_lang", code, max_age=settings.session_max_age, samesite="none" if is_secure() else "lax", secure=is_secure())
    return resp


@router.post("/currency/{code}")
@router.get("/currency/{code}")
async def set_currency(code: str, request: Request, user: CurrentUser, db: DB, next: str | None = None):
    """Show prices in this currency (any active one) — stored on the account and in a cookie."""
    c = currencies.get(code)
    code = c.code if c is not None and c.is_active else ""
    if user is not None:
        user.currency = code or None
        await db.commit()
    if request.method == "POST":
        resp = Response(status_code=204)
    else:
        target = next if next and next.startswith("/app") and "//" not in next else (request.headers.get("referer") or "/app/home")
        resp = redirect(request, target)
    if code:
        set_pref_cookie(resp, currencies.COOKIE, code)
    else:
        resp.delete_cookie(currencies.COOKIE)
    return resp


@router.post("/theme/{mode}")
@router.get("/theme/{mode}")
async def set_theme(mode: str, request: Request, user: CurrentUser, db: DB, next: str | None = None):
    """auto | light | dark — stored in a cookie and on the account."""
    if mode not in THEMES:
        mode = "auto"
    if user is not None:
        user.theme = mode
        await db.commit()
    if request.method == "POST":
        resp = Response(status_code=204)
    else:
        target = next if next and next.startswith("/app") else (request.headers.get("referer") or "/app/home")
        resp = redirect(request, target)
    set_pref_cookie(resp, THEME_COOKIE, mode)
    return resp
