from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Brand(Base, TimestampMixin):
    """Catalogue dictionary: HDD manufacturer / label brand managed from the admin panel."""

    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    logo: Mapped[str | None] = mapped_column(String(255))
    logo_thumb: Mapped[str | None] = mapped_column(String(255))
    series: Mapped[list[str]] = mapped_column(JSON, default=list)
    description: Mapped[dict] = mapped_column(JSON, default=dict)  # {uz,uzl,ru,en,zh}
    warranty_url: Mapped[str | None] = mapped_column(Text)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    @property
    def logo_url(self) -> str | None:
        return f"/static/uploads/{self.logo}" if self.logo else None

    @property
    def logo_thumb_url(self) -> str | None:
        return f"/static/uploads/{self.logo_thumb}" if self.logo_thumb else None

    @property
    def monogram(self) -> str:
        parts = [w for w in self.name.replace("/", " ").split() if w]
        return "".join(w[0] for w in parts[:2]).upper() or "?"
