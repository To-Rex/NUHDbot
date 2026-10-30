from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
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
    f_str,
    nav_badges,
    render,
    staff_dep,
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
from app.services import auctions as asvc
from app.services import audit, media, notifications
from app.services import brands as brand_service
from app.services import orders as osvc
from app.templating import capacity


@router.get("/auctions")
async def auctions_list(request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_ROLES))):
    status = request.query_params.get("status") or ""
    stmt = select(Auction)
    if status in [s.value for s in AuctionStatus]:
        stmt = stmt.where(Auction.status == AuctionStatus(status))
    stmt = stmt.order_by((Auction.status == AuctionStatus.LIVE).desc(), Auction.id.desc()).limit(200)
    items = (await db.execute(stmt)).scalars().unique().all()
    return render(request, staff, "admin/auctions/list.html", {"page_title": t(staff.lang, "admin.auc.title"), "items": items, "status": status, "statuses": list(AuctionStatus), "badges": await nav_badges(db)})


def _ctx():
    return {"conditions": list(Condition), "tests": list(TestStatus), "tz": settings.timezone, "dt_local": dt_local}


async def _brands_ctx(db, a=None) -> dict:
    brands = await brand_service.list_brands(db, active_only=True)
    if a is not None and getattr(a, "brand_id", None) and all(b.id != a.brand_id for b in brands):
        own = await brand_service.get_brand(db, a.brand_id)
        if own:
            brands.append(own)
    return {"brands": brands}


@router.get("/auctions/new")
async def auction_new(request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_EDIT_ROLES))):
    a = Auction(brand="", model="", capacity_gb=1000, condition=Condition.USED, qty=10, currency="USD", start_price_total=Decimal(0), step_per_unit=Decimal(1), current_price_total=Decimal(0), deposit_amount=Decimal(0), starts_at=datetime.now(UTC) + timedelta(hours=1), ends_at=datetime.now(UTC) + timedelta(days=1), timezone=settings.timezone)
    pid = request.query_params.get("product_id")
    if pid and pid.isdigit():
        p = await db.get(Product, int(pid))
        if p:
            a.product_id, a.brand, a.model, a.capacity_gb, a.condition, a.test_status = p.id, p.brand, p.model, p.capacity_gb, p.condition, p.test_status
            a.brand_id = p.brand_id
            a.seller_warranty_months, a.factory_warranty_months, a.currency = p.seller_warranty_months, p.factory_warranty_months, p.currency
            a.description = p.description
            if p.price:
                a.start_price_total = Decimal(p.price) * a.qty
    products = (await db.execute(select(Product).where(Product.is_active.is_(True)).order_by(Product.brand, Product.model))).scalars().unique().all()
    return render(request, staff, "admin/auctions/form.html", {"page_title": t(staff.lang, "admin.auc.new"), "a": a, "is_new": True, "products": products, **_ctx(), **(await _brands_ctx(db, a))})


async def _apply(db, a: Auction, form) -> list[str]:
    errors = []
    b = await brand_service.resolve_brand(db, form.get("brand_id"), f_str(form, "brand_other", maxlen=60) or f_str(form, "brand", maxlen=60))
    brand_service.sync_product_brand(a, b, fallback_name="")
    a.model = f_str(form, "model", maxlen=120)
    if not a.brand or not a.model:
        errors.append("brand/model")
    a.capacity_gb = f_int(form, "capacity_gb", 0) or 0
    a.condition = Condition(form.get("condition") or "used")
    a.test_status = TestStatus(form.get("test_status") or "untested")
    a.qty = max(1, f_int(form, "qty", 1) or 1)
    a.seller_warranty_months = f_int(form, "seller_warranty_months", 0) or 0
    a.factory_warranty_months = f_int(form, "factory_warranty_months", 0) or 0
    a.currency = (f_str(form, "currency", "USD", 3) or "USD").upper()
    sp = f_dec(form, "start_price_total")
    if sp is None or sp <= 0:
        errors.append("start_price_total")
    a.start_price_total = sp or Decimal(0)
    a.step_per_unit = f_dec(form, "step_per_unit") or Decimal(1)
    a.deposit_amount = f_dec(form, "deposit_amount") or Decimal(0)
    a.require_deposit = f_bool(form, "require_deposit") and a.deposit_amount > 0
    pid = f_int(form, "product_id", None)
    a.product_id = pid or None
    starts, ends = f_dt(form, "starts_at"), f_dt(form, "ends_at")
    if not starts or not ends or ends <= starts:
        errors.append("times")
    else:
        a.starts_at, a.ends_at = starts, ends
        if a.status in (AuctionStatus.DRAFT, AuctionStatus.SCHEDULED):
            a.original_ends_at = ends
    a.timezone = settings.timezone
    a.description = f_i18n(form, "description")
    a.rules = f_i18n(form, "rules")
    if a.bids_count == 0:
        a.current_price_total = a.start_price_total
    return errors


@router.post("/auctions/new")
async def auction_create(request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_EDIT_ROLES))):
    form = await request.form()
    a = Auction(status=AuctionStatus.DRAFT, bids_count=0, current_price_total=Decimal(0))
    errors = await _apply(db, a, form)
    if errors:
        products = (await db.execute(select(Product).where(Product.is_active.is_(True)).order_by(Product.brand, Product.model))).scalars().unique().all()
        return render(request, staff, "admin/auctions/form.html", {"page_title": t(staff.lang, "admin.auc.new"), "a": a, "is_new": True, "errors": errors, "products": products, **_ctx(), **(await _brands_ctx(db, a))}, status_code=400)
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
    deposits = (await db.execute(select(AuctionDeposit).where(AuctionDeposit.auction_id == a.id).order_by(AuctionDeposit.id.desc()))).scalars().all()
    result_order = await db.get(Order, a.result_order_id) if a.result_order_id else None
    return render(request, staff, "admin/auctions/detail.html", {"page_title": f"{a.title} {capacity(a.capacity_gb)}", "a": a, "bids": bids, "deposits": deposits, "result_order": result_order, "can_edit": can(staff, AUCTION_EDIT_ROLES), "can_pay": can(staff, PAYMENT_ROLES), **_ctx()})


@router.get("/auctions/{aid}/bids")
async def auction_bids_partial(aid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_ROLES))):
    a = await _get(db, aid)
    bids = await asvc.recent_bids(db, a.id, 100)
    return render(request, staff, "admin/auctions/_bids.html", {"a": a, "bids": bids})


@router.get("/auctions/{aid}/edit")
async def auction_edit(aid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_EDIT_ROLES))):
    a = await _get(db, aid)
    products = (await db.execute(select(Product).where(Product.is_active.is_(True)).order_by(Product.brand, Product.model))).scalars().unique().all()
    return render(request, staff, "admin/auctions/form.html", {"page_title": t(staff.lang, "admin.auc.edit"), "a": a, "is_new": False, "products": products, **_ctx(), **(await _brands_ctx(db, a))})


@router.post("/auctions/{aid}/edit")
async def auction_update(aid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*AUCTION_EDIT_ROLES))):
    a = await _get(db, aid)
    form = await request.form()
    if a.status in (AuctionStatus.ENDED, AuctionStatus.CANCELLED):
        return back(request, f"/admin/auctions/{aid}", t(staff.lang, "admin.forbidden"), "bad")
    before = {"start": str(a.start_price_total), "ends_at": a.ends_at.isoformat(), "qty": a.qty}
    errors = await _apply(db, a, form)
    if errors:
        products = (await db.execute(select(Product).where(Product.is_active.is_(True)).order_by(Product.brand, Product.model))).scalars().unique().all()
        return render(request, staff, "admin/auctions/form.html", {"page_title": t(staff.lang, "admin.auc.edit"), "a": a, "is_new": False, "errors": errors, "products": products, **_ctx(), **(await _brands_ctx(db, a))}, status_code=400)
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
    dep = await db.get(AuctionDeposit, did)
    if not dep or dep.auction_id != aid:
        raise HTTPException(404)
    mapping = {"confirm": DepositStatus.CONFIRMED, "refund": DepositStatus.REFUNDED, "apply": DepositStatus.APPLIED}
    if action not in mapping:
        raise HTTPException(400)
    before = dep.status
    dep.status = mapping[action]
    dep.confirmed_by = staff.id
    await audit.log(db, staff.id, f"deposit.{action}", "deposit", dep.id, {"status": before}, {"status": dep.status, "user": dep.user_id, "amount": str(dep.amount)})
    await db.commit()
    return back(request, f"/admin/auctions/{aid}#deposits", t(staff.lang, "admin.flash.saved"))


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
