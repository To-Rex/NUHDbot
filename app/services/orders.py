from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ACTIVE_ORDER_STATUSES, ORDER_FLOW, OrderStatus, PaymentKind, PaymentStatus
from app.models import Order, OrderItem, OrderStatusHistory, Payment, Product, User
from app.services import audit


class OrderError(Exception):
    def __init__(self, code: str, **ctx):
        super().__init__(code)
        self.code = code
        self.ctx = ctx


async def next_order_number(db: AsyncSession) -> str:
    now = datetime.now(UTC)
    prefix = f"NU-{now:%y%m}-"
    count = (await db.execute(select(func.count()).select_from(Order).where(Order.number.like(prefix + "%")))).scalar_one()
    return f"{prefix}{count + 1:04d}"


async def validate_line(db: AsyncSession, product_id: int, qty: int) -> Product:
    p = await db.get(Product, product_id)
    if p is None or not p.is_active or not p.sale_allowed:
        raise OrderError("product_unavailable")
    if qty < 1:
        raise OrderError("qty_invalid")
    if qty < p.min_order:
        raise OrderError("below_min", min_order=p.min_order, product=p.title)
    if p.full_box_only and p.box_qty and qty % p.box_qty != 0:
        raise OrderError("full_box_only", box_qty=p.box_qty, product=p.title)
    if qty > p.available:
        raise OrderError("not_enough_stock", available=p.available, product=p.title)
    return p


async def create_order(
    db: AsyncSession,
    user: User,
    lines: list[tuple[int, int]],
    *,
    receiver_name: str,
    receiver_phone: str,
    country: str | None,
    city: str | None,
    address: str,
    cargo_company: str | None,
    cargo_code: str | None,
    customer_note: str | None,
    source: str | None = None,
) -> Order:
    if not lines:
        raise OrderError("empty_cart")
    if not user.is_registered:
        raise OrderError("not_registered")
    order = Order(
        number=await next_order_number(db),
        user_id=user.id,
        status=OrderStatus.NEW,
        receiver_name=receiver_name.strip()[:120],
        receiver_phone=receiver_phone.strip()[:32],
        country=country,
        city=city,
        address=address.strip(),
        cargo_company=(cargo_company or "").strip()[:120] or None,
        cargo_code=(cargo_code or "").strip()[:64] or None,  # verbatim; leading zeros and alphabet preserved
        customer_note=(customer_note or "").strip() or None,
        source=source or user.source,
    )
    subtotal = Decimal(0)
    currency = None
    for product_id, qty in lines:
        p = await validate_line(db, product_id, qty)
        # atomic reservation: only succeeds if stock still available
        res = await db.execute(
            update(Product)
            .where(Product.id == p.id, Product.stock - Product.reserved >= qty)
            .values(reserved=Product.reserved + qty)
        )
        if res.rowcount != 1:
            raise OrderError("not_enough_stock", available=p.available, product=p.title)
        unit = Decimal(p.price or 0)
        currency = currency or p.currency
        order.items.append(
            OrderItem(
                product_id=p.id,
                brand=p.brand,
                model=p.model,
                capacity_gb=p.capacity_gb,
                condition=p.condition,
                qty=qty,
                unit_price=unit,
            )
        )
        subtotal += unit * qty
    order.currency = currency or "USD"
    order.subtotal = subtotal
    order.total = subtotal
    order.history.append(OrderStatusHistory(from_status=None, to_status=OrderStatus.NEW, by_user_id=user.id))
    order.payments = []  # initialise the collection so later access never needs an implicit (async-unsafe) lazy load
    db.add(order)
    # remember delivery details for the next checkout
    user.last_receiver_name = order.receiver_name
    user.last_receiver_phone = order.receiver_phone
    user.last_address = order.address
    user.last_cargo_code = order.cargo_code
    user.last_cargo_company = order.cargo_company
    await db.flush()
    # move straight into "awaiting admin" so the customer sees the real state
    await transition(db, order, OrderStatus.AWAITING_ADMIN, by=user, note=None, force=True)
    return order


def allowed_transitions(order: Order, *, is_admin: bool) -> list[OrderStatus]:
    nxt = list(ORDER_FLOW.get(order.status, ()))
    if order.status in ACTIVE_ORDER_STATUSES and order.status not in (OrderStatus.CANCELLED,):
        for extra in (OrderStatus.CANCELLED, OrderStatus.DISPUTED):
            if extra not in nxt and extra != order.status:
                nxt.append(extra)
    return nxt


async def transition(
    db: AsyncSession,
    order: Order,
    to_status: OrderStatus,
    *,
    by: User | None,
    note: str | None = None,
    force: bool = False,
) -> Order:
    if order.status == to_status:
        return order
    if not force and to_status not in allowed_transitions(order, is_admin=bool(by and by.is_admin)):
        raise OrderError("transition_not_allowed", from_status=order.status, to_status=to_status)
    before = order.status
    now = datetime.now(UTC)
    # side effects on stock
    if to_status in (OrderStatus.CANCELLED, OrderStatus.RETURNED) and before not in (
        OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.RETURNED
    ):
        for it in order.items:
            if it.product_id:
                await db.execute(
                    update(Product).where(Product.id == it.product_id).values(reserved=func.greatest(Product.reserved - it.qty, 0))
                )
    if to_status == OrderStatus.SHIPPED and before != OrderStatus.SHIPPED:
        for it in order.items:
            if it.product_id:
                await db.execute(
                    update(Product)
                    .where(Product.id == it.product_id)
                    .values(stock=func.greatest(Product.stock - it.qty, 0), reserved=func.greatest(Product.reserved - it.qty, 0))
                )
        order.shipped_at = now
    if to_status == OrderStatus.AWAITING_ADVANCE and not order.confirmed_at:
        order.confirmed_at = now
    order.status = to_status
    order.history.append(OrderStatusHistory(from_status=before, to_status=to_status, by_user_id=by.id if by else None, note=note))
    await audit.log(db, by.id if by else None, "order.status", "order", order.id, {"status": before}, {"status": to_status, "note": note})
    await db.flush()
    return order


async def customer_confirm_offer(db: AsyncSession, order: Order, user: User) -> Order:
    """Customer agrees to the admin's final offer -> advance stage (16.08)."""
    if order.user_id != user.id or order.status != OrderStatus.AWAITING_ADMIN:
        raise OrderError("cannot_confirm")
    return await transition(db, order, OrderStatus.AWAITING_ADVANCE, by=user, note="customer accepted offer", force=True)


async def add_payment(
    db: AsyncSession, order: Order, user: User, kind: PaymentKind, amount: Decimal, method: str | None, proof: str | None, note: str | None
) -> Payment:
    """A payment row for the order. Staff record money they have received (the receipt itself is settled in chat)."""
    pay = Payment(
        order=order, user_id=user.id, kind=kind, amount=amount, currency=order.currency, method=method, proof_filename=proof, note=note
    )
    db.add(pay)
    await db.flush()
    return pay


async def confirm_payment(db: AsyncSession, pay: Payment, staff: User, ok: bool, note: str | None = None) -> Payment:
    pay.status = PaymentStatus.CONFIRMED if ok else PaymentStatus.REJECTED
    pay.confirmed_by = staff.id
    pay.confirmed_at = datetime.now(UTC)
    if note:
        pay.note = (pay.note + "\n" if pay.note else "") + note
    await audit.log(db, staff.id, "payment.confirm" if ok else "payment.reject", "payment", pay.id, None, {"amount": str(pay.amount)})
    pay.stage_complete = True  # informational for the caller: did this confirmation complete the current payment stage?
    if ok and pay.order is not None:
        order = pay.order
        paid = order.paid_amount
        if order.status == OrderStatus.AWAITING_ADVANCE:
            if paid >= order.advance_amount:
                await transition(db, order, OrderStatus.ADVANCE_CONFIRMED, by=staff, note="advance confirmed")
            else:
                pay.stage_complete = False
        elif order.status == OrderStatus.AWAITING_BALANCE:
            if paid >= Decimal(order.total or 0):
                await transition(db, order, OrderStatus.PAID, by=staff, note="balance confirmed")
            else:
                pay.stage_complete = False
    await db.flush()
    return pay


async def user_orders(db: AsyncSession, user_id: int, *, active: bool | None = None) -> list[Order]:
    stmt = select(Order).where(Order.user_id == user_id)
    if active is True:
        stmt = stmt.where(Order.status.in_(ACTIVE_ORDER_STATUSES))
    elif active is False:
        stmt = stmt.where(Order.status.not_in(ACTIVE_ORDER_STATUSES))
    stmt = stmt.order_by(Order.id.desc())
    return list((await db.execute(stmt)).scalars().unique().all())


async def get_order_for_user(db: AsyncSession, order_id: int, user_id: int) -> Order | None:
    o = await db.get(Order, order_id)
    return o if o and o.user_id == user_id else None
