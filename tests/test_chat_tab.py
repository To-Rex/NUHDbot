"""The Chat tab: it opens the customer's general conversation with the admin, and its badge counts unseen admin replies."""
from app.enums import ThreadStatus
from app.services import support
from tests.conftest import make_user


async def test_one_conversation_per_customer(db):
    """A customer talks to the admin in one conversation: an order question, a closed chat or a second "first" message
    all continue it; the badge counts unseen admin replies."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    from app.models import SupportThread
    from tests.conftest import make_product

    u, other = await make_user(db, 2001), await make_user(db, 2002)
    assert await support.user_thread(db, u.id) is None  # before the first message the tab is empty
    th = await support.get_or_create_thread(db, u)
    await support.add_message(db, th, sender=None, from_staff=True, text="Salom!")
    await support.add_message(db, th, sender=None, from_staff=True, text="Qanday yordam kerak?")
    assert await support.unread_total(db, u.id) == 2 and await support.unread_total(db, other.id) == 0
    await support.mark_read(db, th, by_staff=False)
    assert await support.unread_total(db, u.id) == 0
    # a closed conversation continues: the customer's message reopens it
    th.status = ThreadStatus.CLOSED
    await db.flush()
    again = await support.get_or_create_thread(db, u)
    assert again.id == th.id
    await support.add_message(db, again, sender=u, from_staff=False, text="Rahmat")
    assert th.status == ThreadStatus.OPEN
    # an order question is the same conversation, now marked with that order
    p = await make_product(db)
    from app.enums import OrderStatus
    from app.models import Order
    o = Order(number="NU-T-1", user_id=u.id, status=OrderStatus.AWAITING_ADVANCE, currency="USD", subtotal=p.price, total=p.price)
    db.add(o)
    await db.flush()
    about = await support.get_or_create_thread(db, u, order_id=o.id)
    assert about.id == th.id and about.order_id == o.id
    # the database itself refuses a second conversation
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(SupportThread(user_id=u.id))
            await db.flush()


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
