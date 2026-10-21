"""Các bảng dữ liệu (SQLAlchemy 2.0)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EXPENSE = "expense"
PAYMENT = "payment"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """SQLite trả datetime không kèm múi giờ; coi như UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    """Người dùng Zalo đã nhắn tin với bot."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100))
    # Không đặt khóa ngoại để tránh vòng users <-> ledgers; code tự kiểm tra.
    active_ledger_id: Mapped[int | None] = mapped_column(Integer, default=None)
    bank_id: Mapped[str | None] = mapped_column(String(20), default=None)
    bank_account: Mapped[str | None] = mapped_column(String(20), default=None)
    bank_holder: Mapped[str | None] = mapped_column(String(50), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Ledger(Base):
    """Một sổ chi tiêu chung. Sổ của nhóm chat Zalo có group_chat_id."""

    __tablename__ = "ledgers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    invite_code: Mapped[str] = mapped_column(String(12), unique=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    group_chat_id: Mapped[str | None] = mapped_column(String(64), unique=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Member(Base):
    """Một cái tên trong sổ; có thể gắn với user Zalo hoặc chỉ là tên."""

    __tablename__ = "members"
    __table_args__ = (
        UniqueConstraint("ledger_id", "norm_name"),
        UniqueConstraint("ledger_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ledger_id: Mapped[int] = mapped_column(ForeignKey("ledgers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(50))
    norm_name: Mapped[str] = mapped_column(String(50))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Transaction(Base):
    """Một khoản chi (expense) hoặc một lần trả nợ (payment).

    Trả nợ A -> B được lưu như khoản do A trả và B chịu toàn bộ,
    nhờ vậy số dư chỉ cần một công thức: đã trả - phải chịu.
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    ledger_id: Mapped[int] = mapped_column(ForeignKey("ledgers.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    payer_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    amount: Mapped[int] = mapped_column(BigInteger)
    description: Mapped[str] = mapped_column(String(200))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    payer: Mapped[Member] = relationship(lazy="joined")
    shares: Mapped[list[Share]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Share.id",
    )


class Share(Base):
    """Phần tiền một thành viên phải chịu trong một khoản."""

    __tablename__ = "shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), index=True
    )
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)

    transaction: Mapped[Transaction] = relationship(back_populates="shares")
    member: Mapped[Member] = relationship(lazy="joined")


class ProcessedMessage(Base):
    """Tin nhắn đã xử lý, để không ghi trùng khi Zalo gửi lại."""

    __tablename__ = "processed_messages"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
