from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import AuctionStatus, Condition, DepositStatus, PaymentMethodKind, TestStatus
from app.models.base import Base, TimestampMixin, str_enum, utcnow
from app.services import storage  # noqa: I001


class Auction(Base, TimestampMixin):
    __tablename__ = "auctions"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    brand: Mapped[str] = mapped_column(String(60))
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id", ondelete="SET NULL"))
    model: Mapped[str] = mapped_column(String(120))
    capacity_gb: Mapped[int] = mapped_column(Integer)
    condition: Mapped[Condition] = mapped_column(str_enum(Condition, 10))
    test_status: Mapped[TestStatus] = mapped_column(
        str_enum(TestStatus, 10), default=TestStatus.UNTESTED
    )
    qty: Mapped[int] = mapped_column(Integer)
    seller_warranty_months: Mapped[int] = mapped_column(Integer, default=0)
    factory_warranty_months: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[dict] = mapped_column(JSON, default=dict)

    currency: Mapped[str] = mapped_column(String(3), default="USD")
    start_price_total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    step_per_unit: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=1)
    current_price_total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    bids_count: Mapped[int] = mapped_column(Integer, default=0)
    deposit_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    deposit_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))  # set = the amount is this share of the start price
    require_deposit: Mapped[bool] = mapped_column(Boolean, default=False)
    location: Mapped[str | None] = mapped_column(String(2))  # where the drives are: a country code from the Geo settings (UZ, CN, …); None = not said
    location_name: Mapped[dict | None] = mapped_column(JSON)  # the country's name per language, copied when set
    location_city: Mapped[dict | None] = mapped_column(JSON)  # the city / region per language, copied when set (optional)

    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    original_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(40), default="Asia/Shanghai")
    status: Mapped[AuctionStatus] = mapped_column(
        str_enum(AuctionStatus, 10), default=AuctionStatus.DRAFT, index=True
    )
    winner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    winner_bid_id: Mapped[int | None] = mapped_column(Integer)
    result_order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    rules: Mapped[dict] = mapped_column(JSON, default=dict)  # {uz,ru,en} payment / dispute rules text
    version: Mapped[int] = mapped_column(Integer, default=0)  # bumps on each price change (SSE clients)

    product = relationship("Product", lazy="joined")
    images: Mapped[list["AuctionImage"]] = relationship(
        back_populates="auction", cascade="all, delete-orphan", order_by="AuctionImage.sort", lazy="selectin"
    )
    bids: Mapped[list["Bid"]] = relationship(
        back_populates="auction", cascade="all, delete-orphan", lazy="noload", order_by="Bid.id.desc()"
    )
    winner = relationship("User", foreign_keys=[winner_user_id], lazy="joined")

    @property
    def step_total(self) -> Decimal:
        return Decimal(self.step_per_unit) * self.qty

    @property
    def current_price_unit(self) -> Decimal:
        return (Decimal(self.current_price_total) / self.qty).quantize(Decimal("0.01"))

    @property
    def next_bid_total(self) -> Decimal:
        if self.bids_count == 0:
            return Decimal(self.start_price_total)
        return Decimal(self.current_price_total) + self.step_total

    @property
    def title(self) -> str:
        return f"{self.brand} {self.model}"

    @property
    def capacity_label(self) -> str:
        gb = self.capacity_gb or 0
        return f"{gb // 1000}TB" if gb >= 1000 and gb % 1000 == 0 else f"{gb}GB"

    @property
    def cover_url(self) -> str | None:
        if self.images:
            return self.images[0].url
        if self.product and self.product.cover:
            return self.product.cover.url
        return None


class AuctionImage(Base):
    __tablename__ = "auction_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    auction_id: Mapped[int] = mapped_column(ForeignKey("auctions.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    thumb: Mapped[str] = mapped_column(String(255))
    sort: Mapped[int] = mapped_column(Integer, default=0)

    auction: Mapped[Auction] = relationship(back_populates="images")

    @property
    def url(self) -> str:
        return storage.url(self.filename)

    @property
    def thumb_url(self) -> str:
        return storage.url(self.thumb)


class Bid(Base):
    __tablename__ = "bids"

    id: Mapped[int] = mapped_column(primary_key=True)
    auction_id: Mapped[int] = mapped_column(ForeignKey("auctions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount_total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    auction: Mapped[Auction] = relationship(back_populates="bids")
    user = relationship("User", lazy="joined")


class AuctionDeposit(Base):
    __tablename__ = "auction_deposits"

    id: Mapped[int] = mapped_column(primary_key=True)
    auction_id: Mapped[int] = mapped_column(ForeignKey("auctions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[DepositStatus] = mapped_column(
        str_enum(DepositStatus, 10), default=DepositStatus.PENDING
    )
    proof_filename: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)
    method_id: Mapped[int | None] = mapped_column(ForeignKey("payment_methods.id", ondelete="SET NULL"))  # how the customer says they paid
    admin_note: Mapped[str | None] = mapped_column(Text)  # the reason a receipt was rejected, shown to the customer
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user = relationship("User", foreign_keys=[user_id], lazy="joined")
    method = relationship("PaymentMethod", lazy="joined")
    reviewer = relationship("User", foreign_keys=[confirmed_by], lazy="joined")

    @property
    def proof_url(self) -> str | None:
        return storage.url(self.proof_filename)

    @property
    def proof_is_image(self) -> bool:
        return bool(self.proof_filename) and self.proof_filename.lower().endswith((".webp", ".jpg", ".jpeg", ".png"))

    @property
    def open(self) -> bool:
        """Pending or confirmed: the customer is in (or waiting); rejected and refunded ones are history."""
        return self.status in (DepositStatus.PENDING, DepositStatus.CONFIRMED, DepositStatus.APPLIED)


class PaymentMethod(Base, TimestampMixin):
    """A way to pay the shop — Alipay, WeChat Pay, a card, USDT… — with its QR code (a picture the admin uploaded, or one
    generated from a payment link / address) and the details to copy. Shown for auction deposits and/or order payments."""
    __tablename__ = "payment_methods"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[PaymentMethodKind] = mapped_column(str_enum(PaymentMethodKind, 12), default=PaymentMethodKind.OTHER)
    name: Mapped[str] = mapped_column(String(80))
    account: Mapped[str | None] = mapped_column(String(200))  # the number / address / holder to copy
    instructions: Mapped[dict] = mapped_column(JSON, default=dict)  # {lang: text}
    qr_filename: Mapped[str | None] = mapped_column(String(255))  # an uploaded QR picture
    qr_text: Mapped[str | None] = mapped_column(String(1000))  # or the text a QR is generated from
    currency: Mapped[str | None] = mapped_column(String(3))  # the currency this method takes (shown as a hint; empty = any)
    for_deposits: Mapped[bool] = mapped_column(Boolean, default=True)
    for_orders: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def qr_url(self) -> str | None:
        """Where the QR picture is: the uploaded file, or the generated one (served by the Mini App)."""
        if self.qr_filename:
            return storage.url(self.qr_filename)
        if self.qr_text:
            return f"/app/pay/qr/{self.id}.svg?v={int(self.updated_at.timestamp()) if self.updated_at else 0}"
        return None

    @property
    def has_qr(self) -> bool:
        return bool(self.qr_filename or self.qr_text)
