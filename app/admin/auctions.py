from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select
from starlette.datastructures import UploadFile

from app.admin.common import (
    AUCTION_EDIT_ROLES,
    AUCTION_ROLES,
    DB,
    PAYMENT_ROLES,
    back,
    can,
    dt_local,
    f_bool,
    f_dec,
    f_dt,
    f_i18n,
    f_int,
    nav_badges,
    render,
    staff_dep,
    toast,
)
from app.admin.router import router
from app.config import settings
from app.enums import AuctionStatus, Condition, DepositStatus, OrderStatus, TestStatus
from app.i18n import t
from app.models import (
    Auction,
    AuctionDeposit,
    AuctionImage,
    Bid,
    Order,
    OrderItem,
    OrderStatusHistory,
    Product,
    User,
)
from app.services import auction_rules, auction_terms, audit, deletion, media, notifications
from app.services import auctions as asvc
from app.services import orders as osvc
from app.services import payment_methods as pm_svc
from app.services.settings_service import get_setting, set_setting
from app.templating import capacity


@router.get("/auctions")
async def auctions_list(request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_ROLES))):
    status = request.query_params.get("status") or ""
    stmt = select(Auction)
    if status in [s.value for s in AuctionStatus]:
        stmt = stmt.where(Auction.status == AuctionStatus(status))
    stmt = stmt.order_by((Auction.status == AuctionStatus.LIVE).desc(), Auction.id.desc()).limit(200)
    items = (await db.execute(stmt)).scalars().unique().all()
    return render(request, staff, "admin/auctions/list.html", {"page_title": t(staff.lang, "admin.auc.title"), "items": items, "status": status, "statuses": list(AuctionStatus), "badges": await nav_badges(db),
                                                                **(await _terms_ctx(db, staff)), **(await _deposit_tile_ctx(db, staff)), **(await _rules_ctx(db, staff))})


async def _rules_ctx(db, staff: User) -> dict:
    """The common lot rules tile: the saved text, the standard text per language, how many lots carry their own rules."""
    return {"rules": await auction_rules.load(db), "rules_default": {code: t(code, "auction.rules_default") for code in settings.langs},
            "rules_own_n": await auction_rules.own_count(db), "rules_total_n": await auction_rules.total_count(db), "can_edit": can(staff, AUCTION_EDIT_ROLES)}


@router.post("/auctions/rules")
async def auctions_rules(request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_EDIT_ROLES))):
    """The rules every lot page shows unless the lot has its own: text per language (empty = the standard text)."""
    form = await request.form()
    before = await auction_rules.load(db)
    after = await auction_rules.save(db, body=f_i18n(form, "rules_body"))
    await audit.log(db, staff.id, "settings.update", "settings", None, {"auction_rules": before}, {"auction_rules": after})
    await db.commit()
    msg = t(staff.lang, "admin.auc.rules_saved")
    if request.headers.get("HX-Request") == "true":
        return render(request, staff, "admin/auctions/_rules.html", {**(await _rules_ctx(db, staff)), "tile_open": True}, headers=toast(msg))
    return back(request, "/admin/auctions#auction-rules", msg)


async def _deposit_tile_ctx(db, staff: User) -> dict:
    """The deposit tile: receipts waiting, the share of the start price new lots ask for, how many payment methods there are."""
    pct = await get_setting(db, "auction_deposit_percent", 10)
    return {"dep_pending": await asvc.pending_deposits_count(db), "dep_percent": format(Decimal(str(pct or 0)).normalize(), "f") if pct else "0",
            "pay_methods_n": len(await pm_svc.list_methods(db, purpose="deposit")), "can_edit": can(staff, AUCTION_EDIT_ROLES)}


@router.post("/auctions/deposit-settings")
async def auctions_deposit_settings(request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_EDIT_ROLES))):
    form = await request.form()
    before = await get_setting(db, "auction_deposit_percent", 10)
    pct = f_dec(form, "auction_deposit_percent")
    pct = max(Decimal(0), min(Decimal(100), pct if pct is not None else Decimal(before or 0)))
    value = int(pct) if pct == pct.to_integral_value() else float(pct)
    await set_setting(db, "auction_deposit_percent", value)
    await audit.log(db, staff.id, "settings.update", "settings", None, {"auction_deposit_percent": before}, {"auction_deposit_percent": value})
    await db.commit()
    msg = t(staff.lang, "admin.set.saved")
    if request.headers.get("HX-Request") == "true":
        return render(request, staff, "admin/auctions/_deposit_settings.html", {**(await _deposit_tile_ctx(db, staff)), "tile_open": True}, headers=toast(msg))
    return back(request, "/admin/auctions#deposit-settings", msg)


@router.get("/auctions/deposits")
async def auctions_deposits(request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_ROLES))):
    """The deposits inbox: every lot's receipts, the ones waiting for a check first."""
    status = request.query_params.get("status", "pending")
    stmt = select(AuctionDeposit).order_by(AuctionDeposit.id.desc()).limit(300)
    if status in [s.value for s in DepositStatus]:
        stmt = stmt.where(AuctionDeposit.status == DepositStatus(status))
    else:
        status = ""
    deposits = (await db.execute(stmt)).scalars().all()
    counts = dict((await db.execute(select(AuctionDeposit.status, func.count()).group_by(AuctionDeposit.status))).all())
    counts = {k.value if hasattr(k, "value") else str(k): v for k, v in counts.items()}
    ids = {d.auction_id for d in deposits}
    lots = {a.id: a for a in (await db.execute(select(Auction).where(Auction.id.in_(ids)))).scalars().unique().all()} if ids else {}
    return render(request, staff, "admin/auctions/deposits.html", {"page_title": t(staff.lang, "admin.auc.dep_inbox"), "deposits": deposits, "lots": lots, "status": status, "counts": counts,
                                                                    "can_pay": can(staff, PAYMENT_ROLES), "badges": await nav_badges(db)})


async def _terms_ctx(db, staff: User) -> dict:
    """The auction terms tile: the saved terms, how many customers accepted the current version, the standard text per language."""
    terms = await auction_terms.load(db)
    return {"terms": terms, "terms_accepted": await auction_terms.accepted_count(db, terms), "can_edit": can(staff, AUCTION_EDIT_ROLES),
            "terms_default": {code: t(code, "auction.terms_default") for code in settings.langs}}


@router.post("/auctions/terms")
async def auctions_terms(request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_EDIT_ROLES))):
    """The terms a customer accepts before joining a lot: asked or not, heading and text per language; "accept again" raises
    the version so everybody reads them once more."""
    form = await request.form()
    before = await auction_terms.load(db)
    after = await auction_terms.save(db, show=f_bool(form, "show"), title=f_i18n(form, "terms_title"), body=f_i18n(form, "terms_body"), reaccept=f_bool(form, "reaccept"))
    await audit.log(db, staff.id, "settings.update", "settings", None, {"auction_terms": before}, {"auction_terms": after})
    await db.commit()
    msg = t(staff.lang, "admin.auc.terms_saved")
    if request.headers.get("HX-Request") == "true":
        return render(request, staff, "admin/auctions/_terms.html", {**(await _terms_ctx(db, staff)), "tile_open": True}, headers=toast(msg))
    return back(request, "/admin/auctions#auction-terms", msg)


def _ctx():
    offset = datetime.now(ZoneInfo(settings.timezone)).utcoffset()  # "Now" on the form: the inputs are in the shop's time zone
    return {"conditions": list(Condition), "tests": list(TestStatus), "tz": settings.timezone, "tz_offset": int(offset.total_seconds() // 60) if offset else 0, "dt_local": dt_local}


async def _form_ctx(db, a: Auction) -> dict:
    """The lot picker: active catalogue products, the ones in stock first (plus the lot's own product if it was hidden since)."""
    rows = list((await db.execute(select(Product).where(Product.is_active.is_(True)).order_by(Product.brand, Product.model))).scalars().unique().all())
    if a.product_id and all(p.id != a.product_id for p in rows) and (own := await db.get(Product, a.product_id)):
        rows.insert(0, own)
    rows.sort(key=lambda p: (p.available <= 0, p.brand.lower(), p.model.lower()))
    pct = await get_setting(db, "auction_deposit_percent", 10)
    common = await auction_rules.load(db)
    return {"products": rows, "picked": next((p for p in rows if p.id == a.product_id), None), "dep_default_pct": asvc.pct_label(Decimal(str(pct or 0))) or "10",
            "common_rules": {code: auction_rules.common_text(common, code) for code in settings.langs}}


def _from_product(a: Auction, p: Product) -> None:
    """The lot is a catalogue product: brand, model, capacity, condition, test, warranty, currency and description come from it."""
    a.product_id = p.id
    a.brand, a.brand_id, a.model, a.capacity_gb = p.brand, p.brand_id, p.model, p.capacity_gb
    a.condition, a.test_status = p.condition, p.test_status
    a.seller_warranty_months, a.factory_warranty_months = p.seller_warranty_months or 0, p.factory_warranty_months or 0
    a.currency = (p.currency or "USD").upper()
    a.description = p.description or {}


@router.get("/auctions/new")
async def auction_new(request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_EDIT_ROLES))):
    a = Auction(brand="", model="", capacity_gb=0, condition=Condition.USED, qty=10, currency="USD", start_price_total=Decimal(0), step_per_unit=Decimal(1), current_price_total=Decimal(0), deposit_amount=Decimal(0), starts_at=(start := datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=1)), ends_at=start + timedelta(days=1), timezone=settings.timezone)
    # the deposit a new lot asks for: the shop's share of the start price (Settings), else the fixed default amount, else none
    pct, fixed = Decimal(str(await get_setting(db, "auction_deposit_percent", 10) or 0)), Decimal(str(await get_setting(db, "auction_deposit_default", 0) or 0))
    if pct > 0:
        a.deposit_percent, a.require_deposit = pct, True
    elif fixed > 0:
        a.deposit_amount, a.require_deposit = fixed, True
    pid = request.query_params.get("product_id")  # "New auction" on a product page
    if pid and pid.isdigit() and (p := await db.get(Product, int(pid))):
        _from_product(a, p)
        a.qty = max(1, min(a.qty, p.available or a.qty))
        if p.price:
            a.start_price_total = Decimal(p.price) * a.qty
    if a.deposit_percent:
        a.deposit_amount = asvc.deposit_for(a.start_price_total, a.deposit_percent)
    return render(request, staff, "admin/auctions/form.html", {"page_title": t(staff.lang, "admin.auc.new"), "a": a, "is_new": True, **_ctx(), **(await _form_ctx(db, a))})


async def _apply(db, a: Auction, form) -> list[str]:
    errors = []
    pid = f_int(form, "product_id", None)
    p = await db.get(Product, pid) if pid else None
    if a.bids_count and a.product_id:  # bids are on this product: it stays
        p = await db.get(Product, a.product_id)
    if p is not None:
        _from_product(a, p)
    elif not a.brand:  # a new lot needs a product; an old hand-made lot keeps its own details
        errors.append("product")
    a.qty = max(1, f_int(form, "qty", 1) or 1)
    sp = f_dec(form, "start_price_total")
    if sp is None or sp <= 0:
        errors.append("start_price_total")
    a.start_price_total = sp or Decimal(0)
    a.step_per_unit = f_dec(form, "step_per_unit") or Decimal(1)
    # the deposit: a share of the start price (percent), a fixed amount, or none; older forms send amount + switch only
    mode = form.get("deposit_mode") or ("fixed" if f_bool(form, "require_deposit") else ("legacy" if "deposit_amount" in form else "off"))
    if mode == "percent":
        a.deposit_percent = max(Decimal(0), min(Decimal(100), f_dec(form, "deposit_percent") or Decimal(0)))
        a.deposit_amount = asvc.deposit_for(a.start_price_total, a.deposit_percent)
        a.require_deposit = a.deposit_amount > 0
    elif mode in ("fixed", "legacy"):
        a.deposit_percent = None
        a.deposit_amount = f_dec(form, "deposit_amount") or Decimal(0)
        a.require_deposit = (mode == "fixed" or f_bool(form, "require_deposit")) and a.deposit_amount > 0
    else:
        a.deposit_percent, a.require_deposit = None, False
    starts, ends = f_dt(form, "starts_at"), f_dt(form, "ends_at")
    if not starts or not ends or ends <= starts:
        errors.append("times")
    else:
        a.starts_at, a.ends_at = starts, ends
        if a.status in (AuctionStatus.DRAFT, AuctionStatus.SCHEDULED):
            a.original_ends_at = ends
    a.timezone = settings.timezone
    # the rules: the common text (edited on the Auctions page) unless this lot gets its own; older forms send the text alone
    mode = form.get("rules_mode")
    a.rules = {} if mode == "common" else f_i18n(form, "rules")
    if a.bids_count == 0:
        a.current_price_total = a.start_price_total
    return errors


@router.post("/auctions/new")
async def auction_create(request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_EDIT_ROLES))):
    form = await request.form()
    a = Auction(status=AuctionStatus.DRAFT, bids_count=0, current_price_total=Decimal(0))
    errors = await _apply(db, a, form)
    if errors:
        return render(request, staff, "admin/auctions/form.html", {"page_title": t(staff.lang, "admin.auc.new"), "a": a, "is_new": True, "errors": errors, **_ctx(), **(await _form_ctx(db, a))}, status_code=400)
    a.original_ends_at = a.ends_at
    db.add(a)
    await db.flush()
    await audit.log(db, staff.id, "auction.create", "auction", a.id, None, {"title": a.title, "qty": a.qty, "start": str(a.start_price_total)})
    await db.commit()
    return back(request, f"/admin/auctions/{a.id}", t(staff.lang, "admin.flash.saved"))


async def _get(db, aid: int) -> Auction:
    a = await db.get(Auction, aid)
    if not a:
        raise HTTPException(404)
    return a


@router.get("/auctions/{aid}")
async def auction_detail(aid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_ROLES))):
    a = await _get(db, aid)
    bids = await asvc.recent_bids(db, a.id, 100)
    deposits = (await db.execute(select(AuctionDeposit).where(AuctionDeposit.auction_id == a.id).order_by((AuctionDeposit.status == DepositStatus.PENDING).desc(), AuctionDeposit.id.desc()))).scalars().all()
    result_order = await db.get(Order, a.result_order_id) if a.result_order_id else None
    return render(request, staff, "admin/auctions/detail.html", {"page_title": f"{a.title} {capacity(a.capacity_gb)}", "a": a, "bids": bids, "deposits": deposits, "result_order": result_order, "can_edit": can(staff, AUCTION_EDIT_ROLES), "can_pay": can(staff, PAYMENT_ROLES), "own_rules": auction_rules.has_own(a), **_ctx()})


@router.get("/auctions/{aid}/bids")
async def auction_bids_partial(aid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_ROLES))):
    a = await _get(db, aid)
    bids = await asvc.recent_bids(db, a.id, 100)
    return render(request, staff, "admin/auctions/_bids.html", {"a": a, "bids": bids})


@router.get("/auctions/{aid}/edit")
async def auction_edit(aid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_EDIT_ROLES))):
    a = await _get(db, aid)
    return render(request, staff, "admin/auctions/form.html", {"page_title": t(staff.lang, "admin.auc.edit"), "a": a, "is_new": False, **_ctx(), **(await _form_ctx(db, a))})


@router.post("/auctions/{aid}/edit")
async def auction_update(aid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_EDIT_ROLES))):
    a = await _get(db, aid)
    form = await request.form()
    before = {"start": str(a.start_price_total), "ends_at": a.ends_at.isoformat(), "qty": a.qty}
    errors = await _apply(db, a, form)
    if errors:
        return render(request, staff, "admin/auctions/form.html", {"page_title": t(staff.lang, "admin.auc.edit"), "a": a, "is_new": False, "errors": errors, **_ctx(), **(await _form_ctx(db, a))}, status_code=400)
    a.version += 1
    await audit.log(db, staff.id, "auction.update", "auction", a.id, before, {"start": str(a.start_price_total), "ends_at": a.ends_at.isoformat(), "qty": a.qty})
    await db.commit()
    asvc.publish(a.id, {"type": "state", **asvc.snapshot(a)})
    return back(request, f"/admin/auctions/{aid}", t(staff.lang, "admin.flash.saved"))


@router.post("/auctions/{aid}/images")
async def auction_images(aid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_EDIT_ROLES))):
    a = await _get(db, aid)
    form = await request.form()
    for f in form.getlist("files"):
        if isinstance(f, UploadFile) and f.filename and len(a.images) < settings.max_images_per_product:
            try:
                meta = await media.save_image(f, prefix=f"a{a.id}")
            except media.MediaError:
                continue
            db.add(AuctionImage(auction_id=a.id, filename=meta["filename"], thumb=meta["thumb"], sort=len(a.images)))
            await db.flush()
            await db.refresh(a)
    await db.commit()
    return back(request, f"/admin/auctions/{aid}", t(staff.lang, "admin.flash.saved"))


@router.post("/auctions/{aid}/delete")
async def auction_delete(aid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_EDIT_ROLES))):
    a = await _get(db, aid)
    snap = {"title": a.title, "status": a.status, "qty": a.qty, "start": str(a.start_price_total), "current": str(a.current_price_total), "bids": a.bids_count}
    gone = {"type": "ended", **asvc.snapshot(a), "status": AuctionStatus.CANCELLED}  # open lot pages reload onto "not found"
    await deletion.delete_auction(db, a)
    await audit.log(db, staff.id, "auction.delete", "auction", aid, snap, None)
    await db.commit()
    asvc.publish(aid, gone)
    return back(request, "/admin/auctions", t(staff.lang, "admin.auc.deleted"))


@router.post("/auctions/{aid}/bids/{bid_id}/delete")
async def auction_bid_delete(aid: int, bid_id: int, request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_EDIT_ROLES))):
    """A wrong or fake bid out: the price, the leader and (once ended) the winner move to the bids that are left."""
    a = await _get(db, aid)
    bid = await db.get(Bid, bid_id)
    if not bid or bid.auction_id != a.id:
        raise HTTPException(404)
    await audit.log(db, staff.id, "auction.bid.delete", "auction", a.id, {"bid": bid.id, "user_id": bid.user_id, "amount": str(bid.amount_total)}, None)
    await deletion.delete_bid(db, a, bid)
    await db.commit()
    deletion.announce_auction(a)
    return back(request, f"/admin/auctions/{aid}", t(staff.lang, "admin.auc.bid_deleted"))


@router.post("/auctions/{aid}/images/{iid}/delete")
async def auction_image_delete(aid: int, iid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_EDIT_ROLES))):
    img = await db.get(AuctionImage, iid)
    if img and img.auction_id == aid:
        await media.delete_files(img.filename, img.thumb)
        await db.delete(img)
        await db.commit()
    return back(request, f"/admin/auctions/{aid}", t(staff.lang, "admin.flash.deleted"))


async def _end_now(db, a: Auction, staff: User) -> None:
    last = (await db.execute(select(Bid).where(Bid.auction_id == a.id).order_by(Bid.id.desc()).limit(1))).scalar_one_or_none()
    a.status = AuctionStatus.ENDED
    a.ends_at = min(a.ends_at, datetime.now(UTC))
    a.version += 1
    if last:
        a.winner_user_id, a.winner_bid_id = last.user_id, last.id
    await db.flush()
    asvc.publish(a.id, {"type": "ended", **asvc.snapshot(a)})
    users = await asvc.participants(db, a.id)
    await notifications.notify_auction_result(db, a, users)


@router.post("/auctions/{aid}/action/{action}")
async def auction_action(aid: int, action: str, request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_EDIT_ROLES))):
    a = await _get(db, aid)
    now = datetime.now(UTC)
    msg = t(staff.lang, "admin.flash.saved")
    if action == "publish" and a.status == AuctionStatus.DRAFT:
        if a.ends_at <= now:
            return back(request, f"/admin/auctions/{aid}", t(staff.lang, "admin.auc.invalid_times"), "bad")
        a.status = AuctionStatus.LIVE if a.starts_at <= now else AuctionStatus.SCHEDULED
        a.original_ends_at = a.ends_at
        if a.bids_count == 0:
            a.current_price_total = a.start_price_total
        msg = t(staff.lang, "admin.auc.published")
    elif action == "start" and a.status in (AuctionStatus.DRAFT, AuctionStatus.SCHEDULED):
        a.status = AuctionStatus.LIVE
        a.starts_at = now
        if a.ends_at <= now:
            a.ends_at = now + timedelta(hours=1)
            a.original_ends_at = a.ends_at
        msg = t(staff.lang, "admin.auc.started")
    elif action == "end" and a.status == AuctionStatus.LIVE:
        await _end_now(db, a, staff)
        msg = t(staff.lang, "admin.auc.ended")
    elif action == "cancel" and a.status not in (AuctionStatus.ENDED,):
        a.status = AuctionStatus.CANCELLED
        asvc.publish(a.id, {"type": "ended", **asvc.snapshot(a)})
    else:
        return back(request, f"/admin/auctions/{aid}", t(staff.lang, "admin.forbidden"), "bad")
    a.version += 1
    await audit.log(db, staff.id, f"auction.{action}", "auction", a.id, None, {"status": a.status})
    await db.commit()
    asvc.publish(a.id, {"type": "state", **asvc.snapshot(a)})
    return back(request, f"/admin/auctions/{aid}", msg)


@router.post("/auctions/{aid}/deposits/{did}/{action}")
async def deposit_action(aid: int, did: int, action: str, request: Request, db: DB, staff: User = Depends(staff_dep(*PAYMENT_ROLES))):
    """The verdict on a receipt: confirm (the customer may bid), reject with a reason (they may send another), refund, or apply
    the winner's deposit to the purchase. The customer hears it in Telegram and on the open lot page at once."""
    dep = await db.get(AuctionDeposit, did)
    if not dep or dep.auction_id != aid:
        raise HTTPException(404)
    form = await request.form()
    nxt = form.get("next") or f"/admin/auctions/{aid}#deposits"
    if not str(nxt).startswith("/admin/"):
        nxt = f"/admin/auctions/{aid}#deposits"
    try:
        before = await asvc.review_deposit(db, dep, staff, action, form.get("note"))
    except asvc.AuctionError:
        raise HTTPException(400) from None
    await db.commit()
    asvc.announce_deposit(dep)
    if before != dep.status and dep.status in (DepositStatus.CONFIRMED, DepositStatus.REJECTED, DepositStatus.REFUNDED):
        a = await _get(db, aid)
        try:
            await notifications.notify_deposit(db, dep.user, a, dep)
            await db.commit()
        except Exception:  # noqa: BLE001
            pass
    return back(request, nxt, t(staff.lang, f"admin.auc.dep_done_{action}"))


@router.post("/auctions/{aid}/create-order")
async def auction_create_order(aid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_EDIT_ROLES))):
    a = await _get(db, aid)
    if a.status != AuctionStatus.ENDED or not a.winner_user_id:
        return back(request, f"/admin/auctions/{aid}", t(staff.lang, "admin.forbidden"), "bad")
    if a.result_order_id:
        return back(request, f"/admin/orders/{a.result_order_id}")
    winner = await db.get(User, a.winner_user_id)
    unit = (Decimal(a.current_price_total) / a.qty).quantize(Decimal("0.01"))
    o = Order(
        number=await osvc.next_order_number(db), user_id=winner.id, status=OrderStatus.AWAITING_ADVANCE, currency=a.currency,
        subtotal=a.current_price_total, total=a.current_price_total, receiver_name=winner.last_receiver_name or winner.full_name,
        receiver_phone=winner.last_receiver_phone or winner.phone or "", country=winner.country, city=winner.city, address=winner.last_address or "",
        cargo_code=winner.last_cargo_code, cargo_company=winner.last_cargo_company, admin_note=f"Auction #{a.id} winner", confirmed_at=datetime.now(UTC), source="auction",
    )
    o.items.append(OrderItem(product_id=a.product_id, brand=a.brand, model=a.model, capacity_gb=a.capacity_gb, condition=a.condition, qty=a.qty, unit_price=unit))
    o.history.append(OrderStatusHistory(from_status=None, to_status=OrderStatus.AWAITING_ADVANCE, by_user_id=staff.id, note=f"auction #{a.id}"))
    o.payments = []  # a new order has none; set it so reading what is paid never needs an implicit (async-unsafe) lazy load
    db.add(o)
    await db.flush()
    a.result_order_id = o.id
    # winner's deposit counts towards the purchase (22.05)
    dep = await asvc.user_deposit(db, a.id, winner.id)
    if dep and dep.status == DepositStatus.CONFIRMED:
        dep.status = DepositStatus.APPLIED
        from app.enums import PaymentKind

        pay = await osvc.add_payment(db, o, winner, PaymentKind.DEPOSIT, Decimal(dep.amount), "deposit", dep.proof_filename, f"auction deposit #{dep.id}")
        await osvc.confirm_payment(db, pay, staff, True, "deposit applied")
    await audit.log(db, staff.id, "auction.order", "auction", a.id, None, {"order": o.number})
    await notifications.notify_order_status(db, o, winner)
    await db.commit()
    return back(request, f"/admin/orders/{o.id}", t(staff.lang, "admin.auc.order_created"))
