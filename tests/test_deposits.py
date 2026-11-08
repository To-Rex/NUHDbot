"""Auction deposits paid by QR: a share of the start price, the receipt sent and checked by the staff, the verdict announced on
the lot's live channel; payment methods with their QR codes."""
import asyncio
from decimal import Decimal

import pytest

from app.enums import DepositStatus, PaymentMethodKind
from app.models import PaymentMethod
from app.services import auctions
from app.services import payment_methods as pm
from tests.conftest import make_auction, make_user


def test_deposit_share_and_labels():
    assert auctions.deposit_for("500", 10) == Decimal("50.00")
    assert auctions.deposit_for("333.33", "12.5") == Decimal("41.67")
    assert auctions.pct_label(Decimal("10.00")) == "10" and auctions.pct_label(Decimal("12.50")) == "12.5" and auctions.pct_label(None) == ""


async def test_receipt_required_once_and_resend_after_rejection(db):
    u = await make_user(db, 41)
    staff = await make_user(db, 42)
    a = await make_auction(db)
    a.require_deposit, a.deposit_percent, a.deposit_amount = True, Decimal(10), auctions.deposit_for(a.start_price_total, 10)
    with pytest.raises(auctions.AuctionError) as e:  # no receipt, no deposit
        await auctions.claim_deposit(db, a, u, None, None)
    assert e.value.code == "proof_required"
    dep = await auctions.claim_deposit(db, a, u, "dep_1.webp", "paid via Alipay")
    assert dep.status == DepositStatus.PENDING and dep.amount == Decimal("50.00")
    with pytest.raises(auctions.AuctionError) as e:  # one open deposit per lot and customer
        await auctions.claim_deposit(db, a, u, "dep_2.webp", None)
    assert e.value.code == "deposit_exists"
    with pytest.raises(auctions.AuctionError) as e:  # bidding waits for the verdict
        await auctions.place_bid(db, a.id, u)
    assert e.value.code == "deposit_pending"
    # the staff rejects it with a reason: the customer may send another receipt
    before = await auctions.review_deposit(db, dep, staff, "reject", "the amount is 45, not 50")
    assert before == DepositStatus.PENDING and dep.status == DepositStatus.REJECTED and dep.admin_note == "the amount is 45, not 50" and dep.confirmed_by == staff.id
    dep2 = await auctions.claim_deposit(db, a, u, "dep_2.webp", None)
    assert dep2.id != dep.id and (await auctions.user_deposit(db, a.id, u.id)).id == dep2.id
    # confirmed: the bid goes through
    await auctions.review_deposit(db, dep2, staff, "confirm")
    assert auctions.deposit_ok(dep2)
    a2, bid, _ = await auctions.place_bid(db, a.id, u)
    assert bid.amount_total == a.start_price_total
    assert await auctions.pending_deposits_count(db) == 0
    with pytest.raises(auctions.AuctionError):
        await auctions.review_deposit(db, dep2, staff, "nonsense")


async def test_verdict_reaches_the_lot_channel(db):
    u = await make_user(db, 43)
    staff = await make_user(db, 44)
    a = await make_auction(db)
    a.require_deposit, a.deposit_amount = True, Decimal("50")
    dep = await auctions.claim_deposit(db, a, u, "dep_3.webp", None)
    q = auctions.subscribe(a.id)
    try:
        await auctions.review_deposit(db, dep, staff, "confirm")
        auctions.announce_deposit(dep)
        ev = await asyncio.wait_for(q.get(), 1)
        assert ev == {"type": "deposit", "id": a.id, "dep": dep.id, "status": "confirmed"}
    finally:
        auctions.unsubscribe(a.id, q)


async def test_payment_methods_and_qr(db):
    m1 = PaymentMethod(kind=PaymentMethodKind.ALIPAY, name="Alipay", account="138-0000-0000", qr_text="https://qr.alipay.com/abc", instructions={"en": "Scan and pay", "ru": "Отсканируйте"}, sort=20)
    m2 = PaymentMethod(kind=PaymentMethodKind.USDT, name="USDT", account="TXyz", for_deposits=False, sort=10)
    m3 = PaymentMethod(kind=PaymentMethodKind.OTHER, name="Hidden", is_active=False, sort=0)
    db.add_all([m1, m2, m3])
    await db.flush()
    assert [m.name for m in await pm.list_methods(db)] == ["USDT", "Alipay"]  # the admin's order, active only
    assert [m.name for m in await pm.list_methods(db, purpose="deposit")] == ["Alipay"]
    assert [m.name for m in await pm.list_methods(db, active_only=False)] == ["Hidden", "USDT", "Alipay"]
    assert pm.instructions(m1, "uzl") == "Scan and pay" and pm.instructions(m1, "ru") == "Отсканируйте" and pm.instructions(m2, "en") == ""
    assert m1.has_qr and m1.qr_url.startswith(f"/app/pay/qr/{m1.id}.svg") and not m2.has_qr
    svg = pm.qr_svg("https://qr.alipay.com/abc")
    assert svg.startswith(b"<svg") and b"#fff" in svg  # dark modules on a white ground
    assert pm.kind_of("WECHAT") == PaymentMethodKind.WECHAT and pm.kind_of("nope") == PaymentMethodKind.OTHER
    assert pm.icon(m1) == "scan" and pm.as_dict(m1)["qr"] == "generated"
