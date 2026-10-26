"""Операции, список с фильтрами и отчёты (ФТ-7, ФТ-17, ФТ-18, ФТ-19)."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import case, delete, extract, func, select
from sqlalchemy.orm import Session

from app.modules.classification.models import Category
from app.modules.classification.service import get_category
from app.modules.operations.models import Operation, OperationLine


@dataclass
class LineData:
    name: str
    amount: Decimal
    category_id: int


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """Первое число месяца и первое число следующего: период берётся как [начало, конец)."""
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start, end


def create_operation(
    session: Session,
    user_id: int,
    merchant: str | None,
    occurred_at: datetime,
    lines: list[LineData],
    is_refund: bool = False,
    receipt_id: int | None = None,
) -> Operation:
    """Создаёт операцию вместе со строками. Транзакцию подтверждает вызывающий."""
    operation = Operation(
        user_id=user_id,
        receipt_id=receipt_id,
        merchant=merchant,
        occurred_at=occurred_at,
        total=sum((line.amount for line in lines), Decimal("0")),
        is_refund=is_refund,
        lines=[OperationLine(name=l.name, amount=l.amount, category_id=l.category_id) for l in lines],
    )
    session.add(operation)
    session.flush()
    return operation


def create_manual(session: Session, user_id: int, merchant, occurred_at, is_refund, lines: list[LineData]) -> Operation:
    for line in lines:
        get_category(session, line.category_id)
    return create_operation(session, user_id, merchant, occurred_at, lines, is_refund)


def list_operations(
    session: Session,
    user_id: int,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    category_id: int | None = None,
    merchant: str | None = None,
    text: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Operation]:
    query = select(Operation).where(Operation.user_id == user_id)
    if date_from is not None:
        query = query.where(Operation.occurred_at >= date_from)
    if date_to is not None:
        query = query.where(Operation.occurred_at < date_to)
    if merchant:
        query = query.where(Operation.merchant.ilike(f"%{merchant}%"))
    if category_id is not None:
        query = query.where(Operation.lines.any(OperationLine.category_id == category_id))
    if text:
        query = query.where(Operation.lines.any(OperationLine.name.ilike(f"%{text}%")))
    query = query.order_by(Operation.occurred_at.desc(), Operation.id.desc()).limit(limit).offset(offset)
    return list(session.scalars(query))


def _signed_amount():
    """Возврат уменьшает расходы, поэтому его сумма берётся со знаком минус."""
    return case((Operation.is_refund, -OperationLine.amount), else_=OperationLine.amount)


def _to_decimal(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def totals_by_category(session: Session, user_id: int, start: datetime, end: datetime) -> list[tuple[int, str, Decimal]]:
    query = (
        select(Category.id, Category.name, func.sum(_signed_amount()))
        .select_from(OperationLine)
        .join(Operation, Operation.id == OperationLine.operation_id)
        .join(Category, Category.id == OperationLine.category_id)
        .where(Operation.user_id == user_id, Operation.occurred_at >= start, Operation.occurred_at < end)
        .group_by(Category.id, Category.name)
        .order_by(func.sum(_signed_amount()).desc())
    )
    return [(cid, name, _to_decimal(total)) for cid, name, total in session.execute(query)]


def spent(session: Session, user_id: int, category_id: int, start: datetime, end: datetime) -> Decimal:
    query = (
        select(func.sum(_signed_amount()))
        .select_from(OperationLine)
        .join(Operation, Operation.id == OperationLine.operation_id)
        .where(
            Operation.user_id == user_id,
            OperationLine.category_id == category_id,
            Operation.occurred_at >= start,
            Operation.occurred_at < end,
        )
    )
    return _to_decimal(session.scalar(query))


def monthly_totals(session: Session, user_id: int, year: int, category_id: int | None = None) -> list[tuple[int, Decimal]]:
    """Расходы по месяцам года, всего или по одной категории. Пустые месяцы дают ноль."""
    month = extract("month", Operation.occurred_at)
    query = (
        select(month, func.sum(_signed_amount()))
        .select_from(OperationLine)
        .join(Operation, Operation.id == OperationLine.operation_id)
        .where(Operation.user_id == user_id, extract("year", Operation.occurred_at) == year)
        .group_by(month)
    )
    if category_id is not None:
        query = query.where(OperationLine.category_id == category_id)
    found = {int(m): _to_decimal(total) for m, total in session.execute(query)}
    return [(m, found.get(m, Decimal("0.00"))) for m in range(1, 13)]


def delete_user_data(session: Session, user_id: int) -> None:
    ids = select(Operation.id).where(Operation.user_id == user_id)
    session.execute(delete(OperationLine).where(OperationLine.operation_id.in_(ids)))
    session.execute(delete(Operation).where(Operation.user_id == user_id))
