"""Live events reach every process: in-memory queues locally, Postgres NOTIFY across processes."""
import asyncio
import json

from sqlalchemy import text

from app.services import auctions, pubsub


async def test_notify_from_another_process_reaches_local_streams(db):
    q = auctions.subscribe(4242)
    all_q = auctions.subscribe()  # the auctions page's channel hears every lot
    task = pubsub.start()
    try:
        assert await pubsub.wait_ready(), "listener connection"
        # another process (a different origin) announces a bid on lot 4242
        body = json.dumps({"o": "other-process", "k": "auction", "p": {"id": 4242, "event": {"type": "bid", "id": 4242, "version": 7}}})
        await db.execute(text("select pg_notify(:ch, :body)"), {"ch": pubsub.CHANNEL, "body": body})
        await db.commit()
        ev = await asyncio.wait_for(q.get(), timeout=5)
        assert ev == {"type": "bid", "id": 4242, "version": 7}
        assert (await asyncio.wait_for(all_q.get(), timeout=5))["version"] == 7
        # this process's own notifications are not delivered twice
        assert pubsub.handle(json.dumps({"o": pubsub.ORIGIN, "k": "auction", "p": {"id": 4242, "event": {}}})) is False
        assert pubsub.handle("not json") is False and pubsub.handle(json.dumps({"o": "x", "k": "unknown", "p": {}})) is False
        # a local publish goes to both the lot's and the page's queues
        auctions.publish(4242, {"type": "bid", "id": 4242, "version": 8})
        assert (await asyncio.wait_for(q.get(), timeout=1))["version"] == 8 and (await asyncio.wait_for(all_q.get(), timeout=1))["version"] == 8
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        auctions.unsubscribe(4242, q)
        auctions.unsubscribe(auctions.ALL, all_q)
