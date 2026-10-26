import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Enum, ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, utcnow


class ReceiptStatus(str, enum.Enum):
    QUEUED = "queued"          # ждёт воркера
    PROCESSING = "processing"  # воркер работает
    READY = "ready"            # распознан, ждёт проверки пользователем
    FAILED = "failed"          # не распознан или отклонён как дубликат
    SAVED = "saved"            # пользователь подтвердил, операция создана


class Receipt(Base):
    __tablename__ = "receipt"
    __table_args__ = (
        # один и тот же чек (по фискальным реквизитам) нельзя сохранить дважды, ФТ-8
        Index(
            "uq_receipt_fiscal", "user_id", "fn", "fd", "fp", unique=True,
            sqlite_where=text("status = 'saved'"), postgresql_where=text("status = 'saved'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[ReceiptStatus] = mapped_column(
        Enum(ReceiptStatus, native_enum=False, length=16, values_callable=lambda e: [m.value for m in e]),
        default=ReceiptStatus.QUEUED,
    )
    image_key: Mapped[str | None] = mapped_column(String(255))
    attempts: Mapped[int] = mapped_column(default=0)
    failure_reason: Mapped[str | None] = mapped_column(String(64))
    fn: Mapped[str | None] = mapped_column(String(32))  # номер фискального накопителя
    fd: Mapped[str | None] = mapped_column(String(32))  # номер фискального документа
    fp: Mapped[str | None] = mapped_column(String(32))  # фискальный признак
    merchant: Mapped[str | None] = mapped_column(String(200))
    purchase_dt: Mapped[datetime | None]
    total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    is_refund: Mapped[bool] = mapped_column(default=False)
    flags: Mapped[list] = mapped_column(JSON, default=list)  # поля, которые нужно проверить
    model_version: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    items: Mapped[list["ReceiptItem"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="ReceiptItem.position"
    )


class ReceiptItem(Base):
    __tablename__ = "receipt_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipt.id"), index=True)
    position: Mapped[int]
    name: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    confidence: Mapped[float] = mapped_column(default=1.0)
    category_model_id: Mapped[int] = mapped_column(ForeignKey("category.id"))  # что назначила модель
    category_final_id: Mapped[int | None] = mapped_column(ForeignKey("category.id"))  # что выбрал пользователь

    @property
    def category_id(self) -> int:
        return self.category_final_id or self.category_model_id
