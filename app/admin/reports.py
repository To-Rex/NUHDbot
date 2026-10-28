from fastapi import Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.admin.common import ADMIN, DB, REPORT_ROLES, paginate, qpage, render, staff_dep
from app.admin.router import router
from app.enums import AuctionStatus
from app.i18n import t
from app.models import Auction, AuditLog, User
from app.services import reports


@router.get("/reports")
async def reports_page(request: Request, db: DB, staff: User = Depends(staff_dep(*REPORT_ROLES))):
    try:
        days = int(request.query_params.get("days", 30))
    except ValueError:
        days = 30
    days = days if days in (7, 30, 90, 365) else 30
    d = await reports.dashboard(db, days)
    profit = await reports.profit_report(db)
    total_profit = sum((r["profit"] for r in profit if r["profit"] is not None), 0)
    total_revenue = sum((r["revenue"] for r in profit), 0)
    auctions = (await db.execute(select(Auction).where(Auction.status == AuctionStatus.ENDED).order_by(Auction.ends_at.desc()).limit(50))).scalars().unique().all()
    return render(request, staff, "admin/reports/index.html", {"page_title": t(staff.lang, "admin.rep.title"), "d": d, "days": days, "profit": profit, "total_profit": total_profit, "total_revenue": total_revenue, "auctions": auctions})


@router.get("/reports/orders.csv")
async def orders_csv(db: DB, staff: User = Depends(staff_dep(*REPORT_ROLES))):
    data = await reports.orders_csv(db)
    return StreamingResponse(iter(["﻿", data]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=orders.csv"})


@router.get("/reports/customers.csv")
async def customers_csv(db: DB, staff: User = Depends(staff_dep(*REPORT_ROLES))):
    data = await reports.customers_csv(db)
    return StreamingResponse(iter(["﻿", data]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=customers.csv"})


@router.get("/audit")
async def audit_page(request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    q = request.query_params
    stmt = select(AuditLog)
    if q.get("entity"):
        stmt = stmt.where(AuditLog.entity == q["entity"])
    if q.get("action"):
        stmt = stmt.where(AuditLog.action.ilike(f"%{q['action']}%"))
    if q.get("actor") and q["actor"].isdigit():
        stmt = stmt.where(AuditLog.actor_id == int(q["actor"]))
    if q.get("entity_id"):
        stmt = stmt.where(AuditLog.entity_id == q["entity_id"])
    stmt = stmt.order_by(AuditLog.id.desc())
    rows, total, pages = await paginate(db, stmt, qpage(request), 50)
    ids = {r.actor_id for r in rows if r.actor_id}
    actors = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()} if ids else {}
    entities = [e for (e,) in (await db.execute(select(AuditLog.entity).distinct())).all()]
    return render(request, staff, "admin/reports/audit.html", {"page_title": t(staff.lang, "admin.aud.title"), "rows": rows, "total": total, "pages": pages, "page": qpage(request), "actors": actors, "entities": entities})
