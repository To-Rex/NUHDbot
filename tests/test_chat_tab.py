"""The Chat tab: it opens the customer's general conversation with the admin, and its badge counts unseen admin replies."""
from app.enums import ThreadStatus
from app.services import support
from tests.conftest import make_user


async def test_general_thread_and_unread_badge(db):
    u, other = await make_user(db, 2001), await make_user(db, 2002)
    assert await support.general_thread(db, u.id) is None  # before the first message the tab shows a greeting
    assert await support.unread_total(db, u.id) == 0
    th = await support.get_or_create_thread(db, u)
    await support.add_message(db, th, sender=None, from_staff=True, text="Salom!")
    await support.add_message(db, th, sender=None, from_staff=True, text="Qanday yordam kerak?")
    assert (await support.general_thread(db, u.id)).id == th.id
    assert await support.unread_total(db, u.id) == 2 and await support.unread_total(db, other.id) == 0
    await support.mark_read(db, th, by_staff=False)
    assert await support.unread_total(db, u.id) == 0
    # a closed conversation still opens in the tab; the customer's reply reopens it
    th.status = ThreadStatus.CLOSED
    await db.flush()
    assert (await support.general_thread(db, u.id)).id == th.id
    await support.add_message(db, th, sender=u, from_staff=False, text="Rahmat")
    assert th.status == ThreadStatus.OPEN


async def test_bot_copy_only_for_unseen_replies(db):
    """An admin reply goes to the bot only if the customer has not seen it in the open chat (support_delivery)."""
    from app.services import support_delivery as sd

    u = await make_user(db, 2003)
    th = await support.get_or_create_thread(db, u)
    first = await support.add_message(db, th, sender=None, from_staff=True, text="1")
    second = await support.add_message(db, th, sender=None, from_staff=True, text="2")
    await db.refresh(th, ["messages"])
    assert sd.is_unseen(th, first.id) and sd.is_unseen(th, second.id)  # chat closed: both go to the bot
    await support.mark_read(db, th, by_staff=False)  # the open chat showed them
    assert not sd.is_unseen(th, first.id) and not sd.is_unseen(th, second.id)
    third = await support.add_message(db, th, sender=None, from_staff=True, text="3")  # seen two, not this one
    await db.refresh(th, ["messages"])
    assert not sd.is_unseen(th, second.id) and sd.is_unseen(th, third.id)
    assert [sd.clean_delay(v) for v in (None, "x", -5, 7, 999)] == [10, 10, 0, 7, 120]
