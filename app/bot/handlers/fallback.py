from aiogram import F, Router
from aiogram.types import Message

from app.bot import keyboards as kb
from app.i18n import t
from app.models import User

router = Router(name="fallback")


@router.message(F.chat.type == "private")
async def unknown(message: Message, user: User) -> None:
    await message.answer(t(user.lang, "bot.unknown"), reply_markup=kb.main_menu(user.lang))
