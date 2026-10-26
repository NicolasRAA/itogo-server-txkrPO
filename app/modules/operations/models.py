from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, utcnow


class Operation(Base):
    """Расход или возврат. Сумма всегда положительная, возврат отмечен признаком."""

    __tablename__ = "operation"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    receipt_id: Mapped[int | None] = mapped_column(ForeignKey("receipt.id"))
    merchant: Mapped[str | None] = mapped_column(String(200))
    occurred_at: Mapped[datetime] = mapped_column(index=True)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    is_refund: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    lines: Mapped[list["OperationLine"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class OperationLine(Base):
    __tablename__ = "operation_line"

    id: Mapped[int] = mapped_column(primary_key=True)
    operation_id: Mapped[int] = mapped_column(ForeignKey("operation.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"), index=True)
