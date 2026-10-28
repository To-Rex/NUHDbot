"""JSON endpoints used by the Mini App bootstrap and by SSE streams."""
import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.deps import DB, is_secure
from app.security import verify_telegram_init_data
from app.services import auctions
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
    await db.commit()
    sess = read_session(request)
    sess["uid"] = user.id
    resp = JSONResponse({"ok": True, "registered": user.is_registered, "lang": user.lang})
    write_session(resp, sess, secure=is_secure(), max_age=settings.session_max_age)
    resp.set_cookie("nuhd_lang", user.lang, max_age=settings.session_max_age, samesite="none" if is_secure() else "lax", secure=is_secure())
    return resp


@router.get("/auctions/{auction_id}/stream")
async def auction_stream(auction_id: int, request: Request, db: DB):
    a = await auctions.get_auction(db, auction_id)
    if a is None:
        raise HTTPException(404)
    q = auctions.subscribe(auction_id)
    initial = auctions.snapshot(a)

    async def gen():
        try:
            yield {"event": "state", "data": json.dumps(initial)}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield {"event": ev.get("type", "state"), "data": json.dumps(ev)}
                except TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            auctions.unsubscribe(auction_id, q)

    return EventSourceResponse(gen())


@router.get("/auctions/{auction_id}/state")
async def auction_state(auction_id: int, db: DB):
    a = await auctions.get_auction(db, auction_id)
    if a is None:
        raise HTTPException(404)
    return auctions.snapshot(a)
