"""Per-update DB session + user injection, and a safety net that keeps the dispatcher alive."""
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from app.db import SessionLocal
from app.services.users import get_or_create_tg_user

log = logging.getLogger("nuhd.bot")


class DbUserMiddleware(BaseMiddleware):
    async def __call__(
        self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: dict[str, Any]
    ) -> Any:
        tg_user = data.get("event_from_user")
        async with SessionLocal() as db:
            data["db"] = db
            data["user"] = None
            if tg_user is not None and not tg_user.is_bot:
                payload = {"id": tg_user.id, "first_name": tg_user.first_name, "last_name": tg_user.last_name, "username": tg_user.username, "language_code": tg_user.language_code}
                data["user"] = await get_or_create_tg_user(db, payload, source=_start_source(event))
            try:
                result = await handler(event, data)
                await db.commit()
                return result
            except Exception:
                await db.rollback()
                raise


def _start_source(event: TelegramObject) -> str | None:
    msg = event.message if isinstance(event, Update) else event if isinstance(event, Message) else None
    if msg and msg.text and msg.text.startswith("/start src_"):
        return msg.text.split(" ", 1)[1].removeprefix("src_")[:64]
    return None


class ErrorMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        try:
            return await handler(event, data)
        except Exception:  # noqa: BLE001
            log.exception("unhandled error in bot handler")
            target = None
            if isinstance(event, Update):
                target = event.message or (event.callback_query.message if event.callback_query else None)
            elif isinstance(event, Message):
                target = event
            elif isinstance(event, CallbackQuery):
                target = event.message
            if target is not None:
                try:
                    await target.answer("⚠️ Error. Please try again later.")
                except Exception:  # noqa: BLE001
                    pass
            return None
