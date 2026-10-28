"""Single aiogram Bot instance shared by handlers, notifications and the web app."""
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import settings

_bot: Bot | None = None


def get_bot() -> Bot | None:
    global _bot
    if not settings.bot_token:
        return None
    if _bot is None:
        _bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    return _bot


async def close_bot() -> None:
    global _bot
    if _bot is not None:
        await _bot.session.close()
        _bot = None
