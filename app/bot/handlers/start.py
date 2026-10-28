from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.config import settings
from app.i18n import normalize_lang, t
from app.models import Order, User
from app.services.notifications import esc
from app.services.users import set_phone_from_contact

router = Router(name="start")


async def send_menu(message: Message, user: User, *, first_time: bool = False) -> None:
    lang = user.lang
    text = t(lang, "bot.welcome" if first_time else "bot.welcome_back", name=esc(user.first_name or user.full_name))
    if not kb.is_https():
        text += "\n\n" + t(lang, "bot.miniapp_https_only", url=esc(settings.base_url))
    need_phone = not user.phone
    await message.answer(text, reply_markup=kb.reply_main(lang, need_phone=need_phone))
    await message.answer(t(lang, "bot.btn_menu"), reply_markup=kb.main_menu(lang))
    if need_phone:
        await message.answer(t(lang, "bot.phone_prompt"))


@router.message(CommandStart(deep_link=True))
@router.message(CommandStart())
async def cmd_start(message: Message, user: User, db: AsyncSession, state: FSMContext, command: CommandObject | None = None) -> None:
    await state.clear()
    payload = (command.args if command else "") or ""
    if payload.startswith("order_"):
        try:
            order = await db.get(Order, int(payload.removeprefix("order_")))
        except ValueError:
            order = None
        if order and order.user_id == user.id:
            await message.answer(
                t(user.lang, "bot.deep_order", number=esc(order.number), status=esc(t(user.lang, f"order_status.{order.status}"))),
                reply_markup=kb.order_button(user.lang, order.id),
            )
    first_time = user.created_at is not None and (datetime.now(UTC) - user.created_at).total_seconds() < 15
    if first_time and not payload:
        await message.answer(t(user.lang, "bot.choose_lang"), reply_markup=kb.lang_keyboard())
        return
    await send_menu(message, user, first_time=first_time)


@router.message(Command("language"))
async def cmd_language(message: Message, user: User) -> None:
    await message.answer(t(user.lang, "bot.choose_lang"), reply_markup=kb.lang_keyboard())


@router.callback_query(F.data == "lang:menu")
async def cb_lang_menu(cq: CallbackQuery, user: User) -> None:
    await cq.message.answer(t(user.lang, "bot.choose_lang"), reply_markup=kb.lang_keyboard())
    await cq.answer()


@router.callback_query(F.data.startswith("lang:"))
async def cb_lang(cq: CallbackQuery, user: User, db: AsyncSession) -> None:
    code = normalize_lang(cq.data.split(":", 1)[1])
    user.lang = code
    await db.flush()
    await cq.answer()
    try:
        await cq.message.edit_text(t(code, "bot.lang_set"))
    except Exception:  # noqa: BLE001
        await cq.message.answer(t(code, "bot.lang_set"))
    await send_menu(cq.message, user, first_time=user.registered_at is None)


@router.callback_query(F.data == "menu")
async def cb_menu(cq: CallbackQuery, user: User, state: FSMContext) -> None:
    await state.clear()
    await cq.answer()
    await send_menu(cq.message, user)


@router.message(F.contact)
async def on_contact(message: Message, user: User, db: AsyncSession) -> None:
    c = message.contact
    if c.user_id != message.from_user.id:
        await message.answer(t(user.lang, "bot.contact_not_yours"))
        return
    await set_phone_from_contact(db, user, c.phone_number)
    await message.answer(t(user.lang, "bot.phone_saved", phone=esc(user.phone)), reply_markup=kb.reply_main(user.lang, need_phone=False))
    await message.answer(t(user.lang, "bot.btn_menu"), reply_markup=kb.main_menu(user.lang))
