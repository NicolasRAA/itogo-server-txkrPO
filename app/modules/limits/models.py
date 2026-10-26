from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow


class SpendingLimit(Base):
    __tablename__ = "spending_limit"
    __table_args__ = (UniqueConstraint("user_id", "category_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"))
    monthly_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class Notification(Base):
    """Уведомление о лимите. По одному на лимит, уровень и месяц, чтобы не повторяться."""

    __tablename__ = "notification"
    __table_args__ = (UniqueConstraint("limit_id", "level", "period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    limit_id: Mapped[int] = mapped_column(ForeignKey("spending_limit.id"))
    level: Mapped[int]
    period: Mapped[str] = mapped_column(String(7))  # например, 2026-10
    message: Mapped[str] = mapped_column(String(300))
    is_read: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
