from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import AuctionStatus, Condition, DepositStatus, TestStatus
from app.models.base import Base, TimestampMixin, str_enum, utcnow


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
    require_deposit: Mapped[bool] = mapped_column(Boolean, default=False)

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
        return f"/static/uploads/{self.filename}"

    @property
    def thumb_url(self) -> str:
        return f"/static/uploads/{self.thumb}"


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
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user = relationship("User", foreign_keys=[user_id], lazy="joined")
