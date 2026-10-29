"""Shared helpers for the admin panel: role sets, CSRF, pagination, toasts, form parsing."""
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import ADMIN_LANG_COOKIE, DB, require_staff
from app.enums import Role
from app.i18n import normalize_lang
from app.models import User
from app.security import load_session, sign_session
from app.templating import render as _render

ADMIN = {Role.ADMIN}
PRODUCT_ROLES = {Role.ADMIN, Role.CATALOG, Role.WAREHOUSE, Role.TESTER}
PRODUCT_EDIT_ROLES = {Role.ADMIN, Role.CATALOG}
ORDER_ROLES = {Role.ADMIN, Role.ORDERS, Role.WAREHOUSE, Role.TESTER, Role.FINANCE}
ORDER_EDIT_ROLES = {Role.ADMIN, Role.ORDERS}
PAYMENT_ROLES = {Role.ADMIN, Role.FINANCE}
SHIP_ROLES = {Role.ADMIN, Role.WAREHOUSE, Role.ORDERS}
TEST_ROLES = {Role.ADMIN, Role.TESTER}
SUPPORT_ROLES = {Role.ADMIN, Role.ORDERS}
AUCTION_ROLES = {Role.ADMIN, Role.ORDERS, Role.FINANCE}
AUCTION_EDIT_ROLES = {Role.ADMIN}
CUSTOMER_ROLES = {Role.ADMIN, Role.ORDERS, Role.FINANCE, Role.MARKETING}
ARTICLE_ROLES = {Role.ADMIN, Role.CATALOG}
REPORT_ROLES = {Role.ADMIN, Role.FINANCE}
ADS_ROLES = {Role.ADMIN, Role.MARKETING}
FINANCE_VIEW = {Role.ADMIN, Role.FINANCE}

NAV_GROUPS = [
    ("manage", [("dashboard", "/admin", "home", None)]),
    ("sales", [
        ("orders", "/admin/orders", "package", ORDER_ROLES),
        ("payments", "/admin/payments", "wallet", PAYMENT_ROLES),
        ("auctions", "/admin/auctions", "gavel", AUCTION_ROLES),
        ("support", "/admin/support", "message", SUPPORT_ROLES),
    ]),
    ("catalog", [
        ("products", "/admin/products", "drive", PRODUCT_ROLES),
        ("brands", "/admin/brands", "tag", PRODUCT_EDIT_ROLES),
        ("articles", "/admin/articles", "book", ARTICLE_ROLES),
    ]),
    ("people", [
        ("customers", "/admin/customers", "users", CUSTOMER_ROLES),
        ("staff", "/admin/staff", "shield", ADMIN),
    ]),
    ("system", [
        ("settings", "/admin/settings", "settings", ADMIN),
        ("geo", "/admin/settings/geo", "globe", ADMIN),
        ("ads", "/admin/ads", "flag", ADS_ROLES),
        ("reports", "/admin/reports", "chart", REPORT_ROLES),
        ("audit", "/admin/audit", "list", ADMIN),
    ]),
]
NAV = [item for _, items in NAV_GROUPS for item in items]
CREATE_ITEMS = [
    ("product", "/admin/products/new", "drive", PRODUCT_EDIT_ROLES),
    ("brand", "/admin/brands/new", "tag", PRODUCT_EDIT_ROLES),
    ("auction", "/admin/auctions/new", "gavel", AUCTION_EDIT_ROLES),
    ("article", "/admin/articles/new", "book", ARTICLE_ROLES),
    ("ad", "/admin/ads/new", "flag", ADS_ROLES),
    ("staff", "/admin/staff#new", "shield", ADMIN),
]
HINT_COOKIE = "nuhd_admin_hint"


def can(staff: User, roles: set[Role] | None) -> bool:
    return roles is None or staff.role == Role.ADMIN or staff.role in roles


def csrf_token(staff: User) -> str:
    return sign_session({"c": staff.id})


async def verify_csrf(request: Request, staff: User) -> None:
    token = request.headers.get("X-CSRF")
    if not token:
        form = await request.form()
        token = form.get("_csrf")
    data = load_session(token, max_age=60 * 60 * 24 * 3) if token else None
    if not data or data.get("c") != staff.id:
        raise HTTPException(403, "csrf")


def staff_dep(*roles: Role):
    base = require_staff(*roles)

    async def dep(request: Request, db: DB, staff: Annotated[User, Depends(base)]) -> User:
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            await verify_csrf(request, staff)
        elif not request.headers.get("HX-Request"):
            try:
                request.state.badges = await nav_badges(db)
            except Exception:  # noqa: BLE001 — badges are decoration, never block a page
                request.state.badges = {}
        return staff

    return dep


def render(request: Request, staff: User, name: str, ctx: dict | None = None, **kw):
    ctx = dict(ctx or {})
    ctx.setdefault("staff", staff)
    ctx.setdefault("csrf", csrf_token(staff))
    ctx.setdefault("nav", [(k, u, i) for k, u, i, r in NAV if can(staff, r)])
    ctx.setdefault("nav_groups", [(g, [(k, u, i) for k, u, i, r in items if can(staff, r)]) for g, items in NAV_GROUPS])
    ctx.setdefault("create_items", [(k, u, i) for k, u, i, r in CREATE_ITEMS if can(staff, r)])
    path = request.url.path
    matches = [u for _, u, _, _ in NAV if (path == u if u == "/admin" else path.startswith(u))]
    ctx.setdefault("active_nav", max(matches, key=len) if matches else "")
    ctx.setdefault("show_hint", request.cookies.get(HINT_COOKIE) != "1")
    if "badges" not in ctx:
        ctx["badges"] = getattr(request.state, "badges", None) or {}
    ctx.setdefault("can_finance", can(staff, FINANCE_VIEW))
    ctx.setdefault("can", lambda roles: can(staff, roles))
    ctx.setdefault("roles", {k: v for k, v in globals().items() if k.endswith("_ROLES") or k in ("ADMIN", "FINANCE_VIEW")})
    request.state.staff = staff  # lets templating resolve the staff theme preference
    lang = kw.pop("lang", None) or request.cookies.get(ADMIN_LANG_COOKIE) or staff.lang or "uz"
    return _render(request, name, ctx, lang=normalize_lang(lang), **kw)


def toast(msg: str, kind: str = "ok", extra: dict | None = None) -> dict:
    payload: dict[str, Any] = {"toast": {"msg": msg, "type": kind}}
    if extra:
        payload.update(extra)
    return {"HX-Trigger": json.dumps(payload)}  # ASCII-only: HTTP headers are latin-1


def back(request: Request, url: str, msg: str | None = None, kind: str = "ok") -> Response:
    """Redirect after POST; for HTMX use HX-Redirect so the page reloads with a flash."""
    if msg:
        url = url + ("&" if "?" in url else "?") + "flash=" + __import__("urllib.parse").parse.quote(msg) + "&flash_kind=" + kind
    if request.headers.get("HX-Request") == "true":
        return Response(status_code=204, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


async def paginate(db: AsyncSession, stmt, page: int, per_page: int = 30):
    total = (await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()
    rows = (await db.execute(stmt.offset((page - 1) * per_page).limit(per_page))).scalars().unique().all()
    pages = max(1, (total + per_page - 1) // per_page)
    return list(rows), int(total), pages


def qpage(request: Request) -> int:
    try:
        return max(1, int(request.query_params.get("page", 1)))
    except ValueError:
        return 1


# ---- form parsing helpers ----
def f_str(form, key: str, default: str = "", maxlen: int | None = None) -> str:
    v = (form.get(key) or default).strip()
    return v[:maxlen] if maxlen else v


def f_opt(form, key: str, maxlen: int | None = None) -> str | None:
    v = f_str(form, key, "", maxlen)
    return v or None


def f_int(form, key: str, default: int | None = 0) -> int | None:
    v = (form.get(key) or "").strip()
    if v == "":
        return default
    try:
        return int(float(v))
    except ValueError:
        return default


def f_dec(form, key: str) -> Decimal | None:
    v = (form.get(key) or "").strip().replace(",", ".").replace(" ", "")
    if v == "":
        return None
    try:
        return Decimal(v).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def f_bool(form, key: str) -> bool:
    return form.get(key) in ("1", "on", "true", "yes")


def f_i18n(form, key: str) -> dict:
    return {lang: (form.get(f"{key}_{lang}") or "").strip() for lang in settings.langs if (form.get(f"{key}_{lang}") or "").strip()}


def f_dt(form, key: str) -> datetime | None:
    """Parse <input type=datetime-local> in the business timezone -> aware UTC."""
    v = (form.get(key) or "").strip()
    if not v:
        return None
    try:
        local = datetime.fromisoformat(v)
    except ValueError:
        return None
    if local.tzinfo is None:
        local = local.replace(tzinfo=ZoneInfo(settings.timezone))
    return local.astimezone(UTC)


def dt_local(value: datetime | None) -> str:
    """Aware datetime -> value for <input type=datetime-local> in business timezone."""
    if not value:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(ZoneInfo(settings.timezone)).strftime("%Y-%m-%dT%H:%M")


def snapshot(obj, fields: list[str]) -> dict:
    out = {}
    for f in fields:
        v = getattr(obj, f, None)
        out[f] = str(v) if isinstance(v, (Decimal, datetime)) else (v.value if hasattr(v, "value") else v)
    return out


__all__ = ["DB", "Depends", "HTTPException", "Request", "Response", "RedirectResponse", "select", "func", "Role", "User", "settings"]


async def nav_badges(db: AsyncSession) -> dict:
    from datetime import UTC, datetime, timedelta

    from app.enums import AuctionStatus, OrderStatus, PaymentStatus, ThreadStatus
    from app.models import Auction, Order, Payment, SupportThread

    awaiting = (await db.execute(select(func.count()).select_from(Order).where(Order.status == OrderStatus.AWAITING_ADMIN))).scalar_one()
    pays = (await db.execute(select(func.count()).select_from(Payment).where(Payment.status == PaymentStatus.PENDING))).scalar_one()
    unread = (
        await db.execute(select(func.count()).select_from(SupportThread).where(SupportThread.status == ThreadStatus.OPEN, SupportThread.unread_for_staff > 0))
    ).scalar_one()
    soon = datetime.now(UTC) + timedelta(hours=1)
    ending = (await db.execute(select(func.count()).select_from(Auction).where(Auction.status == AuctionStatus.LIVE, Auction.ends_at <= soon))).scalar_one()
    return {"orders": awaiting or None, "payments": pays or None, "support": unread or None, "auctions": ending or None, "total": (awaiting + pays + unread) or None}
