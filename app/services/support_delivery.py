"""Telegram copies of an admin reply go out only if the customer has not seen it in the Mini App chat meanwhile.

The reply is live in the chat at once; its bot notification waits a few seconds (setting `chat_notify_delay`).
If by then the open chat has shown it (the page marks admin replies read only while it is on screen), the bot
stays quiet; otherwise the copies go out as before. The check reads the database, so it holds with several
server processes; a restart during the wait drops that one notification.
"""
import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_scope
from app.models import SupportThread
from app.services.settings_service import get_setting

log = logging.getLogger("nuhd.support")

DELAY_DEFAULT, DELAY_MAX = 10, 120
Deliver = Callable[[AsyncSession, SupportThread], Awaitable[None]]
_tasks: set[asyncio.Task] = set()  # running waits (a reference keeps them from being collected)
_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)  # one thread's copies go out in order


def is_unseen(th: SupportThread, message_id: int) -> bool:
    """The admin message is among the customer's `unread_for_customer` latest admin messages (the chat's own rule for ticks)."""
    if not th.unread_for_customer:
        return False
    staff_ids = [m.id for m in th.messages if m.from_staff]
    return message_id in staff_ids[-th.unread_for_customer:]


def clean_delay(value) -> int:
    try:
        return max(0, min(DELAY_MAX, int(value)))
    except (TypeError, ValueError):
        return DELAY_DEFAULT


def schedule(thread_id: int, message_id: int, deliver: Deliver) -> None:
    """After the wait, `deliver(db, thread)` sends the Telegram copies — unless the customer has seen the message."""
    task = asyncio.create_task(_run(thread_id, message_id, deliver))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _run(thread_id: int, message_id: int, deliver: Deliver) -> None:
    try:
        async with session_scope() as db:
            delay = clean_delay(await get_setting(db, "chat_notify_delay", DELAY_DEFAULT))
        await asyncio.sleep(delay)
        async with _locks[thread_id], session_scope() as db:
            th = await db.get(SupportThread, thread_id)
            if th is None or not is_unseen(th, message_id):
                return  # seen in the open chat (or gone): no bot message
            await deliver(db, th)
    except Exception:  # noqa: BLE001
        log.exception("support reply delivery failed thread=%s message=%s", thread_id, message_id)
