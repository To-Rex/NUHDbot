from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow, onupdate=utcnow
    )


def str_enum(enum_cls, length: int) -> Enum:
    """Portable string enum column that persists the enum *value* (e.g. 'live'), not the member name."""
    return Enum(enum_cls, native_enum=False, length=length, values_callable=lambda e: [m.value for m in e])
