"""Auction logic: atomic bids with row locks, anti-sniping extension, lifecycle ticks, SSE fan-out."""
import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.enums import AuctionStatus, DepositStatus
from app.models import Auction, AuctionDeposit, Bid, User
from app.services import audit


class AuctionError(Exception):
    def __init__(self, code: str, **ctx):
        super().__init__(code)
        self.code = code
        self.ctx = ctx


# ---- in-process pub/sub for SSE (single worker). For multi-worker deploys swap for Redis pub/sub.
_subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)


def subscribe(auction_id: int) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _subscribers[auction_id].add(q)
    return q


def unsubscribe(auction_id: int, q: asyncio.Queue) -> None:
    _subscribers[auction_id].discard(q)


def publish(auction_id: int, event: dict) -> None:
    for q in list(_subscribers.get(auction_id, ())):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


def snapshot(a: Auction) -> dict:
    return {
        "id": a.id,
        "status": a.status,
        "current_total": str(Decimal(a.current_price_total).quantize(Decimal("0.01"))),
        "current_unit": str(a.current_price_unit),
        "next_total": str(a.next_bid_total.quantize(Decimal("0.01"))),
        "bids": a.bids_count,
        "ends_at": a.ends_at.astimezone(UTC).isoformat(),
        "version": a.version,
        "currency": a.currency,
    }


async def list_auctions(db: AsyncSession, statuses: tuple[AuctionStatus, ...] | None = None, limit: int = 50) -> list[Auction]:
    stmt = select(Auction)
    if statuses:
        stmt = stmt.where(Auction.status.in_(statuses))
    else:
        stmt = stmt.where(Auction.status != AuctionStatus.DRAFT)
    stmt = stmt.order_by(
        (Auction.status == AuctionStatus.LIVE).desc(), (Auction.status == AuctionStatus.SCHEDULED).desc(), Auction.ends_at.desc()
    ).limit(limit)
    return list((await db.execute(stmt)).scalars().unique().all())


async def get_auction(db: AsyncSession, auction_id: int) -> Auction | None:
    return await db.get(Auction, auction_id)


async def recent_bids(db: AsyncSession, auction_id: int, limit: int = 20) -> list[Bid]:
    stmt = select(Bid).where(Bid.auction_id == auction_id).order_by(Bid.id.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def user_deposit(db: AsyncSession, auction_id: int, user_id: int) -> AuctionDeposit | None:
    stmt = select(AuctionDeposit).where(AuctionDeposit.auction_id == auction_id, AuctionDeposit.user_id == user_id).order_by(AuctionDeposit.id.desc())
    return (await db.execute(stmt)).scalars().first()


async def place_bid(db: AsyncSession, auction_id: int, user: User, amount_total: Decimal | None = None) -> tuple[Auction, Bid, User | None]:
    """Atomically place a bid. Returns (auction, bid, previous_leader). Caller commits."""
    if not user.is_registered:
        raise AuctionError("not_registered")
    # lock the auction row so concurrent bids serialize
    a = (await db.execute(select(Auction).where(Auction.id == auction_id).with_for_update(of=Auction))).scalar_one_or_none()
    if a is None:
        raise AuctionError("not_found")
    now = datetime.now(UTC)
    if a.status == AuctionStatus.SCHEDULED and a.starts_at <= now:
        a.status = AuctionStatus.LIVE
    if a.status != AuctionStatus.LIVE or a.ends_at <= now:
        raise AuctionError("not_live")
    if a.require_deposit and Decimal(a.deposit_amount or 0) > 0:
        dep = await user_deposit(db, a.id, user.id)
        if dep is None or dep.status not in (DepositStatus.CONFIRMED, DepositStatus.APPLIED):
            raise AuctionError("deposit_required", amount=str(a.deposit_amount), currency=a.currency)
    minimum = a.next_bid_total
    amount = Decimal(amount_total) if amount_total is not None else minimum
    if amount < minimum:
        raise AuctionError("bid_too_low", minimum=str(minimum))
    # must be a whole number of steps above current (keeps unit price clean)
    if a.bids_count > 0 and (amount - Decimal(a.current_price_total)) % a.step_total != 0:
        raise AuctionError("bid_step", step=str(a.step_total))
    last = (await db.execute(select(Bid).where(Bid.auction_id == a.id).order_by(Bid.id.desc()).limit(1))).scalar_one_or_none()
    prev_leader = last.user if last else None
    if last and last.user_id == user.id:
        raise AuctionError("already_leading")
    bid = Bid(auction_id=a.id, user_id=user.id, amount_total=amount)
    db.add(bid)
    a.current_price_total = amount
    a.bids_count += 1
    a.version += 1
    # anti-sniping: a bid in the last N seconds extends the end by N seconds
    window = timedelta(seconds=settings.auction_extension_window_seconds)
    if a.ends_at - now <= window:
        a.ends_at = now + timedelta(seconds=settings.auction_extension_seconds)
    await db.flush()
    await audit.log(db, user.id, "auction.bid", "auction", a.id, None, {"amount": str(amount), "bid_id": bid.id})
    return a, bid, prev_leader


async def participants(db: AsyncSession, auction_id: int) -> list[User]:
    stmt = select(User).join(Bid, Bid.user_id == User.id).where(Bid.auction_id == auction_id).distinct()
    return list((await db.execute(stmt)).scalars().all())


async def tick(db: AsyncSession) -> list[Auction]:
    """Start scheduled auctions and close finished ones. Returns auctions that just ended."""
    now = datetime.now(UTC)
    await db.execute(
        update(Auction)
        .where(Auction.status == AuctionStatus.SCHEDULED, Auction.starts_at <= now)
        .values(status=AuctionStatus.LIVE, version=Auction.version + 1)
    )
    ended_rows = (
        await db.execute(select(Auction).where(Auction.status == AuctionStatus.LIVE, Auction.ends_at <= now).with_for_update(of=Auction, skip_locked=True))
    ).scalars().unique().all()
    ended: list[Auction] = []
    for a in ended_rows:
        last = (await db.execute(select(Bid).where(Bid.auction_id == a.id).order_by(Bid.id.desc()).limit(1))).scalar_one_or_none()
        a.status = AuctionStatus.ENDED
        a.version += 1
        if last:
            a.winner_user_id = last.user_id
            a.winner_bid_id = last.id
        ended.append(a)
    await db.flush()
    for a in ended:
        publish(a.id, {"type": "ended", **snapshot(a)})
    return ended


async def claim_deposit(db: AsyncSession, a: Auction, user: User, proof: str | None, note: str | None) -> AuctionDeposit:
    dep = AuctionDeposit(auction_id=a.id, user_id=user.id, amount=a.deposit_amount, currency=a.currency, proof_filename=proof, note=note)
    db.add(dep)
    await db.flush()
    return dep
