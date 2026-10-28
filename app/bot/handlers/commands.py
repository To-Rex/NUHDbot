from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.i18n import pick, t
from app.models import User
from app.services import orders as order_service
from app.services.notifications import esc
from app.services.settings_service import get_setting
from app.templating import money

router = Router(name="commands")


@router.message(Command("catalog"))
async def cmd_catalog(message: Message, user: User) -> None:
    await message.answer(t(user.lang, "bot.btn_catalog"), reply_markup=kb.main_menu(user.lang))


@router.message(Command("auction"))
async def cmd_auction(message: Message, user: User) -> None:
    await message.answer(t(user.lang, "bot.btn_auction"), reply_markup=kb.main_menu(user.lang))


@router.message(Command("orders"))
async def cmd_orders(message: Message, user: User, db: AsyncSession) -> None:
    orders = await order_service.user_orders(db, user.id, active=True)
    if not orders:
        await message.answer(t(user.lang, "bot.orders_empty"), reply_markup=kb.main_menu(user.lang))
        return
    await message.answer(t(user.lang, "bot.orders_title"))
    for o in orders[:10]:
        await message.answer(
            t(user.lang, "bot.order_line", number=esc(o.number), qty=o.total_qty, total=money(o.total, o.currency), status=esc(t(user.lang, f"order_status.{o.status}"))),
            reply_markup=kb.order_button(user.lang, o.id),
        )


@router.message(Command("help"))
async def cmd_help(message: Message, user: User, db: AsyncSession) -> None:
    lang = user.lang
    await message.answer(
        t(lang, "bot.help",
          payment=esc(pick(await get_setting(db, "payment_text"), lang)),
          delivery=esc(pick(await get_setting(db, "delivery_text"), lang)),
          hours=esc(pick(await get_setting(db, "working_hours"), lang))),
        reply_markup=kb.menu_button(lang),
    )
