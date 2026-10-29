from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import MessageKind, ThreadStatus
from app.models.base import Base, TimestampMixin, str_enum, utcnow
from app.services import storage  # noqa: I001


class SupportThread(Base, TimestampMixin):
    __tablename__ = "support_threads"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"), index=True)
    subject: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[ThreadStatus] = mapped_column(
        str_enum(ThreadStatus, 8), default=ThreadStatus.OPEN, index=True
    )
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    unread_for_staff: Mapped[int] = mapped_column(default=0)
    unread_for_customer: Mapped[int] = mapped_column(default=0)

    user = relationship("User", foreign_keys=[user_id], lazy="joined")
    order = relationship("Order", lazy="joined")
    messages: Mapped[list["SupportMessage"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", order_by="SupportMessage.id", lazy="selectin"
    )


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("support_threads.id", ondelete="CASCADE"), index=True)
    sender_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    from_staff: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[MessageKind] = mapped_column(str_enum(MessageKind, 10), default=MessageKind.TEXT)
    text: Mapped[str | None] = mapped_column(Text)
    attachment: Mapped[str | None] = mapped_column(String(255))  # local file under uploads
    tg_file_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    thread: Mapped[SupportThread] = relationship(back_populates="messages")
    sender = relationship("User", lazy="joined")

    @property
    def attachment_url(self) -> str | None:
        return storage.url(self.attachment)
