from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, or_, select

from app.admin.common import (
    ADMIN,
    CUSTOMER_ROLES,
    DB,
    back,
    f_opt,
    nav_badges,
    qpage,
    render,
    staff_dep,
)
from app.admin.router import router
from app.config import settings
from app.enums import Role
from app.i18n import normalize_lang, t
from app.models import Auction, AuctionDeposit, Bid, Order, Subscription, SupportThread, User
from app.services import audit, deletion


@router.get("/customers")
async def customers_list(request: Request, db: DB, staff: User = Depends(staff_dep(*CUSTOMER_ROLES))):
    q = request.query_params
    counts = select(Order.user_id, func.count().label("n")).group_by(Order.user_id).subquery()
    stmt = select(User, func.coalesce(counts.c.n, 0)).outerjoin(counts, counts.c.user_id == User.id).where(User.role == Role.CUSTOMER)
    if q.get("q"):
        like = f"%{q['q'].strip()}%"
        stmt = stmt.where(or_(User.first_name.ilike(like), User.last_name.ilike(like), User.phone.ilike(like), User.tg_username.ilike(like), User.city.ilike(like)))
    if q.get("country"):
        stmt = stmt.where(User.country == q["country"].upper())
    if q.get("reg") == "1":
        stmt = stmt.where(User.registered_at.is_not(None))
    elif q.get("reg") == "0":
        stmt = stmt.where(User.registered_at.is_(None))
    if q.get("source"):
        stmt = stmt.where(User.source == q["source"])
    stmt = stmt.order_by(User.id.desc())
    page = qpage(request)
    total = (await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()
    rows = (await db.execute(stmt.offset((page - 1) * 40).limit(40))).all()
    pages = max(1, (total + 39) // 40)
    countries = [c for (c,) in (await db.execute(select(User.country).where(User.country.is_not(None)).distinct())).all()]
    return render(request, staff, "admin/customers/list.html", {"page_title": t(staff.lang, "admin.cust.title"), "rows": rows, "total": total, "pages": pages, "page": page, "countries": countries, "badges": await nav_badges(db)})


@router.get("/customers/{uid}")
async def customer_detail(uid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*CUSTOMER_ROLES))):
    u = await db.get(User, uid)
    if not u:
        raise HTTPException(404)
    orders = (await db.execute(select(Order).where(Order.user_id == uid).order_by(Order.id.desc()).limit(50))).scalars().unique().all()
    bids = (await db.execute(select(Bid, Auction).join(Auction, Auction.id == Bid.auction_id).where(Bid.user_id == uid).order_by(Bid.id.desc()).limit(30))).all()
    deposits = (await db.execute(select(AuctionDeposit).where(AuctionDeposit.user_id == uid).order_by(AuctionDeposit.id.desc()))).scalars().all()
    subs = (await db.execute(select(Subscription).where(Subscription.user_id == uid))).scalars().all()
    threads = (await db.execute(select(SupportThread).where(SupportThread.user_id == uid).order_by(SupportThread.id.desc()))).scalars().unique().all()
    return render(request, staff, "admin/customers/detail.html", {"page_title": u.full_name, "u": u, "orders": orders, "bids": bids, "deposits": deposits, "subs": subs, "threads": threads, "all_roles": list(Role), "langs": settings.langs})


# what staff may correct on a customer's card (the name and phone come from Telegram / registration)
PROFILE_FIELDS = (("first_name", 100), ("last_name", 100), ("phone", 32), ("last_receiver_name", 120), ("last_receiver_phone", 32), ("last_address", 2000), ("last_cargo_company", 120), ("last_cargo_code", 64))


@router.post("/customers/{uid}/update")
async def customer_update(uid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*CUSTOMER_ROLES))):
    u = await db.get(User, uid)
    if not u:
        raise HTTPException(404)
    form = await request.form()
    before = {"country": u.country, "city": u.city, "lang": u.lang, "is_blocked": u.is_blocked, "role": u.role}
    action = form.get("action")
    if action == "block":
        u.is_blocked = True
    elif action == "unblock":
        u.is_blocked = False
    elif action == "role":
        if staff.role != Role.ADMIN:
            raise HTTPException(403)
        if u.id == staff.id:
            return back(request, f"/admin/customers/{uid}", t(staff.lang, "admin.staff.self_guard"), "bad")
        u.role = Role(form.get("role") or "customer")
    else:
        before |= {f: getattr(u, f) for f, _ in PROFILE_FIELDS}
        for f, n in PROFILE_FIELDS:
            v = f_opt(form, f, n)
            setattr(u, f, v or ("" if f in ("first_name", "last_name") else None))
        u.country = (f_opt(form, "country", 2) or "").upper() or None
        u.city = f_opt(form, "city", 100)
        u.lang = normalize_lang(form.get("lang"))
    after = {"country": u.country, "city": u.city, "lang": u.lang, "is_blocked": u.is_blocked, "role": u.role} | ({f: getattr(u, f) for f, _ in PROFILE_FIELDS} if not action else {})
    await audit.log(db, staff.id, f"customer.{action or 'update'}", "user", u.id, before, after)
    await db.commit()
    return back(request, f"/admin/customers/{uid}", t(staff.lang, "admin.flash.saved"))


@router.post("/customers/{uid}/delete")
async def customer_delete(uid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    """The customer and everything that is only theirs. Opening the bot again later starts a fresh registration."""
    u = await db.get(User, uid)
    if not u or u.is_staff:
        raise HTTPException(404)
    snap = {"name": u.full_name, "phone": u.phone, "tg_id": u.tg_id, "tg_username": u.tg_username, "country": u.country, "city": u.city,
            "orders": (await db.execute(select(func.count()).select_from(Order).where(Order.user_id == uid))).scalar_one()}
    touched = await deletion.delete_customer(db, u)
    await audit.log(db, staff.id, "customer.delete", "user", uid, snap, None)
    await db.commit()
    for a in touched:
        deletion.announce_auction(a)
    return back(request, "/admin/customers", t(staff.lang, "admin.cust.deleted", name=snap["name"]))
