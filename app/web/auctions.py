from decimal import Decimal, InvalidOperation

from fastapi import Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.deps import DB, CurrentUser, Lang, redirect, require_registered
from app.enums import AuctionStatus, DepositStatus
from app.i18n import t
from app.models import AuctionDeposit, Bid, User
from app.services import auctions, notifications
from app.services.media import MediaError, save_document
from app.templating import render
from app.web.common import hx_trigger, toast
from app.web.router import router


@router.get("/auctions")
async def auctions_page(request: Request, db: DB, user: CurrentUser, lang: Lang):
    lots = await auctions.list_auctions(db, limit=60)
    groups = {"live": [], "scheduled": [], "ended": []}
    for a in lots:
        key = a.status.value if a.status.value in groups else "ended"
        groups[key].append(a)
    return render(request, "miniapp/auctions.html", {"lang": lang, "groups": groups, "page_title": t(lang, "auction.title")})


async def _ctx(db, a, user, lang):
    bids = await auctions.recent_bids(db, a.id, limit=25)
    leader_id = bids[0].user_id if bids else None
    dep = await auctions.user_deposit(db, a.id, user.id) if user else None
    needs_deposit = a.require_deposit and Decimal(a.deposit_amount or 0) > 0
    can_bid = (not needs_deposit) or (dep is not None and dep.status in (DepositStatus.CONFIRMED, DepositStatus.APPLIED))
    return {"lang": lang, "a": a, "bids": bids, "leader_id": leader_id, "deposit": dep, "needs_deposit": needs_deposit, "can_bid": can_bid, "me_id": user.id if user else None}


@router.get("/auctions/{auction_id}")
async def auction_page(auction_id: int, request: Request, db: DB, user: CurrentUser, lang: Lang):
    a = await auctions.get_auction(db, auction_id)
    if a is None or a.status == AuctionStatus.DRAFT:
        return render(request, "miniapp/not_found.html", {"lang": lang, "message_key": "auction.errors.not_found", "back_url": "/app/auctions"}, status_code=404)
    ctx = await _ctx(db, a, user, lang)
    ctx.update({"page_title": f"{a.brand} {a.model}", "back_url": "/app/auctions"})
    return render(request, "miniapp/auction.html", ctx)


@router.get("/auctions/{auction_id}/bids")
async def auction_bids(auction_id: int, request: Request, db: DB, user: CurrentUser, lang: Lang):
    a = await auctions.get_auction(db, auction_id)
    if a is None:
        return HTMLResponse("", status_code=404)
    return render(request, "miniapp/partials/auction_bids.html", await _ctx(db, a, user, lang))


@router.get("/auctions/{auction_id}/price")
async def auction_price(auction_id: int, request: Request, db: DB, user: CurrentUser, lang: Lang):
    a = await auctions.get_auction(db, auction_id)
    if a is None:
        return HTMLResponse("", status_code=404)
    return render(request, "miniapp/partials/auction_price.html", await _ctx(db, a, user, lang))


@router.post("/auctions/{auction_id}/bid")
async def auction_bid(auction_id: int, request: Request, db: DB, lang: Lang, user: User = Depends(require_registered), amount: str = Form("")):
    amt = None
    if amount.strip():
        try:
            amt = Decimal(amount.replace(",", ".").strip())
        except InvalidOperation:
            resp = HTMLResponse("", status_code=422)
            return toast(resp, t(lang, "misc.error_generic"), "bad", "error")
    uid = user.id
    try:
        a, bid, prev = await auctions.place_bid(db, auction_id, user, amt)
        await db.commit()
    except auctions.AuctionError as e:
        await db.rollback()
        user = await db.get(User, uid)
        a = await auctions.get_auction(db, auction_id)
        if a is None:
            return HTMLResponse("", status_code=404)
        resp = render(request, "miniapp/partials/auction_price.html", await _ctx(db, a, user, lang), status_code=200)
        return toast(resp, t(lang, f"auction.errors.{e.code}", **e.ctx), "bad", "error")
    auctions.publish(a.id, {"type": "bid", **auctions.snapshot(a)})
    if prev is not None and prev.id != user.id:
        try:
            await notifications.notify_outbid(db, prev, a, a.current_price_total)
            await db.commit()
        except Exception:  # noqa: BLE001
            pass
    resp = render(request, "miniapp/partials/auction_price.html", await _ctx(db, a, user, lang))
    return hx_trigger(resp, toast={"msg": t(lang, "auction.bid_ok"), "type": "ok"}, haptic="success", bidPlaced=True)


@router.post("/auctions/{auction_id}/deposit")
async def auction_deposit(auction_id: int, request: Request, db: DB, lang: Lang, user: User = Depends(require_registered), note: str = Form(""), proof: UploadFile | None = File(None)):
    a = await auctions.get_auction(db, auction_id)
    if a is None:
        return redirect(request, "/app/auctions")
    proof_name = None
    if proof and proof.filename:
        try:
            proof_name = await save_document(proof, prefix="dep")
        except MediaError:
            return toast(redirect(request, f"/app/auctions/{auction_id}"), t(lang, "support.errors.file"), "bad", "error")
    await auctions.claim_deposit(db, a, user, proof_name, note or None)
    await db.commit()
    return hx_trigger(redirect(request, f"/app/auctions/{auction_id}"), toast={"msg": t(lang, "auction.deposit_pending"), "type": "ok"}, haptic="success")


async def user_auction_summary(db, user_id: int):
    """Auctions the user has bid on + their deposits (for the profile page)."""
    bid_rows = (await db.execute(select(Bid.auction_id).where(Bid.user_id == user_id).distinct())).scalars().all()
    dep_rows = (await db.execute(select(AuctionDeposit).where(AuctionDeposit.user_id == user_id).order_by(AuctionDeposit.id.desc()))).scalars().all()
    ids = set(bid_rows) | {d.auction_id for d in dep_rows}
    lots = []
    if ids:
        from app.models import Auction

        lots = (await db.execute(select(Auction).where(Auction.id.in_(list(ids))).order_by(Auction.ends_at.desc()))).scalars().unique().all()
    return lots, dep_rows
