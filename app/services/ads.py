"""Ad posts: the Telegram message built from a post, the address book of chats it can go to, sending with the results
kept per chat, and the clicks counted when someone opens the shop through the post's link.

Targets live in the `ad_targets` setting — [{id, title, type, username, members, can_post, left, added_at}] — filled two
ways: the bot writes a chat down when it is added to it (my_chat_member), and the staff add one by id / @username / link,
which the bot checks with get_chat first.
"""
import asyncio
import html
import logging
import re
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.enums import AdPostStatus
from app.i18n import t
from app.models import AdPost, Product
from app.services import storage
from app.services.settings_service import get_setting, set_setting
from app.templating import capacity, money

log = logging.getLogger("nuhd.ads")
CAPTION_MAX = 1024  # Telegram: a photo caption
TYPES = ("channel", "supergroup", "group", "private")
RATE_SLEEP = 0.06  # between chats


def deep_links(campaign: str) -> dict:
    return {"app": f"https://t.me/{settings.bot_username}?startapp=src_{campaign}", "start": f"https://t.me/{settings.bot_username}?start=src_{campaign}"}


def render_post(post: AdPost, products: list[Product]) -> str:
    """The HTML message: the text, one line per product, the shop link (the inline button repeats it for one-tap opening)."""
    lines = [html.escape(post.text).strip(), ""]
    for p in products:
        price = money(p.price, p.currency) if p.price is not None else "—"
        lines.append(f"• <b>{html.escape(p.brand)} {html.escape(p.model)}</b> {capacity(p.capacity_gb)} · {p.condition.value.upper()} · {price}/pc")
    links = deep_links(post.campaign)
    lines += ["", f"🛒 <a href=\"{links['app']}\">{html.escape(settings.app_name)}</a>"]
    return "\n".join(lines)


def button_text(lang: str | None = None) -> str:
    return t(lang or settings.default_lang, "notify.ad_open_shop")


def keyboard(post: AdPost):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=button_text(), url=deep_links(post.campaign)["app"])]])


def photo_url(products: list[Product]) -> str | None:
    """The first product picture as a public https URL (Telegram fetches it), or None when there is none to give."""
    for p in products:
        cover = p.cover
        if cover is None:
            continue
        u = storage.url(cover.filename)
        if not u:
            continue
        if u.startswith("/"):
            if not settings.base_url.startswith("https://"):
                return None
            u = settings.base_url.rstrip("/") + u
        return u
    return None


async def products_of(db: AsyncSession, ids: list[int]) -> list[Product]:
    if not ids:
        return []
    rows = (await db.execute(select(Product).where(Product.id.in_(ids)))).scalars().unique().all()
    by = {p.id: p for p in rows}
    return [by[i] for i in ids if i in by]


# ---------- targets ----------

def parse_ids(text: str | None) -> list[int]:
    """Chat ids typed by hand: numbers separated by commas, spaces or new lines."""
    return [int(x) for x in re.split(r"[,\s;]+", text or "") if re.fullmatch(r"-?\d+", x)]


def clean_target(row) -> dict | None:
    if not isinstance(row, dict):
        return None
    try:
        cid = int(row.get("id"))
    except (TypeError, ValueError):
        return None
    return {"id": cid, "title": str(row.get("title") or "")[:120], "type": row.get("type") if row.get("type") in TYPES else "group", "username": (str(row.get("username") or "")[:64] or None),
            "members": int(row["members"]) if str(row.get("members") or "").lstrip("-").isdigit() else None, "can_post": bool(row.get("can_post", True)), "left": bool(row.get("left", False)),
            "added_at": row.get("added_at"), "checked_at": row.get("checked_at")}


async def targets(db: AsyncSession) -> list[dict]:
    rows = [clean_target(r) for r in (await get_setting(db, "ad_targets", []) or [])]
    return [r for r in rows if r]


async def save_targets(db: AsyncSession, rows: list[dict]) -> None:
    await set_setting(db, "ad_targets", rows)


async def upsert_target(db: AsyncSession, info: dict) -> dict:
    """Add or refresh one chat in the address book (by id). Returns the stored row."""
    rows = await targets(db)
    new = clean_target(info)
    if new is None:
        raise ValueError("bad chat")
    now = datetime.now(UTC).isoformat(timespec="seconds")
    for r in rows:
        if r["id"] == new["id"]:
            r.update({k: v for k, v in new.items() if k not in ("added_at",) and v is not None} | {"left": new["left"], "checked_at": now})
            await save_targets(db, rows)
            return r
    new["added_at"], new["checked_at"] = now, now
    rows.append(new)
    await save_targets(db, rows)
    return new


async def mark_left(db: AsyncSession, chat_id: int, left: bool = True) -> None:
    rows = await targets(db)
    for r in rows:
        if r["id"] == chat_id:
            r["left"] = left
    await save_targets(db, rows)


async def remove_target(db: AsyncSession, chat_id: int) -> bool:
    rows = await targets(db)
    kept = [r for r in rows if r["id"] != chat_id]
    if len(kept) == len(rows):
        return False
    await save_targets(db, kept)
    return True


def parse_ref(ref: str) -> int | str | None:
    """-100123… → int chat id; @name, name or t.me/name → '@name'."""
    s = (ref or "").strip()
    if not s:
        return None
    if re.fullmatch(r"-?\d{5,}", s):
        return int(s)
    m = re.search(r"(?:t\.me/|telegram\.me/)?@?([A-Za-z][A-Za-z0-9_]{3,31})/?$", s)
    return "@" + m.group(1) if m else None


async def chat_info(bot, ref: int | str) -> dict:
    """What the bot can tell about a chat: title, type, username, members, and whether it may post there."""
    chat = await bot.get_chat(ref)
    me = await bot.get_me()
    can_post, members = True, None
    try:
        member = await bot.get_chat_member(chat.id, me.id)
        status = getattr(member, "status", "")
        if chat.type == "channel":
            can_post = status == "administrator" and bool(getattr(member, "can_post_messages", True))
        else:
            can_post = status in ("administrator", "member", "creator")
    except Exception:  # noqa: BLE001
        can_post = False
    try:
        members = await bot.get_chat_member_count(chat.id)
    except Exception:  # noqa: BLE001
        pass
    return {"id": chat.id, "title": chat.title or chat.full_name if hasattr(chat, "full_name") else (chat.title or ""), "type": chat.type, "username": chat.username, "members": members, "can_post": can_post, "left": False}


class TargetError(Exception):
    pass


async def check_target(db: AsyncSession, bot, ref: str) -> dict:
    """Look a chat up with the bot and put it in the address book. Raises TargetError with a short code."""
    parsed = parse_ref(ref)
    if parsed is None:
        raise TargetError("bad_ref")
    if bot is None:
        raise TargetError("bot_off")
    try:
        info = await chat_info(bot, parsed)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        raise TargetError("not_found" if "not found" in msg.lower() or "chat_id is empty" in msg.lower() else "api:" + msg[:120]) from e
    return await upsert_target(db, info)


# ---------- sending ----------

def _one(chat_id: int, title: str, ok: bool, message_id: int | None = None, error: str | None = None, test: bool = False) -> dict:
    return {"chat_id": chat_id, "title": title, "ok": ok, "message_id": message_id, "error": error, "at": datetime.now(UTC).isoformat(timespec="seconds"), "test": test}


async def send_to(bot, post: AdPost, products: list[Product], chat_id: int, title: str = "", *, test: bool = False) -> dict:
    """One chat: the picture of the first product with the post as its caption when it fits, else the text; always with
    the Open-shop button."""
    text, photo = render_post(post, products), photo_url(products)
    try:
        if photo and len(text) <= CAPTION_MAX:
            msg = await bot.send_photo(chat_id, photo, caption=text, reply_markup=keyboard(post))
        else:
            msg = await bot.send_message(chat_id, text, reply_markup=keyboard(post), disable_web_page_preview=True)
        return _one(chat_id, title, True, getattr(msg, "message_id", None), test=test)
    except Exception as e:  # noqa: BLE001
        log.warning("ad %s → %s failed: %s", post.id, chat_id, e)
        return _one(chat_id, title, False, error=str(e)[:200], test=test)


async def send_post(db: AsyncSession, bot, post: AdPost, chat_ids: list[int] | None = None) -> list[dict]:
    """The post to its chats (or the given ones): each result is kept on the post; it becomes `sent` once one chat took it.
    The caller commits."""
    products = await products_of(db, post.product_ids)
    names = {r["id"]: r["title"] for r in await targets(db)}
    results = []
    for n, cid in enumerate(chat_ids if chat_ids is not None else post.target_chat_ids):
        if n:
            await asyncio.sleep(RATE_SLEEP)
        results.append(await send_to(bot, post, products, cid, names.get(cid, "")))
    post.deliveries = list(post.deliveries or []) + results
    if any(r["ok"] for r in results):
        post.status, post.sent_at = AdPostStatus.SENT, datetime.now(UTC)
    return results


async def send_test(db: AsyncSession, bot, post: AdPost, chat_id: int) -> dict:
    """A trial copy to one chat (the staff member or the staff group): the post's status does not change."""
    products = await products_of(db, post.product_ids)
    r = await send_to(bot, post, products, chat_id, "", test=True)
    post.deliveries = list(post.deliveries or []) + [r]
    return r


# ---------- clicks ----------

async def count_click(db: AsyncSession, source: str | None) -> bool:
    """A start parameter src_<campaign> opened the bot or the Mini App: one more click on that post."""
    camp = (source or "").removeprefix("src_").strip()
    if not camp:
        return False
    res = await db.execute(update(AdPost).where(AdPost.campaign == camp).values(clicks=AdPost.clicks + 1))
    return bool(res.rowcount)


def summary(post: AdPost) -> dict:
    """Delivered / failed counts for the list and the card."""
    real = [d for d in (post.deliveries or []) if not d.get("test")]
    return {"ok": sum(1 for d in real if d.get("ok")), "bad": sum(1 for d in real if not d.get("ok")), "tests": sum(1 for d in (post.deliveries or []) if d.get("test"))}
