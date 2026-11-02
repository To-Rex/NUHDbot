"""The admin assistant: a chat with an LLM that runs the shop through tools, and a journal of what it changed.

A chat belongs to one staff member. Every tool call that changed data is an AssistantAction with a journal of the
rows it touched (before / after images), so the change can be put back for UNDO_DAYS; files a deletion freed are
kept until the window closes.
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utcnow

UNDO_DAYS = 3


class AssistantChat(Base, TimestampMixin):
    __tablename__ = "assistant_chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="")

    messages: Mapped[list["AssistantMessage"]] = relationship(back_populates="chat", cascade="all, delete-orphan", order_by="AssistantMessage.id", lazy="selectin")


class AssistantMessage(Base):
    """One line of the conversation as the model sees it: user, assistant (maybe with tool calls) or a tool result."""

    __tablename__ = "assistant_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("assistant_chats.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(12))  # user | assistant | tool
    content: Mapped[str | None] = mapped_column(Text)
    tool_calls: Mapped[list | None] = mapped_column(JSON)  # assistant: [{id, type, function: {name, arguments}}]
    tool_call_id: Mapped[str | None] = mapped_column(String(64))  # tool: which call this answers
    name: Mapped[str | None] = mapped_column(String(64))  # tool: the tool's name
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    chat: Mapped[AssistantChat] = relationship(back_populates="messages")


class AssistantAction(Base):
    """A change the assistant made, with everything needed to put it back."""

    __tablename__ = "assistant_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int | None] = mapped_column(ForeignKey("assistant_chats.id", ondelete="SET NULL"), index=True)
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    tool: Mapped[str] = mapped_column(String(64))
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(String(300), default="")
    entity: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(40))
    journal: Mapped[list] = mapped_column(JSON, default=list)  # [{kind: update|create|delete, table, pk, before, after, children}]
    files: Mapped[list] = mapped_column(JSON, default=list)  # storage files a deletion freed; removed once the undo window closes
    status: Mapped[str] = mapped_column(String(12), default="done")  # done | undone | failed
    note: Mapped[str | None] = mapped_column(Text)  # what undo could not put back, if anything
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    undo_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    step: Mapped[int] = mapped_column(Integer, default=0)  # order inside one assistant turn

    @property
    def can_undo(self) -> bool:
        return self.status == "done" and bool(self.journal) and self.undo_until > utcnow()
