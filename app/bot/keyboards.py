"""Inline / reply keyboards. WebApp buttons need https; otherwise we degrade to plain URL buttons."""
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)

from app.config import settings
from app.i18n import t


def app_url(path: str = "/app") -> str:
    return settings.base_url.rstrip("/") + path


def is_https() -> bool:
    return settings.base_url.startswith("https://")


def app_button(text: str, path: str) -> InlineKeyboardButton:
    url = app_url(path)
    if is_https():
        return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))
    return InlineKeyboardButton(text=text, url=url if url.startswith("http") else "https://t.me/" + settings.bot_username)


def lang_keyboard() -> InlineKeyboardMarkup:
    """Five languages, each labelled in its own language (lang.<code> is the native name in every locale)."""
    buttons = [InlineKeyboardButton(text=t(code, f"lang.{code}"), callback_data=f"lang:{code}") for code in settings.langs]
    rows = [buttons[:2], buttons[2:]] if len(buttons) > 3 else [buttons]
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def main_menu(lang: str) -> InlineKeyboardMarkup:
    b = lambda key, path: app_button(t(lang, key), path)  # noqa: E731
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [b("bot.btn_catalog", "/app/catalog"), b("bot.btn_new", "/app/new")],
            [b("bot.btn_auction", "/app/auctions"), b("bot.btn_orders", "/app/orders")],
            [b("bot.btn_info", "/app/info"), b("bot.btn_profile", "/app/profile")],
            [InlineKeyboardButton(text=t(lang, "bot.btn_support"), callback_data="support:start")],
            [InlineKeyboardButton(text=t(lang, "bot.btn_lang"), callback_data="lang:menu")],
        ]
    )


def reply_main(lang: str, *, need_phone: bool) -> ReplyKeyboardMarkup | ReplyKeyboardRemove:
    rows: list[list[KeyboardButton]] = []
    if is_https():
        rows.append([KeyboardButton(text=t(lang, "bot.btn_open_app"), web_app=WebAppInfo(url=app_url("/app")))])
    if need_phone:
        rows.append([KeyboardButton(text=t(lang, "bot.btn_share_phone"), request_contact=True)])
    if not rows:
        return ReplyKeyboardRemove()
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def support_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "bot.btn_attach_order")), KeyboardButton(text=t(lang, "bot.btn_exit_chat"))]],
        resize_keyboard=True,
    )


def attach_orders_keyboard(lang: str, orders) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"{o.number} · {o.total_qty} · {o.status}", callback_data=f"support:attach:{o.id}")] for o in orders[:10]]
    rows.append([InlineKeyboardButton(text=t(lang, "bot.btn_no_order"), callback_data="support:attach:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_button(lang: str, order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[app_button(t(lang, "bot.btn_open_order"), f"/app/orders/{order_id}")]])


def menu_button(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t(lang, "bot.btn_menu"), callback_data="menu")]])
