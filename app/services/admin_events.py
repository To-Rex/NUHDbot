"""Live events for the admin panel: what staff should notice without reloading a page.

Order events (new, status, payment), deposit claims and new customers are queued on the DB session by the services that
write them and delivered after that transaction commits (dropped on rollback). Auction events and chat events are fed in
by their own modules. Every admin page keeps one stream open (/admin/events); the other processes hear the events through
app.services.pubsub.
"""
import asyncio
from collections import defaultdict

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.services import pubsub

_listeners: set[asyncio.Queue] = set()
_KEY = "admin_events"
_counts: dict[str, int] = defaultdict(int)  # per type, for tests and the health of the stream


def listen() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _listeners.add(q)
    return q


def unlisten(q: asyncio.Queue) -> None:
    _listeners.discard(q)


def queue(db: AsyncSession, type_: str, **data) -> None:
    """Remember an event; it is delivered when this session commits (dropped on rollback)."""
    db.info.setdefault(_KEY, []).append({"type": type_, **data})


def deliver(ev: dict) -> None:
    """To this process's open admin streams now, and to the other processes' through Postgres NOTIFY."""
    deliver_local(ev)
    pubsub.notify("admin", ev)


def deliver_local(ev: dict) -> None:
    _counts[ev.get("type", "?")] += 1
    for q in list(_listeners):
        try:
            q.put_nowait(ev)
        except asyncio.QueueFull:  # a stuck client; it catches up from its own polling
            pass


pubsub.register("admin", deliver_local)


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    for ev in session.info.pop(_KEY, []):
        deliver(ev)


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop(_KEY, None)
