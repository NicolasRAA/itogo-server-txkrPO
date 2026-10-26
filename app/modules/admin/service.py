"""Справочник категорий для персонала, учёт исправлений и журнал действий (ФТ-26, ФТ-27, ФТ-28)."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.modules.admin.models import AuditLog, Correction, ReceiptStat
from app.modules.classification import service as classification
from app.modules.classification.models import Category

# Порог из ТЗ: если пользователи исправляют больше 15 % полей, качество моделей нужно проверить
CORRECTION_THRESHOLD = 0.15


@dataclass
class FieldChange:
    field: str
    recognized: str | None
    final: str | None


@dataclass
class MerchantShare:
    merchant: str
    corrected: int
    total: int

    @property
    def share(self) -> float:
        return self.corrected / self.total if self.total else 0.0


@dataclass
class CorrectionReport:
    receipts: int
    fields_total: int
    fields_corrected: int
    by_field: dict[str, int]
    by_merchant: list[MerchantShare]

    @property
    def share(self) -> float:
        return self.fields_corrected / self.fields_total if self.fields_total else 0.0

    @property
    def exceeds_threshold(self) -> bool:
        return self.share > CORRECTION_THRESHOLD


def log_action(session: Session, actor_id: int, action: str, target_user_id: int | None = None, details: str = "") -> None:
    session.add(AuditLog(actor_id=actor_id, action=action, target_user_id=target_user_id, details=details))


def list_audit(session: Session, limit: int = 100) -> list[AuditLog]:
    return list(session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)))


def create_category(session: Session, actor_id: int, name: str) -> Category:
    category = classification.create_category(session, name)
    log_action(session, actor_id, "category.create", details=name)
    return category


def update_category(session: Session, actor_id: int, category_id: int, name: str | None, is_active: bool | None) -> Category:
    category = classification.update_category(session, category_id, name, is_active)
    log_action(session, actor_id, "category.update", details=f"id={category_id}")
    return category


def record_corrections(
    session: Session, receipt_id: int, user_id: int, merchant: str | None, fields_total: int, changes: list[FieldChange]
) -> None:
    """Вызывается при подтверждении чека: сохраняет изменённые поля и итоговую статистику."""
    for change in changes:
        session.add(
            Correction(
                receipt_id=receipt_id,
                user_id=user_id,
                field=change.field,
                recognized_value=change.recognized,
                final_value=change.final,
            )
        )
    session.add(
        ReceiptStat(
            receipt_id=receipt_id, user_id=user_id, merchant=merchant,
            fields_total=fields_total, fields_corrected=len(changes),
        )
    )


def correction_report(session: Session, since: datetime, until: datetime) -> CorrectionReport:
    stats = session.scalars(select(ReceiptStat).where(ReceiptStat.created_at >= since, ReceiptStat.created_at < until))
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    receipts = fields_total = fields_corrected = 0
    for stat in stats:
        receipts += 1
        fields_total += stat.fields_total
        fields_corrected += stat.fields_corrected
        entry = totals[stat.merchant or "не определён"]
        entry[0] += stat.fields_corrected
        entry[1] += stat.fields_total
    by_field = dict(
        session.execute(
            select(Correction.field, func.count())
            .where(Correction.created_at >= since, Correction.created_at < until)
            .group_by(Correction.field)
        ).all()
    )
    merchants = sorted((MerchantShare(m, c, t) for m, (c, t) in totals.items()), key=lambda s: s.share, reverse=True)
    return CorrectionReport(receipts, fields_total, fields_corrected, by_field, merchants)


def delete_user_data(session: Session, user_id: int) -> None:
    session.execute(delete(Correction).where(Correction.user_id == user_id))
    session.execute(delete(ReceiptStat).where(ReceiptStat.user_id == user_id))
