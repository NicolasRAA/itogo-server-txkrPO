from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.receipts.models import ReceiptStatus


class ReceiptItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    name: str
    quantity: Decimal
    price: Decimal
    amount: Decimal
    confidence: float
    category_id: int


class ReceiptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: ReceiptStatus
    failure_reason: str | None
    merchant: str | None
    purchase_dt: datetime | None
    total: Decimal | None
    is_refund: bool
    flags: list[str]
    items: list[ReceiptItemOut]


class ItemEditIn(BaseModel):
    id: int | None = None  # пусто у позиции, которую пользователь добавил сам
    name: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    category_id: int


class ConfirmIn(BaseModel):
    merchant: str | None = Field(default=None, max_length=200)
    purchase_dt: datetime
    total: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    items: list[ItemEditIn] = Field(min_length=1)
