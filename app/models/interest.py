from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow


class InterestEvent(Base):
    """One sign of a customer's interest: a product opened, a search or filter in the catalogue, a product put in the cart,
    ordered, a bid on a lot, a subscription. Kept for good (the demand analysis grows with time); the product's traits are
    copied so the event keeps its meaning when the product changes or goes."""

    __tablename__ = "interest_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(12), index=True)  # view | search | filter | cart | order | bid | subscribe
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), index=True)
    brand: Mapped[str | None] = mapped_column(String(60), index=True)
    model: Mapped[str | None] = mapped_column(String(120))
    capacity_gb: Mapped[int | None] = mapped_column(Integer, index=True)
    condition: Mapped[str | None] = mapped_column(String(10))
    purposes: Mapped[list | None] = mapped_column(JSON)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))  # the product's price at the time (base currency)
    qty: Mapped[int | None] = mapped_column(Integer)  # cart / order quantity, bid amount is not kept here
    query: Mapped[str | None] = mapped_column(String(200))  # the search text, or the filters as text
    results: Mapped[int | None] = mapped_column(Integer)  # what the search / filter found (0 = a gap in the catalogue)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    user = relationship("User", lazy="noload")
    product = relationship("Product", lazy="noload")
