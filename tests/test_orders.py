from decimal import Decimal

import pytest

from app.enums import ORDER_FLOW, OrderStatus, PaymentKind
from app.models import Product
from app.services import orders
from tests.conftest import make_product, make_user

DELIVERY = dict(receiver_name="Ali", receiver_phone="+998901234567", country="UZ", city="Toshkent", address="Chilonzor 1", cargo_company="Cargo", cargo_code="00750ВВ", customer_note=None)


async def test_create_order_reserves_stock_and_keeps_cargo_code_verbatim(db):
    u = await make_user(db)
    p = await make_product(db, stock=50, min_order=5)
    o = await orders.create_order(db, u, [(p.id, 10)], **DELIVERY)
    await db.commit()
    await db.refresh(p)
    assert o.status == OrderStatus.AWAITING_ADMIN
    assert o.number.startswith("NU-")
    assert p.reserved == 10 and p.available == 40
    assert o.total == Decimal("400")
    assert o.cargo_code == "00750ВВ"  # leading zeros + Cyrillic preserved
    assert o.advance_amount == Decimal("120.00") and o.balance_amount == Decimal("280.00")
    assert [h.to_status for h in o.history] == [OrderStatus.NEW, OrderStatus.AWAITING_ADMIN]


async def test_below_min_and_over_stock_and_full_box(db):
    u = await make_user(db)
    p = await make_product(db, stock=12, min_order=5, full_box_only=True, box_qty=10)
    with pytest.raises(orders.OrderError) as e:
        await orders.create_order(db, u, [(p.id, 3)], **DELIVERY)
    assert e.value.code == "below_min"
    with pytest.raises(orders.OrderError) as e:
        await orders.create_order(db, u, [(p.id, 15)], **DELIVERY)
    assert e.value.code == "full_box_only"
    with pytest.raises(orders.OrderError) as e:
        await orders.create_order(db, u, [(p.id, 20)], **DELIVERY)
    assert e.value.code in ("full_box_only", "not_enough_stock")
    p2 = await make_product(db, stock=8, min_order=1)
    with pytest.raises(orders.OrderError) as e:
        await orders.create_order(db, u, [(p2.id, 9)], **DELIVERY)
    assert e.value.code == "not_enough_stock"


async def test_unregistered_user_cannot_order(db):
    u = await make_user(db, registered=False)
    p = await make_product(db)
    with pytest.raises(orders.OrderError) as e:
        await orders.create_order(db, u, [(p.id, 5)], **DELIVERY)
    assert e.value.code == "not_registered"


async def test_cancel_releases_reservation_and_ship_decrements_stock(db):
    u = await make_user(db)
    admin = await make_user(db, tg_id=1, role=__import__("app.enums", fromlist=["Role"]).Role.ADMIN)
    p = await make_product(db, stock=50)
    o1 = await orders.create_order(db, u, [(p.id, 10)], **DELIVERY)
    await orders.transition(db, o1, OrderStatus.CANCELLED, by=admin)
    await db.commit()
    await db.refresh(p)
    assert p.reserved == 0 and p.stock == 50

    o2 = await orders.create_order(db, u, [(p.id, 10)], **DELIVERY)
    for st in (OrderStatus.AWAITING_ADVANCE, OrderStatus.ADVANCE_CONFIRMED, OrderStatus.TESTING, OrderStatus.TEST_READY, OrderStatus.AWAITING_CUSTOMER,
               OrderStatus.AWAITING_BALANCE, OrderStatus.PAID, OrderStatus.PACKING, OrderStatus.SHIPPED):
        await orders.transition(db, o2, st, by=admin)
    await db.commit()
    p = await db.get(Product, p.id)
    await db.refresh(p)
    assert p.stock == 40 and p.reserved == 0
    assert o2.shipped_at is not None


async def test_transitions_follow_flow(db):
    u = await make_user(db)
    admin = await make_user(db, tg_id=2, role=__import__("app.enums", fromlist=["Role"]).Role.ADMIN)
    p = await make_product(db)
    o = await orders.create_order(db, u, [(p.id, 5)], **DELIVERY)
    with pytest.raises(orders.OrderError) as e:
        await orders.transition(db, o, OrderStatus.SHIPPED, by=admin)
    assert e.value.code == "transition_not_allowed"
    allowed = orders.allowed_transitions(o, is_admin=True)
    assert OrderStatus.AWAITING_ADVANCE in allowed and OrderStatus.CANCELLED in allowed and OrderStatus.DISPUTED in allowed
    assert ORDER_FLOW[OrderStatus.AWAITING_ADMIN] == (OrderStatus.AWAITING_ADVANCE,)
    # customer accepts offer -> advance stage
    await orders.customer_confirm_offer(db, o, u)
    assert o.status == OrderStatus.AWAITING_ADVANCE and o.confirmed_at is not None


async def test_recorded_payments_move_status(db):
    """Receipts are settled in chat; staff record what arrived and the stage follows the money."""
    u = await make_user(db)
    finance = await make_user(db, tg_id=3, role=__import__("app.enums", fromlist=["Role"]).Role.FINANCE)
    p = await make_product(db)
    o = await orders.create_order(db, u, [(p.id, 5)], **DELIVERY)
    await orders.customer_confirm_offer(db, o, u)
    pay = await orders.add_payment(db, o, u, PaymentKind.ADVANCE, o.advance_amount, "USDT", None, None)
    await orders.confirm_payment(db, pay, finance, ok=True)
    assert o.status == OrderStatus.ADVANCE_CONFIRMED and o.paid_amount == o.advance_amount
    for st in (OrderStatus.TESTING, OrderStatus.TEST_READY, OrderStatus.AWAITING_CUSTOMER):
        await orders.transition(db, o, st, by=finance)
    # staff move the order on once the customer agrees in chat
    await orders.transition(db, o, OrderStatus.AWAITING_BALANCE, by=finance)
    assert o.status == OrderStatus.AWAITING_BALANCE
    part = await orders.add_payment(db, o, u, PaymentKind.BALANCE, o.balance_amount / 2, "USDT", None, None)
    await orders.confirm_payment(db, part, finance, ok=True)
    assert o.status == OrderStatus.AWAITING_BALANCE and part.stage_complete is False
    rest = await orders.add_payment(db, o, u, PaymentKind.BALANCE, o.total - o.paid_amount, "USDT", None, None)
    await orders.confirm_payment(db, rest, finance, ok=True)
    assert o.status == OrderStatus.PAID and o.paid_amount == o.total
