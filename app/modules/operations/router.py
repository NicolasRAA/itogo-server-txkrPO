from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_session, utcnow
from app.modules.limits import service as limits
from app.modules.operations import service
from app.modules.operations.schemas import CategoryTotal, ManualOperationIn, MonthTotal, OperationOut
from app.modules.users.deps import get_current_user
from app.modules.users.models import User

router = APIRouter(tags=["operations"])


@router.post("/operations", response_model=OperationOut, status_code=201)
def create_operation(data: ManualOperationIn, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    lines = [service.LineData(l.name, l.amount, l.category_id) for l in data.lines]
    operation = service.create_manual(session, user.id, data.merchant, data.occurred_at, data.is_refund, lines)
    if not data.is_refund:
        limits.check_after_operation(session, user, {l.category_id for l in lines}, data.occurred_at)
    session.commit()
    return operation


@router.get("/operations", response_model=list[OperationOut])
def operations(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    category_id: int | None = None,
    merchant: str | None = None,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    return service.list_operations(session, user.id, date_from, date_to, category_id, merchant, q, limit, offset)


@router.get("/reports/by-category", response_model=list[CategoryTotal])
def by_category(
    year: int | None = None,
    month: int | None = Query(None, ge=1, le=12),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """По умолчанию отчёт строится за текущий месяц."""
    now = utcnow()
    start, end = service.month_bounds(year or now.year, month or now.month)
    rows = service.totals_by_category(session, user.id, start, end)
    return [CategoryTotal(category_id=cid, category=name, amount=amount) for cid, name, amount in rows]


@router.get("/reports/monthly", response_model=list[MonthTotal])
def monthly(
    year: int | None = None,
    category_id: int | None = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    rows = service.monthly_totals(session, user.id, year or utcnow().year, category_id)
    return [MonthTotal(month=m, amount=amount) for m, amount in rows]
