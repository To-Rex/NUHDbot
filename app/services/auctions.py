"""Auction logic: atomic bids with row locks, anti-sniping extension, lifecycle ticks, SSE fan-out."""
import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.enums import AuctionStatus, DepositStatus
from app.models import Auction, AuctionDeposit, Bid, User
from app.services import admin_events, auction_terms, audit, pubsub


class AuctionError(Exception):
    def __init__(self, code: str, **ctx):
        super().__init__(code)
        self.code = code
        self.ctx = ctx


# ---- pub/sub for the SSE streams: in-memory queues per process, carried to the other processes over Postgres NOTIFY
ALL = 0  # the channel every lot's events also go to (the auctions page listens there)
_subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)


def subscribe(auction_id: int = ALL) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _subscribers[auction_id].add(q)
    return q


def unsubscribe(auction_id: int, q: asyncio.Queue) -> None:
    _subscribers[auction_id].discard(q)


def _deliver(auction_id: int, event: dict) -> None:
    for key in {auction_id, ALL}:
        for q in list(_subscribers.get(key, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # a stuck client; it catches up from its own polling
                pass
    admin_events.deliver_local({**{k: v for k, v in event.items() if k != "type"}, "type": "auction", "kind": event.get("type", "state")})  # the admin panel's own stream hears every lot too


def publish(auction_id: int, event: dict) -> None:
    """A lot changed (bid, start, end): every open stream in this process hears it now, the other processes right after."""
    _deliver(auction_id, event)
    pubsub.notify("auction", {"id": auction_id, "event": event})


pubsub.register("auction", lambda p: _deliver(int(p["id"]), p["event"]))


def snapshot(a: Auction) -> dict:
    return {
        "id": a.id,
        "status": a.status.value,
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


async def participant_counts(db: AsyncSession, auction_ids: list[int]) -> dict[int, int]:
    """How many people have bid on each lot (no names: just the number)."""
    if not auction_ids:
        return {}
    rows = (await db.execute(select(Bid.auction_id, func.count(func.distinct(Bid.user_id))).where(Bid.auction_id.in_(auction_ids)).group_by(Bid.auction_id))).all()
    return dict(rows)


async def bidder_numbers(db: AsyncSession, auction_id: int) -> dict[int, int]:
    """Customers never see each other's names: each bidder is "Participant №N", N = the order of their first bid here."""
    rows = (await db.execute(select(Bid.user_id, func.min(Bid.id).label("first")).where(Bid.auction_id == auction_id).group_by(Bid.user_id).order_by("first"))).all()
    return {uid: n for n, (uid, _) in enumerate(rows, start=1)}


async def best_bid(db: AsyncSession, auction_id: int, user_id: int):
    return (await db.execute(select(func.max(Bid.amount_total)).where(Bid.auction_id == auction_id, Bid.user_id == user_id))).scalar_one()


async def user_deposit(db: AsyncSession, auction_id: int, user_id: int) -> AuctionDeposit | None:
    stmt = select(AuctionDeposit).where(AuctionDeposit.auction_id == auction_id, AuctionDeposit.user_id == user_id).order_by(AuctionDeposit.id.desc())
    return (await db.execute(stmt)).scalars().first()


async def place_bid(db: AsyncSession, auction_id: int, user: User, amount_total: Decimal | None = None) -> tuple[Auction, Bid, User | None]:
    """Atomically place a bid. Returns (auction, bid, previous_leader). Caller commits."""
    if not user.is_registered:
        raise AuctionError("not_registered")
    if not await auction_terms.is_accepted(db, user):  # joining a lot means having read and accepted the auction terms
        raise AuctionError("terms")
    # lock the auction row so concurrent bids serialize
    a = (await db.execute(select(Auction).where(Auction.id == auction_id).with_for_update(of=Auction))).scalar_one_or_none()
    if a is None:
        raise AuctionError("not_found")
    now = datetime.now(UTC)
    if a.status == AuctionStatus.SCHEDULED and a.starts_at <= now:
        a.status = AuctionStatus.LIVE
    if a.status != AuctionStatus.LIVE or a.ends_at <= now:
        raise AuctionError("not_live")
    if needs_deposit(a):
        dep = await user_deposit(db, a.id, user.id)
        if not deposit_ok(dep):
            raise AuctionError("deposit_pending" if dep is not None and dep.status == DepositStatus.PENDING else "deposit_required", amount=str(a.deposit_amount), currency=a.currency)
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


# ---- deposits: a share of the start price, paid by QR, the receipt checked by a staff member before the first bid

def deposit_for(start_total, percent) -> Decimal:
    """The deposit a lot asks for: `percent` of its start price, to the cent."""
    return (Decimal(start_total or 0) * Decimal(percent or 0) / 100).quantize(Decimal("0.01"))


def pct_label(percent) -> str:
    """10.00 → "10", 12.50 → "12.5"; nothing for lots with a fixed amount."""
    if percent is None or Decimal(percent) <= 0:
        return ""
    return format(Decimal(percent).quantize(Decimal("0.01")).normalize(), "f")


def needs_deposit(a: Auction) -> bool:
    return bool(a.require_deposit) and Decimal(a.deposit_amount or 0) > 0


def deposit_ok(dep: AuctionDeposit | None) -> bool:
    return dep is not None and dep.status in (DepositStatus.CONFIRMED, DepositStatus.APPLIED)


async def claim_deposit(db: AsyncSession, a: Auction, user: User, proof: str | None, note: str | None, method_id: int | None = None) -> AuctionDeposit:
    """The customer paid by QR and sends the receipt: a pending deposit for the staff to check. One open deposit per lot and
    customer; after a rejection a new one may be sent."""
    if not await auction_terms.is_accepted(db, user):  # the deposit is the first step of joining: the terms come before it
        raise AuctionError("terms")
    if a.status not in (AuctionStatus.LIVE, AuctionStatus.SCHEDULED):
        raise AuctionError("not_live")
    if not proof:
        raise AuctionError("proof_required")
    cur = await user_deposit(db, a.id, user.id)
    if cur is not None and cur.open:
        raise AuctionError("deposit_exists")
    dep = AuctionDeposit(auction_id=a.id, user_id=user.id, amount=a.deposit_amount, currency=a.currency, proof_filename=proof, note=note, method_id=method_id)
    db.add(dep)
    await db.flush()
    admin_events.queue(db, "deposit_new", auction_id=a.id, deposit_id=dep.id, name=user.full_name, amount=str(dep.amount), currency=dep.currency)
    return dep


REVIEW = {"confirm": DepositStatus.CONFIRMED, "reject": DepositStatus.REJECTED, "refund": DepositStatus.REFUNDED, "apply": DepositStatus.APPLIED}


async def review_deposit(db: AsyncSession, dep: AuctionDeposit, staff: User, action: str, note: str | None = None) -> DepositStatus:
    """A staff member's verdict on a deposit. Returns the status it had before. Caller commits, then `announce_deposit`."""
    if action not in REVIEW:
        raise AuctionError("bad_action")
    before = dep.status
    dep.status = REVIEW[action]
    dep.confirmed_by = staff.id
    dep.reviewed_at = datetime.now(UTC)
    if action == "reject" or note:
        dep.admin_note = (note or "").strip()[:500] or None
    await db.flush()
    await audit.log(db, staff.id, f"deposit.{action}", "deposit", dep.id, {"status": before}, {"status": dep.status, "user": dep.user_id, "amount": str(dep.amount), "note": dep.admin_note})
    return before


def announce_deposit(dep: AuctionDeposit) -> None:
    """The lot's open pages hear it: the customer's page swaps its deposit card, the admin lot page refreshes its table."""
    publish(dep.auction_id, {"type": "deposit", "id": dep.auction_id, "dep": dep.id, "status": dep.status.value})


async def pending_deposits(db: AsyncSession, limit: int = 200) -> list[AuctionDeposit]:
    stmt = select(AuctionDeposit).where(AuctionDeposit.status == DepositStatus.PENDING).order_by(AuctionDeposit.id).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def pending_deposits_count(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(AuctionDeposit).where(AuctionDeposit.status == DepositStatus.PENDING))).scalar_one()
