"""Live support-chat events for the SSE streams (Mini App thread view, admin inbox).

Events are queued on the DB session and fanned out only after that transaction commits, so a listener
that reacts by fetching new messages always finds them. Every write path (Mini App, admin, Telegram
bot) goes through app.services.support, which queues the events. In-process fan-out: the app runs one
uvicorn worker (the bot polls inside it); several workers would need Postgres LISTEN/NOTIFY instead.
"""
import asyncio
import json
from collections import defaultdict

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse
from starlette.requests import Request

STAFF = "staff"  # every event, for the admin inbox
_listeners: dict[str, set[asyncio.Queue]] = defaultdict(set)
_KEY = "chat_events"


def thread_channel(thread_id: int) -> str:
    return f"thread:{thread_id}"


def listen(channel: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _listeners[channel].add(q)
    return q


def unlisten(channel: str, q: asyncio.Queue) -> None:
    _listeners[channel].discard(q)
    if not _listeners[channel]:
        _listeners.pop(channel, None)


def queue(db: AsyncSession, ev: dict) -> None:
    """Remember an event; it is delivered when this session commits (dropped on rollback)."""
    db.info.setdefault(_KEY, []).append(ev)


def deliver(ev: dict) -> None:
    for ch in (thread_channel(ev["thread_id"]), STAFF):
        for q in list(_listeners.get(ch, ())):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:  # a stuck client; it catches up on reconnect
                pass


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    for ev in session.info.pop(_KEY, []):
        deliver(ev)


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop(_KEY, None)


def stream(request: Request, channel: str) -> EventSourceResponse:
    """SSE response for one channel. Starts with `ready` (clients fetch anything they missed on every
    (re)connect), then one event per change, with a ping every 15 s so dead connections get noticed."""

    async def gen():
        q = listen(channel)  # subscribe only once streaming really starts (no leak if the client never reads)
        try:
            yield {"event": "ready", "data": "{}", "retry": 2000}
            while not await request.is_disconnected():
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield {"event": ev["type"], "data": json.dumps(ev)}
                except TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            unlisten(channel, q)

    return EventSourceResponse(gen(), headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
