from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, utcnow


class Currency(Base, TimestampMixin):
    """A currency entered by staff with a manual rate. Prices stay in the product's own currency;
    the Mini App converts them for display into the currency the customer picked."""

    __tablename__ = "currencies"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(3), unique=True)  # USD, UZS — the value Product.currency holds
    name: Mapped[str] = mapped_column(String(40))  # "Dollar", "So'm"
    symbol: Mapped[str] = mapped_column(String(8))  # "$", "so'm"
    symbol_first: Mapped[bool] = mapped_column(Boolean, default=False)  # "$40" vs "40 so'm"
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal(1))  # units for 1 base currency
    rate_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), default=utcnow)  # when the rate was last typed in
    decimals: Mapped[int] = mapped_column(Integer, default=2)
    is_base: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=100)
