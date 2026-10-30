from datetime import UTC, datetime, timedelta

from fastapi import Depends, Request
from sqlalchemy import select

from app.admin.common import DB, nav_badges, render, staff_dep
from app.admin.router import router
from app.enums import AuctionStatus, OrderStatus, ThreadStatus
from app.models import Auction, Order, SupportThread, User
from app.services import reports


@router.get("")
@router.get("/")
async def dashboard(request: Request, db: DB, staff: User = Depends(staff_dep())):
    try:
        days = int(request.query_params.get("days", 30))
    except ValueError:
        days = 30
    days = days if days in (7, 30, 90, 365) else 30
    data = await reports.dashboard(db, days)
    awaiting = (await db.execute(select(Order).where(Order.status == OrderStatus.AWAITING_ADMIN).order_by(Order.id.desc()).limit(8))).scalars().unique().all()
    # money is agreed in chat; these orders are waiting for staff to record what arrived
    awaiting_pay = (
        await db.execute(select(Order).where(Order.status.in_((OrderStatus.AWAITING_ADVANCE, OrderStatus.AWAITING_BALANCE))).order_by(Order.id.desc()).limit(8))
    ).scalars().unique().all()
    threads = (
        await db.execute(
            select(SupportThread).where(SupportThread.status == ThreadStatus.OPEN, SupportThread.unread_for_staff > 0).order_by(SupportThread.last_message_at.desc()).limit(8)
        )
    ).scalars().unique().all()
    soon = datetime.now(UTC) + timedelta(hours=24)
    ending = (
        await db.execute(select(Auction).where(Auction.status == AuctionStatus.LIVE, Auction.ends_at <= soon).order_by(Auction.ends_at).limit(6))
    ).scalars().unique().all()
    from app.models import Product

    recent = (await db.execute(select(Order).order_by(Order.id.desc()).limit(8))).scalars().unique().all()
    out_of_stock = (
        await db.execute(select(Product).where(Product.is_active.is_(True), Product.stock - Product.reserved <= 0).order_by(Product.sort.desc()).limit(6))
    ).scalars().unique().all()
    # sparkline (solid line + translucent area, drawn in the template)
    daily = data["daily"]
    spark, spark_pts, spark_max = "", [], 0
    if daily:
        spark_max = max(c for _, c in daily) or 1
        w, h = 300, 60
        pts = [(i * (w / max(1, len(daily) - 1)), h - (c / spark_max) * (h - 8) - 4) for i, (_, c) in enumerate(daily)]
        spark = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        spark_pts = [(f"{x:.1f}", f"{y:.1f}", daily[i][0], daily[i][1]) for i, (x, y) in enumerate(pts)]
    return render(
        request, staff, "admin/dashboard.html",
        {"page_title": "Dashboard", "d": data, "days": days, "awaiting": awaiting, "awaiting_pay": awaiting_pay, "threads": threads, "ending": ending, "spark": spark, "spark_pts": spark_pts, "spark_max": spark_max, "recent": recent, "out_of_stock": out_of_stock, "badges": await nav_badges(db)},
    )
