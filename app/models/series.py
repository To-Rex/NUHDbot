from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Series(Base, TimestampMixin):
    """Catalogue dictionary: a product line of a brand (WD Purple, Seagate IronWolf) with its colour.

    Picking the series in the product form sets the product colour; staff can still change it per product.
    """

    __tablename__ = "series"
    __table_args__ = (UniqueConstraint("brand_id", "key", name="uq_series_brand_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    key: Mapped[str] = mapped_column(String(60))  # normalised name (upper, single spaces) for case-insensitive matching
    color: Mapped[str | None] = mapped_column(String(16))  # ProductColor value
    sort: Mapped[int] = mapped_column(Integer, default=0)
