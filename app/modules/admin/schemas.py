from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CategoryCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class CategoryUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    is_active: bool | None = None


class MerchantStat(BaseModel):
    merchant: str
    corrected: int
    total: int
    share: float


class CorrectionReportOut(BaseModel):
    receipts: int
    fields_total: int
    fields_corrected: int
    share: float
    exceeds_threshold: bool
    by_field: dict[str, int]
    by_merchant: list[MerchantStat]


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: int
    action: str
    target_user_id: int | None
    details: str
    created_at: datetime
