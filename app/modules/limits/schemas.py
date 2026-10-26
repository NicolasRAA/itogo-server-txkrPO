from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class LimitIn(BaseModel):
    monthly_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class LimitOut(BaseModel):
    category_id: int
    category: str
    monthly_amount: Decimal
    spent: Decimal
    percent: int


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    level: int
    period: str
    message: str
    is_read: bool
    created_at: datetime
