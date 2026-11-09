"""The bot added to (or removed from) a group or channel: the chat goes into the ad posts' address book by itself."""
import logging

from aiogram import Router
from aiogram.types import ChatMemberUpdated
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import ads

log = logging.getLogger("nuhd.bot")
router = Router(name="chats")
IN = ("member", "administrator", "creator", "restricted")


@router.my_chat_member()
async def bot_membership(event: ChatMemberUpdated, db: AsyncSession) -> None:
    chat = event.chat
    if chat.type not in ("group", "supergroup", "channel"):
        return
    new = event.new_chat_member
    if new.status in IN:
        can_post = new.status in ("administrator", "creator") and bool(getattr(new, "can_post_messages", True)) if chat.type == "channel" else True
        await ads.upsert_target(db, {"id": chat.id, "title": chat.title or "", "type": chat.type, "username": chat.username, "can_post": can_post, "left": False})
        log.info("ad target %s (%s) %s", chat.id, chat.title, new.status)
    else:
        await ads.mark_left(db, chat.id, True)
