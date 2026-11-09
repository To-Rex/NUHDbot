"""JSON endpoints used by the Mini App bootstrap and by SSE streams."""
import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.deps import DB, is_secure
from app.models import Auction
from app.security import verify_telegram_init_data
from app.services import ads, auctions
from app.services.cart import read_session, write_session
from app.services.users import get_or_create_tg_user

router = APIRouter(tags=["api"])


class TelegramAuth(BaseModel):
    init_data: str
    start_param: str | None = None


@router.post("/auth/telegram")
async def auth_telegram(payload: TelegramAuth, request: Request, db: DB):
    data = verify_telegram_init_data(payload.init_data)
    if not data or not data.get("user"):
        raise HTTPException(401, "invalid init data")
    source = (payload.start_param or data.get("start_param") or "")[:64] or None
    user = await get_or_create_tg_user(db, data["user"], source=source)
    sess = read_session(request)
    if source and source.startswith("src_") and sess.get("src") != source:  # opened through an ad post's link: one click, once per session
        await ads.count_click(db, source)
        sess["src"] = source
    await db.commit()
    sess["uid"] = user.id
    resp = JSONResponse({"ok": True, "registered": user.is_registered, "lang": user.lang})
    write_session(resp, sess, secure=is_secure(), max_age=settings.session_max_age)
    resp.set_cookie("nuhd_lang", user.lang, max_age=settings.session_max_age, samesite="none" if is_secure() else "lax", secure=is_secure())
    return resp


SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}  # no proxy buffering: events leave as they happen


def _stream(request: Request, channel: int, first: dict | None):
    """Events of one lot (or of every lot, channel 0): an opening `state` (or `ready`), then one event per change,
    a ping every 15 s so a dead connection gets noticed on both ends."""

    async def gen():
        q = auctions.subscribe(channel)  # subscribe only once streaming really starts
        try:
            yield {"event": "state", "data": json.dumps(first), "retry": 2000} if first is not None else {"event": "ready", "data": "{}", "retry": 2000}
            while not await request.is_disconnected():
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield {"event": ev.get("type", "state"), "data": json.dumps(ev)}
                except TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            auctions.unsubscribe(channel, q)

    return EventSourceResponse(gen(), headers=SSE_HEADERS)


@router.get("/auctions/stream")
async def auctions_stream(request: Request):
    """Every lot's events — the auctions page keeps all its cards current from this one stream."""
    return _stream(request, auctions.ALL, None)


@router.get("/auctions/{auction_id}/stream")
async def auction_stream(auction_id: int, request: Request, db: DB):
    a = await auctions.get_auction(db, auction_id)
    if a is None:
        raise HTTPException(404)
    initial = auctions.snapshot(a)
    await db.close()  # the stream stays open: give the pooled connection back now
    return _stream(request, auction_id, initial)


@router.get("/auctions/state")
async def auctions_state(ids: str, db: DB):
    """Several lots' state at once (the auctions page's polling safety net)."""
    wanted = [int(x) for x in ids.split(",") if x.strip().isdigit()][:60]
    if not wanted:
        return []
    rows = (await db.execute(select(Auction).where(Auction.id.in_(wanted)))).scalars().unique().all()
    people = await auctions.participant_counts(db, [a.id for a in rows])
    return [{**auctions.snapshot(a), "people": people.get(a.id, 0)} for a in rows]


@router.get("/auctions/{auction_id}/state")
async def auction_state(auction_id: int, db: DB):
    a = await auctions.get_auction(db, auction_id)
    if a is None:
        raise HTTPException(404)
    return auctions.snapshot(a)
