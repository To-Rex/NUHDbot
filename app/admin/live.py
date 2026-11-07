"""The admin panel's live channel: one stream per open page, carrying what the staff member is allowed to see
(orders and payments, deposits, auctions, new customers, chat), plus the sidebar badge counts on demand."""
import asyncio
import json

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from app.admin.common import (
    AUCTION_ROLES,
    CUSTOMER_ROLES,
    DB,
    ORDER_ROLES,
    PAYMENT_ROLES,
    SHIP_ROLES,
    SUPPORT_ROLES,
    can,
    nav_badges,
    staff_dep,
)
from app.admin.router import router
from app.enums import STAFF_ROLES
from app.i18n import t
from app.models import User
from app.services import admin_events

ORDER_WATCHERS = ORDER_ROLES | PAYMENT_ROLES | SHIP_ROLES
VISIBLE = {  # who hears what
    "order_new": ORDER_WATCHERS, "order_status": ORDER_WATCHERS, "payment_new": ORDER_WATCHERS,
    "deposit_new": AUCTION_ROLES, "auction": AUCTION_ROLES, "customer_new": CUSTOMER_ROLES, "chat": SUPPORT_ROLES,
}


def _decorate(ev: dict, lang: str) -> dict:
    """Labels the client cannot translate itself: the order status name."""
    if ev.get("type") == "order_status" and ev.get("status"):
        return {**ev, "status_label": t(lang, f"order_status.{ev['status']}")}
    return ev


@router.get("/events")
async def admin_events_stream(request: Request, db: DB, staff: User = Depends(staff_dep(*STAFF_ROLES))):
    await db.close()  # the stream stays open: give the pooled connection back now
    lang = staff.lang

    async def gen():
        q = admin_events.listen()
        try:
            yield {"event": "ready", "data": "{}", "retry": 2000}
            while not await request.is_disconnected():
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                if can(staff, VISIBLE.get(ev.get("type"), set())):
                    yield {"event": ev["type"], "data": json.dumps(_decorate(ev, lang), default=str)}
        finally:
            admin_events.unlisten(q)

    return EventSourceResponse(gen(), headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/badges")
async def admin_badges(db: DB, staff: User = Depends(staff_dep(*STAFF_ROLES))):
    """The sidebar counts (orders awaiting, unread chats, lots ending soon) — refreshed by the live channel."""
    return JSONResponse(await nav_badges(db))
