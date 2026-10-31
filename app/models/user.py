from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import STAFF_ROLES, Role
from app.models.base import Base, TimestampMixin, str_enum


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    tg_username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(100), default="")
    last_name: Mapped[str] = mapped_column(String(100), default="")
    phone: Mapped[str | None] = mapped_column(String(32), index=True)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    country: Mapped[str | None] = mapped_column(String(2))
    city: Mapped[str | None] = mapped_column(String(100))
    lang: Mapped[str] = mapped_column(String(8), default="uz")
    theme: Mapped[str] = mapped_column(String(8), default="auto")  # auto | light | dark
    nav_layout: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))  # staff sidebar order {"groups": {group: [item, ...]}}; JSONB keeps DISTINCT on users working
    bought_from_china_before: Mapped[bool | None] = mapped_column(Boolean)
    ads_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(64))  # ad campaign / group tag

    role: Mapped[Role] = mapped_column(str_enum(Role, 20), default=Role.CUSTOMER, index=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    # staff panel login (optional for customers)
    login: Mapped[str | None] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(128))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # remembered delivery details (prefilled at checkout)
    last_receiver_name: Mapped[str | None] = mapped_column(String(120))
    last_receiver_phone: Mapped[str | None] = mapped_column(String(32))
    last_address: Mapped[str | None] = mapped_column(Text)
    last_cargo_code: Mapped[str | None] = mapped_column(String(64))
    last_cargo_company: Mapped[str | None] = mapped_column(String(120))

    orders = relationship("Order", back_populates="user", lazy="noload")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() or (self.tg_username or f"#{self.id}")

    @property
    def is_registered(self) -> bool:
        return bool(self.registered_at and self.phone and self.first_name and self.country)

    @property
    def is_staff(self) -> bool:
        return self.role in STAFF_ROLES

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN
