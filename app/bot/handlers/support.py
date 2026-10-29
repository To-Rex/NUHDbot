"""Customer ↔ admin chat through the bot (spec §24). Admin identity is never exposed."""
import io
import logging
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.config import settings
from app.enums import MessageKind
from app.i18n import pick, t
from app.models import SupportThread, User
from app.services import media, notifications, support
from app.services import orders as order_service
from app.services.notifications import esc
from app.services.settings_service import get_setting

log = logging.getLogger("nuhd.bot.support")
router = Router(name="support")
MAX_DL = 8 * 1024 * 1024


class SupportState(StatesGroup):
    chatting = State()


async def _enter(target: Message, user: User, db: AsyncSession, state: FSMContext) -> None:
    th = await support.get_or_create_thread(db, user)
    await state.set_state(SupportState.chatting)
    await state.update_data(thread_id=th.id)
    await target.answer(
        t(user.lang, "bot.support_enter", hours=esc(pick(await get_setting(db, "working_hours"), user.lang)), reply=esc(pick(await get_setting(db, "reply_time"), user.lang))),
        reply_markup=kb.support_keyboard(user.lang),
    )


@router.callback_query(F.data == "support:start")
async def cb_support(cq: CallbackQuery, user: User, db: AsyncSession, state: FSMContext) -> None:
    await cq.answer()
    await _enter(cq.message, user, db, state)


@router.message(F.text.in_({"/support", "/admin"}))
async def cmd_support(message: Message, user: User, db: AsyncSession, state: FSMContext) -> None:
    await _enter(message, user, db, state)


def _is_exit(text: str | None) -> bool:
    return bool(text) and text in {t(code, "bot.btn_exit_chat") for code in settings.langs}


def _is_attach(text: str | None) -> bool:
    return bool(text) and text in {t(code, "bot.btn_attach_order") for code in settings.langs}


@router.message(SupportState.chatting, F.text.func(_is_exit))
async def exit_chat(message: Message, user: User, state: FSMContext) -> None:
    await state.clear()
    await message.answer(t(user.lang, "bot.support_exit"), reply_markup=kb.reply_main(user.lang, need_phone=not user.phone))
    await message.answer(t(user.lang, "bot.btn_menu"), reply_markup=kb.main_menu(user.lang))


@router.message(SupportState.chatting, F.text.func(_is_attach))
async def attach_prompt(message: Message, user: User, db: AsyncSession) -> None:
    orders = await order_service.user_orders(db, user.id, active=True)
    if not orders:
        await message.answer(t(user.lang, "bot.orders_empty"))
        return
    await message.answer(t(user.lang, "bot.support_attach_prompt"), reply_markup=kb.attach_orders_keyboard(user.lang, orders))


@router.callback_query(F.data.startswith("support:attach:"))
async def cb_attach(cq: CallbackQuery, user: User, db: AsyncSession, state: FSMContext) -> None:
    order_id = int(cq.data.rsplit(":", 1)[1])
    await cq.answer()
    if order_id == 0:
        th = await support.get_or_create_thread(db, user)
    else:
        order = await order_service.get_order_for_user(db, order_id, user.id)
        if order is None:
            return
        th = await support.get_or_create_thread(db, user, order_id=order.id)
        await cq.message.answer(t(user.lang, "bot.support_attached", number=esc(order.number)))
    await state.set_state(SupportState.chatting)
    await state.update_data(thread_id=th.id)


async def _download(bot: Bot, file_id: str, size: int | None, suffix: str) -> str | None:
    if size and size > MAX_DL:
        return None
    try:
        tg_file = await bot.get_file(file_id)
        if tg_file.file_size and tg_file.file_size > MAX_DL:
            return None
        buf = io.BytesIO()
        await bot.download(tg_file, destination=buf)
        meta = await media.save_bytes_image(buf.getvalue(), prefix="tg")
        return meta["filename"]
    except Exception:  # noqa: BLE001
        log.exception("download failed")
        return None


@router.message(SupportState.chatting, ~F.text.startswith("/"))
async def on_support_message(message: Message, user: User, db: AsyncSession, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    th = await db.get(SupportThread, data.get("thread_id") or 0) if data.get("thread_id") else None
    if th is None or th.user_id != user.id:
        th = await support.get_or_create_thread(db, user)
        await state.update_data(thread_id=th.id)
    kind, text, file_id, attachment = MessageKind.TEXT, message.text, None, None
    if message.photo:
        kind, file_id, text = MessageKind.PHOTO, message.photo[-1].file_id, message.caption
        attachment = await _download(bot, file_id, message.photo[-1].file_size, ".jpg")
    elif message.video:
        kind, file_id, text = MessageKind.VIDEO, message.video.file_id, message.caption
    elif message.document:
        kind, file_id, text = MessageKind.DOCUMENT, message.document.file_id, message.caption
        suffix = Path(message.document.file_name or "file.bin").suffix.lower()[:8] or ".bin"
        if suffix in (".exe", ".sh", ".bat", ".js", ".html", ".php"):
            suffix = ".bin"
        attachment = await _download(bot, file_id, message.document.file_size, suffix)
        if attachment is None and message.document.file_size and message.document.file_size > MAX_DL:
            await message.answer(t(user.lang, "bot.file_too_large", mb=MAX_DL // (1024 * 1024)))
    elif not message.text:
        return
    await support.add_message(db, th, sender=user, from_staff=False, text=text, kind=kind, attachment=attachment, tg_file_id=file_id)
    await message.answer(t(user.lang, "bot.support_ack", reply=esc(pick(await get_setting(db, "reply_time"), user.lang))))
    preview = (text or f"[{kind}]")[:200]
    order_txt = f"📦 {th.order.number}" if th.order else ""
    await notifications.notify_staff(db, t("uz", "notify.new_support_staff", customer=esc(user.full_name), preview=esc(preview)), kind="new_support")
    # mirror into staff group so staff can reply from Telegram
    if settings.admin_chat_id:
        mirror = t("uz", "bot.support_mirror", id=th.id, customer=esc(user.full_name), country=esc(user.country or "—"), phone=esc(user.phone or "—"), order=order_txt, text=esc(text or f"[{kind}]"))
        try:
            if kind == MessageKind.PHOTO and file_id:
                await bot.send_photo(settings.admin_chat_id, file_id, caption=mirror[:1000])
            elif kind == MessageKind.VIDEO and file_id:
                await bot.send_video(settings.admin_chat_id, file_id, caption=mirror[:1000])
            elif kind == MessageKind.DOCUMENT and file_id:
                await bot.send_document(settings.admin_chat_id, file_id, caption=mirror[:1000])
            else:
                await bot.send_message(settings.admin_chat_id, mirror)
        except Exception:  # noqa: BLE001
            log.exception("mirror to staff group failed")


# ---- staff replies from the admin group: reply to a mirrored "#thread_<id>" message
@router.message(F.chat.type.in_({"group", "supergroup"}), F.reply_to_message)
async def staff_reply(message: Message, user: User | None, db: AsyncSession, bot: Bot) -> None:
    if not settings.admin_chat_id or message.chat.id != settings.admin_chat_id or user is None or not user.is_staff:
        return
    src = message.reply_to_message.text or message.reply_to_message.caption or ""
    marker = "#thread_"
    if marker not in src:
        return
    try:
        thread_id = int(src.split(marker, 1)[1].split()[0].strip("*_:"))
    except (ValueError, IndexError):
        return
    th = (await db.execute(select(SupportThread).where(SupportThread.id == thread_id))).scalar_one_or_none()
    if th is None:
        return
    text = message.text or message.caption
    kind, file_id = MessageKind.TEXT, None
    if message.photo:
        kind, file_id = MessageKind.PHOTO, message.photo[-1].file_id
    elif message.document:
        kind, file_id = MessageKind.DOCUMENT, message.document.file_id
    await support.add_message(db, th, sender=user, from_staff=True, text=text, kind=kind, tg_file_id=file_id)
    customer = th.user
    try:
        if kind == MessageKind.PHOTO and file_id:
            await bot.send_photo(customer.tg_id, file_id, caption=f"💬 {esc(text or '')}"[:1000])
        elif kind == MessageKind.DOCUMENT and file_id:
            await bot.send_document(customer.tg_id, file_id, caption=f"💬 {esc(text or '')}"[:1000])
        else:
            await notifications.notify_support_reply(db, customer, th.id, text or "")
        await message.reply(t(user.lang, "bot.support_staff_reply_ok", id=th.id))
    except Exception:  # noqa: BLE001
        log.exception("staff reply delivery failed")
