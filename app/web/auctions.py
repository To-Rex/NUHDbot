from decimal import Decimal, InvalidOperation

from fastapi import Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.deps import DB, CurrentUser, Lang, redirect, require_registered
from app.enums import AuctionStatus, DepositStatus
from app.i18n import t
from app.models import AuctionDeposit, Bid, User
from app.services import auction_terms as terms_svc
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
    groups["live"].sort(key=lambda a: a.ends_at)  # ending soonest first
    groups["scheduled"].sort(key=lambda a: a.starts_at)  # starting soonest first
    people = await auctions.participant_counts(db, [a.id for a in lots])
    return render(request, "miniapp/auctions.html", {
        "lang": lang, "groups": groups, "page_title": t(lang, "auction.title"), "lot_people": people,
        "hero": groups["live"][0] if groups["live"] else None,  # the lot ending soonest, shown big on top
        "live_people": sum(people.get(a.id, 0) for a in groups["live"]),
    })


async def _terms_ctx(db, user, lang) -> dict:
    """The auction terms as the viewer sees them: the text, and whether this viewer has accepted the current version."""
    terms = await terms_svc.load(db)
    return {"terms": terms, "terms_ok": terms_svc.accepted(user, terms), "terms_title": terms_svc.title(terms, lang),
            "terms_paras": terms_svc.paragraphs(terms_svc.body(terms, lang)), "terms_updated": await terms_svc.updated_at(db)}


@router.get("/auctions/terms")
async def auction_terms_page(request: Request, db: DB, user: CurrentUser, lang: Lang, lot: int | None = None, view: str = "sheet"):
    """The terms to read before joining: the bid sheet shows them in place of the lot (view=sheet), the lot page in its own sheet."""
    return render(request, "miniapp/partials/auction_terms.html", {**(await _terms_ctx(db, user, lang)), "lot": lot, "view": "page" if view == "page" else "sheet"})


@router.post("/auctions/terms")
async def auction_terms_accept(request: Request, db: DB, lang: Lang, user: User = Depends(require_registered), lot: int | None = Form(None), view: str = Form("sheet"), agree: str = Form("")):
    """The viewer has read the terms and ticks the box: stamp it, then answer with whatever was waiting behind the terms —
    the lot's bid sheet, or the lot page's call to action (and its deposit card, out of band)."""
    if agree != "1":
        return toast(HTMLResponse("", status_code=400), t(lang, "auction.terms_read"), "bad", "error")
    await terms_svc.accept(db, user)
    await db.commit()
    a = await auctions.get_auction(db, lot) if lot else None
    if a is None or a.status == AuctionStatus.DRAFT:
        resp = render(request, "miniapp/partials/auction_terms.html", {**(await _terms_ctx(db, user, lang)), "lot": lot, "view": view})
    else:
        ctx = await _ctx(db, a, user, lang)
        resp = render(request, "miniapp/partials/auction_sheet.html" if view != "page" else "miniapp/partials/auction_accepted.html", {**ctx, "lot": a.id, "view": view})
    return hx_trigger(resp, toast={"msg": t(lang, "auction.terms_ok"), "type": "ok"}, haptic="success", termsAccepted=True)


async def _ctx(db, a, user, lang):
    bids = await auctions.recent_bids(db, a.id, limit=25)
    leader_id = bids[0].user_id if bids else None
    dep = await auctions.user_deposit(db, a.id, user.id) if user else None
    needs_deposit = a.require_deposit and Decimal(a.deposit_amount or 0) > 0
    can_bid = (not needs_deposit) or (dep is not None and dep.status in (DepositStatus.CONFIRMED, DepositStatus.APPLIED))
    numbers = await auctions.bidder_numbers(db, a.id)  # no names on the customer side: "Participant №N"
    start, cur = Decimal(a.start_price_total or 0), Decimal(a.current_price_total or 0)
    growth = cur - start if a.bids_count else Decimal(0)
    stats = {
        "participants": len(numbers), "growth": growth, "growth_pct": (growth / start * 100).quantize(Decimal("0.1")) if start and growth else Decimal(0),
        "last_bid_at": bids[0].created_at if bids else None,
        "extended_min": max(0, int((a.ends_at - a.original_ends_at).total_seconds() // 60)) if a.original_ends_at else 0,
    }
    return {"lang": lang, "a": a, "bids": bids, "leader_id": leader_id, "deposit": dep, "needs_deposit": needs_deposit, "can_bid": can_bid,
            "me_id": user.id if user else None, "numbers": numbers, "stats": stats, **(await _terms_ctx(db, user, lang)),
            "my_best": await auctions.best_bid(db, a.id, user.id) if user and user.id in numbers else None}


@router.get("/auctions/{auction_id}")
async def auction_page(auction_id: int, request: Request, db: DB, user: CurrentUser, lang: Lang):
    a = await auctions.get_auction(db, auction_id)
    if a is None or a.status == AuctionStatus.DRAFT:
        return render(request, "miniapp/not_found.html", {"lang": lang, "message_key": "auction.errors.not_found", "back_url": "/app/auctions"}, status_code=404)
    ctx = await _ctx(db, a, user, lang)
    ctx.update({"page_title": f"{a.brand} {a.model}", "back_url": "/app/auctions"})
    return render(request, "miniapp/auction.html", ctx)


@router.get("/auctions/{auction_id}/sheet")
async def auction_sheet(auction_id: int, request: Request, db: DB, user: CurrentUser, lang: Lang):
    """The bid sheet on the auctions page: the lot, where it stands and where the viewer stands, and the bid form — no page change."""
    a = await auctions.get_auction(db, auction_id)
    if a is None or a.status == AuctionStatus.DRAFT:
        return HTMLResponse("", status_code=404)
    return render(request, "miniapp/partials/auction_sheet.html", await _ctx(db, a, user, lang))


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
async def auction_bid(auction_id: int, request: Request, db: DB, lang: Lang, user: User = Depends(require_registered), amount: str = Form(""), view: str = Form("")):
    tpl = "miniapp/partials/auction_sheet.html" if view == "sheet" else "miniapp/partials/auction_price.html"  # the bid sheet answers with itself
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
        resp = render(request, tpl, await _ctx(db, a, user, lang), status_code=200)
        return toast(resp, t(lang, f"auction.errors.{e.code}", **e.ctx), "bad", "error")
    auctions.publish(a.id, {"type": "bid", **auctions.snapshot(a)})
    if prev is not None and prev.id != user.id:
        try:
            await notifications.notify_outbid(db, prev, a, a.current_price_total)
            await db.commit()
        except Exception:  # noqa: BLE001
            pass
    resp = render(request, tpl, await _ctx(db, a, user, lang))
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
    try:
        await auctions.claim_deposit(db, a, user, proof_name, note or None)
    except auctions.AuctionError as e:
        return toast(redirect(request, f"/app/auctions/{auction_id}"), t(lang, f"auction.errors.{e.code}", **e.ctx), "bad", "error")
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
