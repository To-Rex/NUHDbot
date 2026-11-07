"""Cross-process fan-out for live events (auction bids, chat messages) over Postgres LISTEN/NOTIFY.

Each process keeps the in-memory queues its own SSE clients listen on; this module carries every published event to the
other processes (several uvicorn workers, or a separate bot process) through one NOTIFY channel, so a bid placed on one
worker reaches a customer whose stream is open on another. Without a listener connection (tests, a failed connection)
events still reach the local queues — only the cross-process hop is lost, and the clients' polling safety net covers it.
"""
import asyncio
import json
import logging
import uuid
from collections.abc import Callable

from sqlalchemy.engine import make_url

from app.config import settings

log = logging.getLogger("nuhdbot.pubsub")

CHANNEL = "nuhd_events"
ORIGIN = uuid.uuid4().hex  # this process: its own notifications are skipped on the way back
_handlers: dict[str, Callable[[dict], None]] = {}
_conn = None
_task: asyncio.Task | None = None


def register(kind: str, handler: Callable[[dict], None]) -> None:
    """A local deliverer for one kind of event (auction, chat): called with the payload from another process."""
    _handlers[kind] = handler


def handle(raw: str) -> bool:
    """One notification's payload → the local deliverer. Returns whether it was delivered (own events are not)."""
    try:
        msg = json.loads(raw)
    except ValueError:
        return False
    if not isinstance(msg, dict) or msg.get("o") == ORIGIN:
        return False
    fn = _handlers.get(msg.get("k"))
    if fn is None:
        return False
    try:
        fn(msg.get("p") or {})
    except Exception:  # noqa: BLE001
        log.exception("pubsub handler failed")
    return True


def notify(kind: str, payload: dict) -> None:
    """Tell the other processes. Fire-and-forget: no listener connection means nobody else to tell."""
    if _conn is None:
        return
    body = json.dumps({"o": ORIGIN, "k": kind, "p": payload}, default=str)
    if len(body) > 7900:  # NOTIFY payloads are capped at 8000 bytes; the clients refetch anyway
        body = json.dumps({"o": ORIGIN, "k": kind, "p": {k: v for k, v in payload.items() if k in ("id", "type", "thread_id", "version")}}, default=str)

    async def send():
        try:
            await _conn.execute("select pg_notify($1, $2)", CHANNEL, body)
        except Exception as e:  # noqa: BLE001
            log.warning("pubsub notify failed: %s", e)

    try:
        asyncio.get_running_loop().create_task(send())
    except RuntimeError:
        pass


def _dsn() -> str:
    url = make_url(settings.database_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


async def _run() -> None:
    """Keep one listening connection; reconnect with a backoff when it drops."""
    global _conn
    import asyncpg

    delay = 1.0
    while True:
        try:
            conn = await asyncpg.connect(_dsn())
            await conn.add_listener(CHANNEL, lambda _c, _pid, _ch, payload: handle(payload))
            _conn = conn
            delay = 1.0
            log.info("pubsub: listening on %s", CHANNEL)
            while True:  # a heartbeat notices a silently dropped connection
                await asyncio.sleep(30)
                await conn.execute("select 1")
        except asyncio.CancelledError:
            break
        except Exception as e:  # noqa: BLE001
            log.warning("pubsub connection lost (%s); retrying in %.0fs", e, delay)
            _conn = None
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15)
    if _conn is not None:
        try:
            await _conn.close()
        except Exception:  # noqa: BLE001
            pass
        _conn = None


def start() -> asyncio.Task:
    global _task
    _task = asyncio.create_task(_run())
    return _task


async def wait_ready(timeout: float = 5.0) -> bool:
    """For tests and startup checks: the listener connection is up."""
    for _ in range(int(timeout / 0.05)):
        if _conn is not None:
            return True
        await asyncio.sleep(0.05)
    return _conn is not None
