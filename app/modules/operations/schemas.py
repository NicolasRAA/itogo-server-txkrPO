from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class LineIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    category_id: int


class ManualOperationIn(BaseModel):
    merchant: str | None = Field(default=None, max_length=200)
    occurred_at: datetime
    is_refund: bool = False
    lines: list[LineIn] = Field(min_length=1)


class LineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    amount: Decimal
    category_id: int


class OperationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    merchant: str | None
    occurred_at: datetime
    total: Decimal
    is_refund: bool
    receipt_id: int | None
    lines: list[LineOut]


class CategoryTotal(BaseModel):
    category_id: int
    category: str
    amount: Decimal


class MonthTotal(BaseModel):
    month: int
    amount: Decimal
