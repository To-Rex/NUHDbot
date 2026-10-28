from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app.config import APP_DIR, settings
from app.enums import Condition, OrderStatus, TestStatus
from app.i18n import pick, t
from app.services.cart import get_cart

templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
env = templates.env
env.auto_reload = settings.debug
env.trim_blocks = True
env.lstrip_blocks = True

CONDITION_CLASS = {Condition.NEW: "cond-new", Condition.USED: "cond-used", Condition.REFRESH: "cond-refresh"}
TEST_CLASS = {TestStatus.UNTESTED: "test-untested", TestStatus.TESTING: "test-testing", TestStatus.TESTED: "test-tested"}
ORDER_STEPS = [
    OrderStatus.AWAITING_ADMIN,
    OrderStatus.AWAITING_ADVANCE,
    OrderStatus.ADVANCE_CONFIRMED,
    OrderStatus.TESTING,
    OrderStatus.TEST_READY,
    OrderStatus.AWAITING_CUSTOMER,
    OrderStatus.AWAITING_BALANCE,
    OrderStatus.PAID,
    OrderStatus.PACKING,
    OrderStatus.SHIPPED,
    OrderStatus.DELIVERED,
    OrderStatus.COMPLETED,
]


def money(value, currency: str | None = None, *, dash: str = "—") -> str:
    if value is None:
        return dash
    try:
        v = Decimal(value)
    except Exception:  # noqa: BLE001
        return str(value)
    s = f"{v:,.2f}".rstrip("0").rstrip(".") if v == v.to_integral() else f"{v:,.2f}"
    return f"${s}" if (currency or "USD") == "USD" else f"{s} {currency}"


def capacity(gb) -> str:
    gb = int(gb or 0)
    if gb >= 1000:
        return f"{gb // 1000}TB" if gb % 1000 == 0 else f"{gb / 1000:g}TB"
    return f"{gb}GB"


def fmt_dt(value: datetime | None, fmt: str = "%d.%m.%Y %H:%M", tz: str | None = None) -> str:
    if not value:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(ZoneInfo(tz or settings.timezone)).strftime(fmt)


def fmt_date(value: datetime | None) -> str:
    return fmt_dt(value, "%d.%m.%Y")


def iso(value: datetime | None) -> str:
    if not value:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def nl2br(value: str | None) -> Markup:
    from markupsafe import escape

    if not value:
        return Markup("")
    return Markup("<br>".join(escape(line) for line in str(value).splitlines()))


env.filters.update(
    money=money, capacity=capacity, dt=fmt_dt, date=fmt_date, iso=iso, nl2br=nl2br,
    pick=lambda v, lang: pick(v, lang),
)
env.globals.update(
    settings=settings,
    app_name=settings.app_name,
    bot_username=settings.bot_username,
    Condition=Condition,
    TestStatus=TestStatus,
    OrderStatus=OrderStatus,
    CONDITION_CLASS=CONDITION_CLASS,
    TEST_CLASS=TEST_CLASS,
    ORDER_STEPS=ORDER_STEPS,
    now=lambda: datetime.now(UTC),
)


def render(request: Request, name: str, ctx: dict | None = None, *, lang: str | None = None, status_code: int = 200, headers: dict | None = None):
    ctx = dict(ctx or {})
    user = getattr(request.state, "user", None)
    lang = lang or ctx.get("lang") or (user.lang if user else settings.default_lang)
    session = getattr(request.state, "session", {}) or {}
    cart = get_cart(session)
    ctx.setdefault("user", user)
    ctx.setdefault("lang", lang)
    ctx.setdefault("cart_count", sum(cart.values()))
    ctx.setdefault("is_htmx", request.headers.get("HX-Request") == "true")
    ctx.setdefault("path", request.url.path)
    ctx["t"] = lambda key, **kw: t(lang, key, **kw)
    ctx["p"] = lambda value: pick(value, lang)
    return templates.TemplateResponse(request, name, ctx, status_code=status_code, headers=headers)
