from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.services import storage  # noqa: I001


class Banner(Base, TimestampMixin):
    """A slide on the Mini App home slider: hot offer, sale, new stock or an announcement, managed by staff."""

    __tablename__ = "banners"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), default="hot")  # hot | sale | new | info
    title: Mapped[dict] = mapped_column(JSON, default=dict)  # {uz, uzl, ru, en, zh}
    subtitle: Mapped[dict] = mapped_column(JSON, default=dict)
    badge: Mapped[str | None] = mapped_column(String(24))  # "-15%", "Hit"
    color: Mapped[str] = mapped_column(String(16), default="red")
    image: Mapped[str | None] = mapped_column(String(255))
    image_thumb: Mapped[str | None] = mapped_column(String(255))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    product_ids: Mapped[list[int]] = mapped_column(JSON, default=list)  # several products → an offers page
    auto_sale: Mapped[bool] = mapped_column(Boolean, default=False)  # the offers page lists every discounted product
    link: Mapped[str | None] = mapped_column(String(255))  # a Mini App path (/app/...) when no product
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))  # shown struck through next to the product price
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=100)
    clicks: Mapped[int] = mapped_column(Integer, default=0)

    product = relationship("Product", lazy="selectin")

    @property
    def image_url(self) -> str | None:
        return storage.url(self.image)
