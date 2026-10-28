from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.enums import Role
from app.i18n import normalize_lang
from app.models import User
from app.security import load_session
from app.services.cart import read_session
from app.services.users import get_or_create_tg_user

ADMIN_COOKIE = "nuhd_admin"
THEME_COOKIE = "nuhd_theme"
ADMIN_LANG_COOKIE = "nuhd_admin_lang"
THEMES = ("auto", "light", "dark")
PREF_MAX_AGE = 60 * 60 * 24 * 365


def set_pref_cookie(response: Response, name: str, value: str, *, path: str = "/") -> None:
    """Long-lived, non-sensitive preference cookie (theme / language)."""
    response.set_cookie(name, value, max_age=PREF_MAX_AGE, samesite="none" if is_secure() else "lax", secure=is_secure(), path=path)


def resolve_theme(request: Request, user: User | None) -> str:
    """auto | light | dark. Query (one-shot) > account preference > cookie > auto."""
    q = request.query_params.get("theme")
    if q in THEMES:
        return q
    if user is not None and getattr(user, "theme", "auto") in ("light", "dark"):
        return user.theme
    c = request.cookies.get(THEME_COOKIE)
    return c if c in THEMES else "auto"
DB = Annotated[AsyncSession, Depends(get_db)]


def is_secure() -> bool:
    return settings.base_url.startswith("https://")


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def redirect(request: Request, url: str, code: int = 303) -> Response:
    """Redirect that also works for HTMX partial requests."""
    if is_htmx(request):
        return Response(status_code=204, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=code)


async def current_user(request: Request, db: DB) -> User | None:
    if getattr(request.state, "user_loaded", False):
        return request.state.user
    user: User | None = None
    sess = read_session(request)
    uid = sess.get("uid")
    if uid:
        user = await db.get(User, int(uid))
        if user and user.is_blocked:
            user = None
    if user is None and settings.debug and request.query_params.get("dev_tg"):
        # local development without Telegram: /app?dev_tg=1001
        user = await get_or_create_tg_user(db, {"id": int(request.query_params["dev_tg"]), "first_name": "Dev", "username": "dev"})
        await db.commit()
        request.state.set_session_uid = user.id
    request.state.user = user
    request.state.user_loaded = True
    request.state.session = sess
    return user


CurrentUser = Annotated[User | None, Depends(current_user)]


def get_lang(request: Request, user: CurrentUser) -> str:
    q = request.query_params.get("lang")
    if q:
        return normalize_lang(q)
    if user:
        return normalize_lang(user.lang)
    cookie = request.cookies.get("nuhd_lang")
    if cookie:
        return normalize_lang(cookie)
    accept = request.headers.get("accept-language", "")
    return normalize_lang(accept) if accept else settings.default_lang


Lang = Annotated[str, Depends(get_lang)]


async def require_user(request: Request, user: CurrentUser) -> User:
    if user is None:
        raise RedirectException(f"/app?next={request.url.path}")
    return user


async def require_registered(request: Request, user: CurrentUser) -> User:
    if user is None:
        raise RedirectException(f"/app?next={request.url.path}")
    if not user.is_registered:
        raise RedirectException(f"/app/register?next={request.url.path}")
    return user


class RedirectException(Exception):
    def __init__(self, url: str):
        self.url = url


# ---------- staff / admin panel ----------
async def current_staff(request: Request, db: DB) -> User | None:
    data = load_session(request.cookies.get(ADMIN_COOKIE))
    if not data or "uid" not in data:
        return None
    user = await db.get(User, int(data["uid"]))
    if user is None or not user.is_staff or user.is_blocked:
        return None
    return user


CurrentStaff = Annotated[User | None, Depends(current_staff)]


def require_staff(*roles: Role) -> Callable:
    allowed = set(roles)

    async def dep(request: Request, staff: CurrentStaff) -> User:
        if staff is None:
            raise RedirectException(f"/admin/login?next={request.url.path}")
        if allowed and staff.role not in allowed and staff.role != Role.ADMIN:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
        return staff

    return dep
