"""Live support-chat events: delivered only after commit, dropped on rollback, routed per thread."""
from app.models import SupportThread
from app.services import chat_events, support
from tests.conftest import make_user


def drain(q) -> list[dict]:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


async def test_message_event_only_after_commit(db):
    u = await make_user(db)
    th = await support.get_or_create_thread(db, u)
    await db.commit()
    mine, staff = chat_events.listen(chat_events.thread_channel(th.id)), chat_events.listen(chat_events.STAFF)
    try:
        msg = await support.add_message(db, th, sender=u, from_staff=False, text="salom")
        assert drain(mine) == []  # not committed yet: a listener fetching now would not find it
        await db.commit()
        got = drain(mine)
        assert got == [{"type": "msg", "thread_id": th.id, "id": msg.id, "from_staff": False}]
        assert drain(staff) == got
    finally:
        chat_events.unlisten(chat_events.thread_channel(th.id), mine)
        chat_events.unlisten(chat_events.STAFF, staff)


async def test_rollback_drops_events(db):
    u = await make_user(db)
    th = await support.get_or_create_thread(db, u)
    await db.commit()
    channel = chat_events.thread_channel(th.id)  # th expires on rollback
    q = chat_events.listen(channel)
    try:
        await support.add_message(db, th, sender=u, from_staff=False, text="bekor")
        await db.rollback()
        await db.commit()
        assert drain(q) == []
    finally:
        chat_events.unlisten(channel, q)


async def test_other_threads_do_not_hear_it(db):
    a, b = await make_user(db, 2001), await make_user(db, 2002)
    ta, tb = await support.get_or_create_thread(db, a), await support.get_or_create_thread(db, b)
    await db.commit()
    qb = chat_events.listen(chat_events.thread_channel(tb.id))
    try:
        await support.add_message(db, ta, sender=a, from_staff=False, text="faqat A")
        await db.commit()
        assert drain(qb) == []
    finally:
        chat_events.unlisten(chat_events.thread_channel(tb.id), qb)


async def test_reply_and_read_events(db):
    u = await make_user(db)
    staff_user = await make_user(db, 3001)
    th = await support.get_or_create_thread(db, u)
    await support.add_message(db, th, sender=u, from_staff=False, text="savol")
    await db.commit()
    q = chat_events.listen(chat_events.thread_channel(th.id))
    try:
        # a staff reply means the customer's message was read: read first, then the new message
        await support.add_message(db, th, sender=staff_user, from_staff=True, text="javob")
        await db.commit()
        types = [(e["type"], e.get("by")) for e in drain(q)]
        assert types == [("read", "staff"), ("msg", None)]
        # the customer opens the chat: the staff reply turns "read"
        await support.mark_read(db, th, by_staff=False)
        await db.commit()
        assert [(e["type"], e["by"]) for e in drain(q)] == [("read", "customer")]
        # nothing unread any more: no event
        await support.mark_read(db, th, by_staff=False)
        await db.commit()
        assert drain(q) == []
        await db.refresh(th)
        assert isinstance(th, SupportThread) and th.unread_for_customer == 0
    finally:
        chat_events.unlisten(chat_events.thread_channel(th.id), q)
