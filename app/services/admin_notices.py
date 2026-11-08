"""The admin panel's kept notices: the bell in the top bar.

The live channel (app.services.admin_events) shows what happens as a toast while a page is open; the kinds listed in STORED
are also written down here when the event is queued (same transaction, so a rollback drops both), and stay in the bell's
list. Each staff member has their own "seen" mark (users.notices_seen_at): what came after it counts as new. Which kinds a
staff member sees follows the live channel's role map (app.admin.common.LIVE_VISIBLE); the callers pass the kinds.
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdminNotice, User

STORED = {"order_new", "payment_new", "deposit_new", "auction_join", "customer_new"}
KEEP_DAYS = 60  # older notices go when a new one is written
ICONS = {"order_new": "package", "payment_new": "money", "deposit_new": "qr", "auction_join": "gavel", "customer_new": "user"}


def href_for(kind: str, data: dict) -> str:
    """Where a click on the notice goes."""
    if kind in ("order_new", "payment_new"):
        return f"/admin/orders/{data.get('id')}" + ("#payments" if kind == "payment_new" else "")
    if kind == "deposit_new":
        return "/admin/auctions/deposits"
    if kind == "auction_join":
        return f"/admin/auctions/{data['auction_id']}" if data.get("auction_id") else f"/admin/customers/{data.get('user_id')}"
    if kind == "customer_new":
        return f"/admin/customers/{data.get('id')}"
    return "/admin"


def record(db: AsyncSession, kind: str, data: dict) -> AdminNotice | None:
    """Write the notice down (flushed with the caller's transaction). Only the kinds in STORED are kept."""
    if kind not in STORED:
        return None
    n = AdminNotice(kind=kind, data={k: v for k, v in data.items() if v is not None}, href=href_for(kind, data)[:200])
    db.add(n)
    return n


async def prune(db: AsyncSession, keep_days: int = KEEP_DAYS) -> int:
    res = await db.execute(delete(AdminNotice).where(AdminNotice.created_at < datetime.now(UTC) - timedelta(days=keep_days)))
    return res.rowcount or 0


def _visible(stmt, kinds: set[str]):
    return stmt.where(AdminNotice.kind.in_(sorted(kinds))) if kinds else stmt.where(False)


async def unread_count(db: AsyncSession, staff: User, kinds: set[str]) -> int:
    stmt = _visible(select(func.count()).select_from(AdminNotice), kinds)
    if staff.notices_seen_at:
        stmt = stmt.where(AdminNotice.created_at > staff.notices_seen_at)
    return (await db.execute(stmt)).scalar_one()


async def recent(db: AsyncSession, kinds: set[str], *, limit: int = 20, before_id: int | None = None) -> list[AdminNotice]:
    """Newest first; before_id pages further back."""
    stmt = _visible(select(AdminNotice), kinds).order_by(AdminNotice.id.desc()).limit(limit)
    if before_id:
        stmt = stmt.where(AdminNotice.id < before_id)
    return list((await db.execute(stmt)).scalars().all())


async def mark_seen(db: AsyncSession, staff: User) -> None:
    """The bell was opened: everything so far is seen. Caller commits."""
    staff.notices_seen_at = datetime.now(UTC)
    await db.flush()


def is_new(n: AdminNotice, staff: User) -> bool:
    return staff.notices_seen_at is None or n.created_at > staff.notices_seen_at
