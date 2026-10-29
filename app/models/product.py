from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import Condition, FormFactor, ImageKind, Interface, TestStatus
from app.models.base import Base, TimestampMixin, str_enum, utcnow
from app.services import storage  # noqa: I001


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    brand: Mapped[str] = mapped_column(String(60), index=True)  # denormalised display name (kept in sync with brand_id)
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id", ondelete="SET NULL"), index=True)
    model: Mapped[str] = mapped_column(String(120), index=True)  # real hardware model
    label_model: Mapped[str | None] = mapped_column(String(120))  # model printed on the label (Refresh)
    series: Mapped[str | None] = mapped_column(String(60))  # e.g. Purple, SkyHawk
    capacity_gb: Mapped[int] = mapped_column(Integer, index=True)
    interface: Mapped[Interface] = mapped_column(str_enum(Interface, 8), default=Interface.SATA)
    form_factor: Mapped[FormFactor] = mapped_column(str_enum(FormFactor, 4), default=FormFactor.F35)
    condition: Mapped[Condition] = mapped_column(str_enum(Condition, 10), index=True)
    purposes: Mapped[list[str]] = mapped_column(JSON, default=list)
    rpm: Mapped[int | None] = mapped_column(Integer)
    cache_mb: Mapped[int | None] = mapped_column(Integer)

    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    cost_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))  # for net profit, staff only
    stock: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)
    min_order: Mapped[int] = mapped_column(Integer, default=1)
    box_qty: Mapped[int | None] = mapped_column(Integer)
    full_box_only: Mapped[bool] = mapped_column(Boolean, default=False)

    seller_warranty_months: Mapped[int] = mapped_column(Integer, default=0)
    factory_warranty_months: Mapped[int] = mapped_column(Integer, default=0)
    test_status: Mapped[TestStatus] = mapped_column(
        str_enum(TestStatus, 10), default=TestStatus.UNTESTED
    )
    hours_used: Mapped[int | None] = mapped_column(Integer)
    health: Mapped[str | None] = mapped_column(String(40))
    test_summary: Mapped[dict] = mapped_column(JSON, default=dict)  # {uz,ru,en}

    description: Mapped[dict] = mapped_column(JSON, default=dict)  # {uz,ru,en}
    compatibility: Mapped[dict] = mapped_column(JSON, default=dict)  # {uz,ru,en}
    specs: Mapped[dict] = mapped_column(JSON, default=dict)  # free key/value
    delivery_note: Mapped[dict] = mapped_column(JSON, default=dict)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sale_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    views: Mapped[int] = mapped_column(Integer, default=0)

    brand_ref = relationship("Brand", lazy="selectin")
    images: Mapped[list["ProductImage"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", order_by="ProductImage.sort", lazy="selectin"
    )

    @property
    def available(self) -> int:
        return max(0, (self.stock or 0) - (self.reserved or 0))

    @property
    def cover(self) -> "ProductImage | None":
        for img in self.images:
            if img.is_cover:
                return img
        return self.images[0] if self.images else None

    @property
    def title(self) -> str:
        return f"{self.brand} {self.model}"

    @property
    def capacity_label(self) -> str:
        gb = self.capacity_gb or 0
        return f"{gb // 1000}TB" if gb >= 1000 and gb % 1000 == 0 else (f"{gb / 1000:g}TB" if gb >= 1000 else f"{gb}GB")


class ProductImage(Base):
    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    thumb: Mapped[str] = mapped_column(String(255))
    kind: Mapped[ImageKind] = mapped_column(str_enum(ImageKind, 8), default=ImageKind.SAMPLE)
    is_cover: Mapped[bool] = mapped_column(Boolean, default=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    product: Mapped[Product] = relationship(back_populates="images")

    @property
    def url(self) -> str:
        return storage.url(self.filename)

    @property
    def thumb_url(self) -> str:
        return storage.url(self.thumb)


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    new_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
