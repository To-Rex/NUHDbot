from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import Condition, OrderStatus, PaymentKind, PaymentStatus
from app.models.base import Base, TimestampMixin, str_enum, utcnow


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[OrderStatus] = mapped_column(
        str_enum(OrderStatus, 24), default=OrderStatus.NEW, index=True
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)  # admin-confirmed final amount
    advance_percent: Mapped[int] = mapped_column(Integer, default=30)

    receiver_name: Mapped[str] = mapped_column(String(120), default="")
    receiver_phone: Mapped[str] = mapped_column(String(32), default="")
    country: Mapped[str | None] = mapped_column(String(2))
    city: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str] = mapped_column(Text, default="")
    cargo_company: Mapped[str | None] = mapped_column(String(120))
    cargo_code: Mapped[str | None] = mapped_column(String(64))  # stored verbatim, never normalized
    customer_note: Mapped[str | None] = mapped_column(Text)
    admin_note: Mapped[str | None] = mapped_column(Text)
    tracking_number: Mapped[str | None] = mapped_column(String(120))
    delivery_terms: Mapped[str | None] = mapped_column(Text)
    warranty_terms: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(64))

    user = relationship("User", back_populates="orders", lazy="joined")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin", order_by="OrderItem.id"
    )
    history: Mapped[list["OrderStatusHistory"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin", order_by="OrderStatusHistory.id"
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin", order_by="Payment.id"
    )

    @property
    def total_qty(self) -> int:
        return sum(i.qty for i in self.items)

    @property
    def advance_amount(self) -> Decimal:
        return (Decimal(self.total or 0) * Decimal(self.advance_percent) / Decimal(100)).quantize(Decimal("0.01"))

    @property
    def balance_amount(self) -> Decimal:
        return (Decimal(self.total or 0) - self.advance_amount).quantize(Decimal("0.01"))

    @property
    def paid_amount(self) -> Decimal:
        return sum(
            (Decimal(p.amount) for p in self.payments if p.status == PaymentStatus.CONFIRMED and p.kind != PaymentKind.REFUND),
            Decimal(0),
        )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    brand: Mapped[str] = mapped_column(String(60))
    model: Mapped[str] = mapped_column(String(120))
    capacity_gb: Mapped[int] = mapped_column(Integer)
    condition: Mapped[Condition] = mapped_column(str_enum(Condition, 10))
    qty: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    serials: Mapped[list[str]] = mapped_column(JSON, default=list)  # serial numbers actually shipped
    test_note: Mapped[str | None] = mapped_column(Text)

    order: Mapped[Order] = relationship(back_populates="items")
    product = relationship("Product", lazy="joined")

    @property
    def line_total(self) -> Decimal:
        return Decimal(self.unit_price) * self.qty


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24))
    by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    order: Mapped[Order] = relationship(back_populates="history")
    by_user = relationship("User", lazy="joined")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[PaymentKind] = mapped_column(str_enum(PaymentKind, 10))
    status: Mapped[PaymentStatus] = mapped_column(
        str_enum(PaymentStatus, 10), default=PaymentStatus.PENDING
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    method: Mapped[str | None] = mapped_column(String(60))
    proof_filename: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    order: Mapped[Order | None] = relationship(back_populates="payments")
