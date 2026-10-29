from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class BrandModel(Base, TimestampMixin):
    """Catalogue dictionary: a drive model that belongs to a brand, entered in bulk by staff.

    Feeds the model autocomplete in the product form; the optional specs prefill a new product.
    """

    __tablename__ = "brand_models"
    __table_args__ = (UniqueConstraint("brand_id", "key", name="uq_brand_models_brand_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    key: Mapped[str] = mapped_column(String(120))  # normalised name (upper, single spaces) for case-insensitive uniqueness
    capacity_gb: Mapped[int | None] = mapped_column(Integer)
    interface: Mapped[str | None] = mapped_column(String(8))
    form_factor: Mapped[str | None] = mapped_column(String(4))
    series: Mapped[str | None] = mapped_column(String(60))
