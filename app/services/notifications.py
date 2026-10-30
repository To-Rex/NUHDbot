"""Telegram notifications to customers. Never raises; logs to notification_log."""
import html
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.instance import get_bot
from app.config import settings
from app.enums import OrderStatus
from app.i18n import t
from app.models import NotificationLog, User

log = logging.getLogger("nuhd.notify")


def esc(s: object) -> str:
    return html.escape(str(s or ""))


def miniapp_button(text: str, path: str):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    url = settings.base_url.rstrip("/") + path
    if url.startswith("https://"):
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))]])
    return None  # Telegram refuses non-https web_app urls; skip button in local dev


async def send(db: AsyncSession, user: User | None, text: str, *, kind: str, chat_id: int | None = None, reply_markup=None) -> bool:
    chat = chat_id or (user.tg_id if user else None)
    bot = get_bot()
    ok, err = False, None
    if bot is None or chat is None:
        err = "bot disabled or no chat"
    else:
        try:
            await bot.send_message(chat, text, reply_markup=reply_markup, disable_web_page_preview=True)
            ok = True
        except Exception as e:  # noqa: BLE001
            err = str(e)[:500]
            log.warning("notify failed chat=%s: %s", chat, err)
    db.add(NotificationLog(user_id=user.id if user else None, tg_chat_id=chat, kind=kind, text=text[:4000], ok=ok, error=err))
    return ok


async def notify_order_status(db: AsyncSession, order, user: User) -> None:
    lang = user.lang
    status_txt = t(lang, f"order_status.{order.status}")
    text = t(lang, "notify.order_status", number=esc(order.number), status=esc(status_txt))
    extra_key = {
        OrderStatus.AWAITING_ADVANCE: "notify.order_awaiting_advance",
        OrderStatus.AWAITING_CUSTOMER: "notify.order_awaiting_customer",
        OrderStatus.AWAITING_BALANCE: "notify.order_awaiting_balance",
    }.get(order.status)
    if extra_key:
        text += "\n\n" + t(lang, extra_key, advance=f"{order.advance_amount} {order.currency}", balance=f"{order.balance_amount} {order.currency}")
    await send(db, user, text, kind="order_status", reply_markup=miniapp_button(t(lang, "notify.open_order"), f"/app/orders/{order.id}"))


async def notify_outbid(db: AsyncSession, user: User, auction, new_total) -> None:
    text = t(user.lang, "notify.outbid", title=esc(f"{auction.title} {auction.capacity_label}"), amount=f"{new_total} {auction.currency}")
    await send(db, user, text, kind="outbid", reply_markup=miniapp_button(t(user.lang, "notify.open_auction"), f"/app/auctions/{auction.id}"))


async def notify_auction_result(db: AsyncSession, auction, participants: list[User]) -> None:
    for u in participants:
        if auction.winner_user_id == u.id:
            text = t(u.lang, "notify.auction_won", title=esc(auction.title), amount=f"{auction.current_price_total} {auction.currency}")
        else:
            text = t(u.lang, "notify.auction_lost", title=esc(auction.title))
        await send(db, u, text, kind="auction_result", reply_markup=miniapp_button(t(u.lang, "notify.open_auction"), f"/app/auctions/{auction.id}"))


async def notify_support_reply(db: AsyncSession, user: User, thread_id: int, preview: str) -> None:
    text = t(user.lang, "notify.support_reply", preview=esc(preview[:200]))
    await send(db, user, text, kind="support_reply", reply_markup=miniapp_button(t(user.lang, "notify.open_chat"), f"/app/support/{thread_id}"))
