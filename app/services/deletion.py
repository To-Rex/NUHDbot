"""Deleting from the admin panel.

Each helper removes one record together with what belongs only to it (files in storage, stock it held, ids kept in
JSON lists) and leaves the rest to the foreign keys: ON DELETE CASCADE takes child rows, SET NULL unlinks history
(order lines and auctions keep their own brand / model / price copy). The caller writes the audit entry and commits.
"""
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import AuctionStatus, OrderStatus
from app.models import (
    AdPost,
    Auction,
    AuctionDeposit,
    Banner,
    Bid,
    Order,
    OrderItem,
    Payment,
    Product,
    SupportMessage,
    SupportThread,
    User,
)
from app.services import auctions as auctions_svc
from app.services import chat_events, media

# an order in one of these no longer holds stock: it left the warehouse or the hold was already released
_NOT_HOLDING = (OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.RETURNED)


async def delete_product(db: AsyncSession, p: Product) -> None:
    await media.delete_files(*[n for img in p.images for n in (img.filename, img.thumb)])
    for model in (Banner, AdPost):  # offer banners and ad posts list products in JSON: drop the id there
        for row in (await db.execute(select(model))).scalars().unique().all():
            if p.id in (row.product_ids or []):
                row.product_ids = [x for x in row.product_ids if x != p.id]
    await db.delete(p)
    await db.flush()


async def _release(db: AsyncSession, it: OrderItem, qty: int) -> None:
    if it.product_id and qty:
        await db.execute(update(Product).where(Product.id == it.product_id).values(reserved=func.greatest(Product.reserved - qty, 0)))


async def delete_order(db: AsyncSession, o: Order) -> None:
    if o.status not in _NOT_HOLDING:
        for it in o.items:
            await _release(db, it, it.qty)
    await media.delete_files(*[p.proof_filename for p in o.payments])
    await db.delete(o)
    await db.flush()


async def delete_order_item(db: AsyncSession, o: Order, it: OrderItem) -> None:
    """One line out of an order; the totals follow (the order keeps at least one line — the caller checks)."""
    if o.status not in _NOT_HOLDING:
        await _release(db, it, it.qty)
    o.items.remove(it)
    await db.delete(it)
    o.subtotal = sum((Decimal(i.unit_price) * i.qty for i in o.items), Decimal(0))
    o.total = o.subtotal
    await db.flush()


async def delete_payment(db: AsyncSession, o: Order, pay: Payment) -> None:
    await media.delete_files(pay.proof_filename)
    o.payments.remove(pay)
    await db.delete(pay)
    await db.flush()


async def recompute_auction(db: AsyncSession, a: Auction) -> None:
    """After bids were removed: the price, the count and (once ended) the winner come from the bids that are left."""
    last = (await db.execute(select(Bid).where(Bid.auction_id == a.id).order_by(Bid.id.desc()).limit(1))).scalar_one_or_none()
    a.bids_count = (await db.execute(select(func.count()).select_from(Bid).where(Bid.auction_id == a.id))).scalar_one()
    a.current_price_total = last.amount_total if last else a.start_price_total
    if a.status == AuctionStatus.ENDED:
        a.winner_user_id, a.winner_bid_id = (last.user_id, last.id) if last else (None, None)
    a.version += 1
    await db.flush()


def announce_auction(a: Auction) -> None:
    """Tell open lot pages (call after the commit)."""
    auctions_svc.publish(a.id, {"type": "state", **auctions_svc.snapshot(a)})


async def delete_bid(db: AsyncSession, a: Auction, bid: Bid) -> None:
    await db.delete(bid)
    await db.flush()
    await recompute_auction(db, a)


async def delete_auction(db: AsyncSession, a: Auction) -> None:
    await media.delete_files(*[n for img in a.images for n in (img.filename, img.thumb)])
    await media.delete_files(*(await db.execute(select(AuctionDeposit.proof_filename).where(AuctionDeposit.auction_id == a.id))).scalars().all())
    await db.delete(a)
    await db.flush()


async def delete_thread(db: AsyncSession, th: SupportThread) -> None:
    await media.delete_files(*[m.attachment for m in th.messages])
    chat_events.queue(db, {"type": "thread", "thread_id": th.id})
    await db.delete(th)
    await db.flush()


async def delete_message(db: AsyncSession, th: SupportThread, m: SupportMessage) -> None:
    """One bubble out of a chat; unread counters and the thread's last activity follow, open chats drop it live."""
    same_side = [x.id for x in th.messages if x.from_staff == m.from_staff]
    if m.from_staff and m.id in same_side[len(same_side) - th.unread_for_customer:]:
        th.unread_for_customer = max(th.unread_for_customer - 1, 0)
    if not m.from_staff and m.id in same_side[len(same_side) - th.unread_for_staff:]:
        th.unread_for_staff = max(th.unread_for_staff - 1, 0)
    await media.delete_files(m.attachment)
    th.messages.remove(m)
    await db.delete(m)
    th.last_message_at = max((x.created_at for x in th.messages), default=None)
    chat_events.queue(db, {"type": "del", "thread_id": th.id, "id": m.id})
    await db.flush()


async def delete_customer(db: AsyncSession, u: User) -> list[Auction]:
    """A customer and everything that is only theirs: orders (stock released), payments, bids, deposits, the chat.
    Returns the auctions whose bids changed, to announce after the commit."""
    for o in (await db.execute(select(Order).where(Order.user_id == u.id))).scalars().unique().all():
        await delete_order(db, o)
    for pay in (await db.execute(select(Payment).where(Payment.user_id == u.id))).scalars().all():
        await media.delete_files(pay.proof_filename)
        await db.delete(pay)
    for dep in (await db.execute(select(AuctionDeposit).where(AuctionDeposit.user_id == u.id))).scalars().all():
        await media.delete_files(dep.proof_filename)
        await db.delete(dep)
    touched = list((await db.execute(select(Auction).where(Auction.id.in_(select(Bid.auction_id).where(Bid.user_id == u.id))))).scalars().unique().all())
    for bid in (await db.execute(select(Bid).where(Bid.user_id == u.id))).scalars().all():
        await db.delete(bid)
    await db.flush()
    for a in touched:
        await recompute_auction(db, a)
    for th in (await db.execute(select(SupportThread).where(SupportThread.user_id == u.id))).scalars().unique().all():
        await delete_thread(db, th)
    await db.delete(u)
    await db.flush()
    return touched
