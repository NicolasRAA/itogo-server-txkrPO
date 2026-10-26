"""Месячные лимиты и уведомления при достижении 80 % и 100 % (ФТ-24, ФТ-25)."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.core.queue import task_queue
from app.modules.classification.service import get_category
from app.modules.limits.models import Notification, SpendingLimit
from app.modules.operations import service as operations
from app.modules.users.models import User

LEVELS = (80, 100)


@dataclass
class LimitUsage:
    category_id: int
    category: str
    monthly_amount: Decimal
    spent: Decimal
    percent: int


def percent_used(spent: Decimal, limit: Decimal) -> int:
    if limit <= 0:
        return 0
    return int(spent * 100 / limit)


def reached_level(spent: Decimal, limit: Decimal) -> int | None:
    """Наивысший порог из LEVELS, который уже достигнут, или None."""
    percent = percent_used(spent, limit)
    reached = [level for level in LEVELS if percent >= level]
    return reached[-1] if reached else None


def set_limit(session: Session, user_id: int, category_id: int, amount: Decimal) -> SpendingLimit:
    get_category(session, category_id)
    limit = session.scalar(
        select(SpendingLimit).where(SpendingLimit.user_id == user_id, SpendingLimit.category_id == category_id)
    )
    if limit is None:
        limit = SpendingLimit(user_id=user_id, category_id=category_id, monthly_amount=amount)
        session.add(limit)
    else:
        limit.monthly_amount = amount
    session.flush()
    return limit


def remove_limit(session: Session, user_id: int, category_id: int) -> None:
    limit = session.scalar(
        select(SpendingLimit).where(SpendingLimit.user_id == user_id, SpendingLimit.category_id == category_id)
    )
    if limit is None:
        raise NotFound("Лимит не найден")
    session.execute(delete(Notification).where(Notification.limit_id == limit.id))
    session.delete(limit)


def usage(session: Session, user_id: int, when: datetime) -> list[LimitUsage]:
    """Текущий расход по каждому лимиту за месяц, в который попадает дата when."""
    start, end = operations.month_bounds(when.year, when.month)
    rows = []
    for limit in session.scalars(select(SpendingLimit).where(SpendingLimit.user_id == user_id)):
        spent = operations.spent(session, user_id, limit.category_id, start, end)
        name = get_category(session, limit.category_id).name
        rows.append(LimitUsage(limit.category_id, name, limit.monthly_amount, spent, percent_used(spent, limit.monthly_amount)))
    return rows


def check_after_operation(session: Session, user: User, category_ids: set[int], when: datetime) -> list[Notification]:
    """Проверяет лимиты тех категорий, по которым только что появились расходы."""
    created = []
    period = f"{when.year}-{when.month:02d}"
    for item in usage(session, user.id, when):
        if item.category_id not in category_ids:
            continue
        level = reached_level(item.spent, item.monthly_amount)
        if level is None:
            continue
        limit = session.scalar(
            select(SpendingLimit).where(SpendingLimit.user_id == user.id, SpendingLimit.category_id == item.category_id)
        )
        exists = session.scalar(
            select(Notification).where(
                Notification.limit_id == limit.id, Notification.level == level, Notification.period == period
            )
        )
        if exists is not None:
            continue
        if level == 100:
            text = f"Лимит по категории «{item.category}» исчерпан: {item.spent} из {item.monthly_amount}"
        else:
            text = f"По категории «{item.category}» израсходовано {item.percent} % лимита"
        notification = Notification(user_id=user.id, limit_id=limit.id, level=level, period=period, message=text)
        session.add(notification)
        created.append(notification)
        if user.notify_by_email:
            task_queue.publish("send_email", (user.email, "Лимит расходов", text))
    session.flush()
    return created


def list_notifications(session: Session, user_id: int, only_unread: bool = False) -> list[Notification]:
    query = select(Notification).where(Notification.user_id == user_id).order_by(Notification.id.desc())
    if only_unread:
        query = query.where(Notification.is_read.is_(False))
    return list(session.scalars(query))


def mark_read(session: Session, user_id: int, notification_id: int) -> Notification:
    notification = session.get(Notification, notification_id)
    if notification is None or notification.user_id != user_id:
        raise NotFound("Уведомление не найдено")
    notification.is_read = True
    return notification


def delete_user_data(session: Session, user_id: int) -> None:
    session.execute(delete(Notification).where(Notification.user_id == user_id))
    session.execute(delete(SpendingLimit).where(SpendingLimit.user_id == user_id))
