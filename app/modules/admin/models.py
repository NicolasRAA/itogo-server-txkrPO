from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow


class Correction(Base):
    """Одно поле чека, которое пользователь исправил после распознавания (ФТ-27)."""

    __tablename__ = "correction"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipt.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    field: Mapped[str] = mapped_column(String(32))
    recognized_value: Mapped[str | None] = mapped_column(String(200))
    final_value: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class ReceiptStat(Base):
    """Сколько полей было в подтверждённом чеке и сколько из них исправлено."""

    __tablename__ = "receipt_stat"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipt.id"), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    merchant: Mapped[str | None] = mapped_column(String(200))
    fields_total: Mapped[int]
    fields_corrected: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class AuditLog(Base):
    """Журнал действий персонала заказчика (ФТ-28)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    target_user_id: Mapped[int | None]
    details: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
