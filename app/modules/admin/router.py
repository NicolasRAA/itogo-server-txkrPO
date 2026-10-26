from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_session, utcnow
from app.modules.admin import service
from app.modules.admin.schemas import (
    AuditOut,
    CategoryCreateIn,
    CategoryUpdateIn,
    CorrectionReportOut,
    MerchantStat,
)
from app.modules.classification import service as classification
from app.modules.classification.schemas import CategoryOut
from app.modules.users.deps import require_admin, require_staff
from app.modules.users.models import User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/categories", response_model=list[CategoryOut])
def all_categories(_: User = Depends(require_staff), session: Session = Depends(get_session)):
    return classification.list_categories(session, only_active=False)


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category(data: CategoryCreateIn, admin: User = Depends(require_admin), session: Session = Depends(get_session)):
    category = service.create_category(session, admin.id, data.name)
    session.commit()
    return category


@router.patch("/categories/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: int, data: CategoryUpdateIn, admin: User = Depends(require_admin), session: Session = Depends(get_session)
):
    category = service.update_category(session, admin.id, category_id, data.name, data.is_active)
    session.commit()
    return category


@router.get("/reports/corrections", response_model=CorrectionReportOut)
def corrections(days: int = Query(7, ge=1, le=90), _: User = Depends(require_staff), session: Session = Depends(get_session)):
    now = utcnow()
    report = service.correction_report(session, now - timedelta(days=days), now)
    return CorrectionReportOut(
        receipts=report.receipts,
        fields_total=report.fields_total,
        fields_corrected=report.fields_corrected,
        share=round(report.share, 4),
        exceeds_threshold=report.exceeds_threshold,
        by_field=report.by_field,
        by_merchant=[MerchantStat(merchant=m.merchant, corrected=m.corrected, total=m.total, share=round(m.share, 4)) for m in report.by_merchant],
    )


@router.get("/audit", response_model=list[AuditOut])
def audit(_: User = Depends(require_admin), session: Session = Depends(get_session)):
    return service.list_audit(session)
