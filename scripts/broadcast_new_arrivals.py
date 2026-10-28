"""Send new-arrival notifications to subscribers.  uv run python -m scripts.broadcast_new_arrivals --since-hours 24"""
import argparse
import asyncio

from app.bot.broadcast import broadcast_recent_arrivals
from app.bot.instance import close_bot
from app.db import session_scope


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since-hours", type=int, default=24)
    a = ap.parse_args()
    try:
        async with session_scope() as db:
            result = await broadcast_recent_arrivals(db, a.since_hours)
        for pid, n in result.items():
            print(f"product {pid}: sent {n}")
        print("total:", sum(result.values()))
    finally:
        await close_bot()


if __name__ == "__main__":
    asyncio.run(main())
