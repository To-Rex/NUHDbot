import csv
import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ACTIVE_ORDER_STATUSES, AuctionStatus, OrderStatus, PaymentKind, PaymentStatus
from app.models import Auction, Order, OrderItem, Payment, Product, User


async def dashboard(db: AsyncSession, days: int = 30) -> dict:
    since = datetime.now(UTC) - timedelta(days=days)
    orders_total = (await db.execute(select(func.count()).select_from(Order).where(Order.created_at >= since))).scalar_one()
    active = (await db.execute(select(func.count()).select_from(Order).where(Order.status.in_(ACTIVE_ORDER_STATUSES)))).scalar_one()
    awaiting_admin = (await db.execute(select(func.count()).select_from(Order).where(Order.status == OrderStatus.AWAITING_ADMIN))).scalar_one()
    revenue = (
        await db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.status == PaymentStatus.CONFIRMED, Payment.kind.in_([PaymentKind.ADVANCE, PaymentKind.BALANCE]), Payment.created_at >= since
            )
        )
    ).scalar_one()
    advances = (
        await db.execute(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.status == PaymentStatus.CONFIRMED, Payment.kind == PaymentKind.ADVANCE))
    ).scalar_one()
    refunds = (
        await db.execute(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.status == PaymentStatus.CONFIRMED, Payment.kind == PaymentKind.REFUND))
    ).scalar_one()
    awaiting_balance_sum = Decimal(0)
    for o in (await db.execute(select(Order).where(Order.status == OrderStatus.AWAITING_BALANCE))).scalars().unique().all():
        awaiting_balance_sum += o.balance_amount
    disks_sold = (
        await db.execute(
            select(func.coalesce(func.sum(OrderItem.qty), 0)).join(Order).where(Order.status.in_([OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.COMPLETED]))
        )
    ).scalar_one()
    customers = (await db.execute(select(func.count()).select_from(User).where(User.registered_at.is_not(None)))).scalar_one()
    products = (await db.execute(select(func.count()).select_from(Product).where(Product.is_active.is_(True)))).scalar_one()
    low_stock = (await db.execute(select(func.count()).select_from(Product).where(Product.is_active.is_(True), Product.stock - Product.reserved <= 0))).scalar_one()
    live_auctions = (await db.execute(select(func.count()).select_from(Auction).where(Auction.status == AuctionStatus.LIVE))).scalar_one()
    by_brand = (
        await db.execute(
            select(OrderItem.brand, func.sum(OrderItem.qty), func.sum(OrderItem.qty * OrderItem.unit_price))
            .join(Order)
            .where(Order.status.in_([OrderStatus.PAID, OrderStatus.PACKING, OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.COMPLETED]))
            .group_by(OrderItem.brand)
            .order_by(func.sum(OrderItem.qty).desc())
        )
    ).all()
    by_capacity = (
        await db.execute(
            select(OrderItem.capacity_gb, func.sum(OrderItem.qty))
            .join(Order)
            .where(Order.status.in_([OrderStatus.PAID, OrderStatus.PACKING, OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.COMPLETED]))
            .group_by(OrderItem.capacity_gb)
            .order_by(OrderItem.capacity_gb)
        )
    ).all()
    # daily orders for sparkline
    day = func.date_trunc("day", Order.created_at).label("day")
    daily = (await db.execute(select(day, func.count()).where(Order.created_at >= since).group_by(day).order_by(day))).all()
    return {
        "days": days,
        "orders_total": orders_total,
        "active_orders": active,
        "awaiting_admin": awaiting_admin,
        "revenue": Decimal(revenue),
        "advances": Decimal(advances),
        "refunds": Decimal(refunds),
        "awaiting_balance_sum": awaiting_balance_sum,
        "disks_sold": int(disks_sold),
        "customers": customers,
        "products": products,
        "low_stock": low_stock,
        "live_auctions": live_auctions,
        "by_brand": [(b, int(q), Decimal(s or 0)) for b, q, s in by_brand],
        "by_capacity": [(g, int(q)) for g, q in by_capacity],
        "daily": [(d.date().isoformat(), int(c)) for d, c in daily],
    }


async def profit_report(db: AsyncSession) -> list[dict]:
    """Net profit only where cost price is known (30.11)."""
    rows = (
        await db.execute(
            select(OrderItem, Product.cost_price)
            .join(Order)
            .outerjoin(Product, Product.id == OrderItem.product_id)
            .where(Order.status.in_([OrderStatus.PAID, OrderStatus.PACKING, OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.COMPLETED]))
        )
    ).all()
    out = []
    for item, cost in rows:
        revenue = Decimal(item.unit_price) * item.qty
        profit = (Decimal(item.unit_price) - Decimal(cost)) * item.qty if cost is not None else None
        out.append({"order_id": item.order_id, "title": f"{item.brand} {item.model}", "qty": item.qty, "revenue": revenue, "profit": profit})
    return out


async def orders_csv(db: AsyncSession) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["number", "created_at", "status", "customer", "phone", "country", "city", "items", "qty", "total", "currency", "paid", "cargo_code"])
    for o in (await db.execute(select(Order).order_by(Order.id.desc()))).scalars().unique().all():
        w.writerow([
            o.number, o.created_at.isoformat(timespec="minutes"), o.status, o.user.full_name if o.user else "", o.receiver_phone, o.country or "", o.city or "",
            "; ".join(f"{i.brand} {i.model} x{i.qty}" for i in o.items), o.total_qty, o.total, o.currency, o.paid_amount, o.cargo_code or "",
        ])
    return buf.getvalue()


async def customers_csv(db: AsyncSession) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "name", "phone", "country", "city", "lang", "registered_at", "orders", "source"])
    users = (await db.execute(select(User).where(User.registered_at.is_not(None)).order_by(User.id))).scalars().all()
    counts = dict((await db.execute(select(Order.user_id, func.count()).group_by(Order.user_id))).all())
    for u in users:
        w.writerow([u.id, u.full_name, u.phone or "", u.country or "", u.city or "", u.lang, u.registered_at.date().isoformat() if u.registered_at else "", counts.get(u.id, 0), u.source or ""])
    return buf.getvalue()
