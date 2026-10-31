from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import MessageKind, ThreadStatus
from app.models import SupportMessage, SupportThread, User
from app.services import chat_events


async def get_or_create_thread(db: AsyncSession, user: User, order_id: int | None = None) -> SupportThread:
    stmt = select(SupportThread).where(SupportThread.user_id == user.id, SupportThread.status == ThreadStatus.OPEN)
    stmt = stmt.where(SupportThread.order_id == order_id) if order_id else stmt.where(SupportThread.order_id.is_(None))
    th = (await db.execute(stmt.order_by(SupportThread.id.desc()))).scalars().first()
    if th is None:
        th = SupportThread(user_id=user.id, order_id=order_id, last_message_at=datetime.now(UTC))
        db.add(th)
        await db.flush()
    return th


async def add_message(
    db: AsyncSession,
    thread: SupportThread,
    *,
    sender: User | None,
    from_staff: bool,
    text: str | None,
    kind: MessageKind = MessageKind.TEXT,
    attachment: str | None = None,
    tg_file_id: str | None = None,
) -> SupportMessage:
    msg = SupportMessage(
        thread_id=thread.id,
        sender_user_id=sender.id if sender else None,
        from_staff=from_staff,
        kind=kind,
        text=(text or "").strip() or None,
        attachment=attachment,
        tg_file_id=tg_file_id,
    )
    db.add(msg)
    thread.last_message_at = datetime.now(UTC)
    # replying also means the other side's messages have been read
    read_by = ("staff" if thread.unread_for_staff else None) if from_staff else ("customer" if thread.unread_for_customer else None)
    if from_staff:
        thread.unread_for_customer += 1
        thread.unread_for_staff = 0
    else:
        thread.unread_for_staff += 1
        thread.unread_for_customer = 0
        thread.status = ThreadStatus.OPEN
    await db.flush()
    if read_by:
        chat_events.queue(db, {"type": "read", "thread_id": thread.id, "by": read_by})
    chat_events.queue(db, {"type": "msg", "thread_id": thread.id, "id": msg.id, "from_staff": from_staff})
    return msg


def thread_changed(db: AsyncSession, thread: SupportThread) -> None:
    """Status / assignee changed: live inboxes refresh after the commit."""
    chat_events.queue(db, {"type": "thread", "thread_id": thread.id})


async def user_threads(db: AsyncSession, user_id: int) -> list[SupportThread]:
    stmt = select(SupportThread).where(SupportThread.user_id == user_id).order_by(SupportThread.last_message_at.desc().nulls_last())
    return list((await db.execute(stmt)).scalars().unique().all())


async def staff_threads(db: AsyncSession, status: ThreadStatus | None = ThreadStatus.OPEN, limit: int = 100) -> list[SupportThread]:
    stmt = select(SupportThread)
    if status:
        stmt = stmt.where(SupportThread.status == status)
    stmt = stmt.order_by(SupportThread.unread_for_staff.desc(), SupportThread.last_message_at.desc().nulls_last()).limit(limit)
    return list((await db.execute(stmt)).scalars().unique().all())


async def mark_read(db: AsyncSession, thread: SupportThread, *, by_staff: bool) -> None:
    changed = bool(thread.unread_for_staff if by_staff else thread.unread_for_customer)
    if by_staff:
        thread.unread_for_staff = 0
    else:
        thread.unread_for_customer = 0
    await db.flush()
    if changed:  # the other side's ticks turn "read"
        chat_events.queue(db, {"type": "read", "thread_id": thread.id, "by": "staff" if by_staff else "customer"})
