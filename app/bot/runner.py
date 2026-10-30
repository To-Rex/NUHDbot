"""Dispatcher wiring and startup (polling or webhook) — called from app.main lifespan."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault, MenuButtonWebApp, Update, WebAppInfo
from fastapi import FastAPI, Header, HTTPException, Request

from app.bot.instance import get_bot
from app.bot.middlewares import DbUserMiddleware, ErrorMiddleware
from app.config import settings
from app.i18n import t

log = logging.getLogger("nuhd.bot")
_dp: Dispatcher | None = None


def setup_dispatcher() -> Dispatcher:
    from app.bot.handlers import commands, fallback, start, support

    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(ErrorMiddleware())
    dp.update.outer_middleware(DbUserMiddleware())
    dp.include_router(start.router)
    dp.include_router(support.router)
    dp.include_router(commands.router)
    dp.include_router(fallback.router)
    return dp


def get_dispatcher() -> Dispatcher:
    global _dp
    if _dp is None:
        _dp = setup_dispatcher()
    return _dp


async def configure_bot(bot: Bot) -> None:
    # Telegram accepts only two-letter language codes here: default (no code) = Uzbek Cyrillic; uzl shares it.
    for lang in [code for code in settings.langs if len(code) == 2]:
        cmds = [BotCommand(command=c, description=t(lang, f"bot.cmd_{c}")[:256]) for c in ("start", "catalog", "orders", "auction", "help", "language")]
        try:
            await bot.set_my_commands(cmds, scope=BotCommandScopeDefault(), language_code=None if lang == settings.default_lang else lang)
        except Exception:  # noqa: BLE001
            log.exception("set_my_commands failed for %s", lang)
    if settings.base_url.startswith("https://"):
        try:
            await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="HDD Shop", web_app=WebAppInfo(url=settings.base_url.rstrip("/") + "/app")))
        except Exception:  # noqa: BLE001
            log.exception("set_chat_menu_button failed")


async def start_bot(app: FastAPI) -> asyncio.Task | None:
    bot = get_bot()
    if bot is None or settings.bot_mode == "off":
        return None
    dp = get_dispatcher()
    await configure_bot(bot)
    if settings.bot_mode == "webhook":
        url = settings.base_url.rstrip("/") + "/tg/webhook"
        await bot.set_webhook(url, secret_token=settings.webhook_secret, drop_pending_updates=False, allowed_updates=dp.resolve_used_update_types())

        @app.post("/tg/webhook", include_in_schema=False)
        async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
            if x_telegram_bot_api_secret_token != settings.webhook_secret:
                raise HTTPException(403)
            update = Update.model_validate(await request.json(), context={"bot": bot})
            await dp.feed_update(bot, update)
            return {"ok": True}

        log.info("bot webhook set: %s", url)
        return None
    await bot.delete_webhook(drop_pending_updates=False)
    log.info("bot polling started as @%s", settings.bot_username)
    return asyncio.create_task(dp.start_polling(bot, handle_signals=False, allowed_updates=dp.resolve_used_update_types()))
