"""Приём чеков, обработка результата распознавания и подтверждение (ФТ-4, 8, 11, 12, 13)."""
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.queue import task_queue
from app.integrations.ml_client import MlClient, MlUnavailable, Recognition
from app.integrations.storage import Storage
from app.modules.admin import service as admin
from app.modules.classification import service as classification
from app.modules.limits import service as limits
from app.modules.operations import service as operations
from app.modules.receipts.models import Receipt, ReceiptItem, ReceiptStatus
from app.modules.receipts.qr import QrData, QrError, parse_qr
from app.modules.receipts.reconcile import reconcile
from app.modules.users.models import User

log = logging.getLogger(__name__)

PDF_MESSAGE = "Файлы PDF не поддерживаются. Загрузите фотографию в формате JPG или PNG"
UNREADABLE_MESSAGE = "Не удалось прочитать файл. Загрузите фотографию в формате JPG или PNG"


class RetryLater(Exception):
    """Распознавание не удалось, но попытки ещё остались: воркер должен повторить задачу."""


@dataclass
class ItemEdit:
    id: int | None
    name: str
    quantity: Decimal
    price: Decimal
    amount: Decimal
    category_id: int


def detect_image_type(content: bytes) -> str | None:
    """Тип определяется по началу файла, а не по расширению, которое можно подделать."""
    if content.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    return None


def accept_upload(session: Session, storage: Storage, user: User, content: bytes) -> Receipt:
    if len(content) > get_settings().max_image_bytes:
        raise ValidationFailed("Файл больше 10 МБ. Уменьшите фотографию и загрузите снова")
    kind = detect_image_type(content)
    if kind is None:
        raise ValidationFailed(PDF_MESSAGE if content.startswith(b"%PDF") else UNREADABLE_MESSAGE)
    key = f"receipts/{user.id}/{uuid.uuid4().hex}.{kind}"
    storage.put(key, content)
    receipt = Receipt(user_id=user.id, image_key=key)
    session.add(receipt)
    session.commit()
    _publish_recognition(receipt.id)
    return receipt


def _publish_recognition(receipt_id: int) -> None:
    try:
        task_queue.publish("recognize_receipt", (receipt_id,), queue="recognition")
    except Exception:  # чек уже сохранён, его подхватит requeue_stuck
        log.exception("Не удалось поставить в очередь чек %s", receipt_id)


def get_for_user(session: Session, user_id: int, receipt_id: int) -> Receipt:
    receipt = session.get(Receipt, receipt_id)
    if receipt is None or receipt.user_id != user_id:
        raise NotFound("Чек не найден")  # чужой чек выглядит так же, как несуществующий
    return receipt


def requeue_stuck(session: Session) -> int:
    """Ставит заново задачи, которые не ушли в очередь или потерялись."""
    border = utcnow() - timedelta(minutes=get_settings().stuck_after_minutes)
    ids = list(
        session.scalars(select(Receipt.id).where(Receipt.status == ReceiptStatus.QUEUED, Receipt.created_at < border))
    )
    for receipt_id in ids:
        _publish_recognition(receipt_id)
    return len(ids)


def mark_failed(session: Session, receipt: Receipt, reason: str) -> None:
    receipt.status = ReceiptStatus.FAILED
    receipt.failure_reason = reason
    session.commit()


def process(session: Session, receipt_id: int, storage: Storage, ml: MlClient) -> None:
    """Обработка одного чека воркером: от изображения до черновика на проверку."""
    receipt = session.get(Receipt, receipt_id)
    if receipt is None or receipt.status not in (ReceiptStatus.QUEUED, ReceiptStatus.PROCESSING):
        return  # повторная доставка задачи: чек уже обработан
    receipt.status = ReceiptStatus.PROCESSING
    receipt.attempts += 1
    session.commit()
    try:
        recognition = ml.recognize(storage.get(receipt.image_key))
    except MlUnavailable:
        if receipt.attempts >= get_settings().max_recognition_attempts:
            mark_failed(session, receipt, "recognition_unavailable")
            return
        receipt.status = ReceiptStatus.QUEUED
        session.commit()
        raise RetryLater()
    apply_recognition(session, receipt, recognition, ml)


def apply_recognition(session: Session, receipt: Receipt, recognition: Recognition, ml: MlClient) -> None:
    qr: QrData | None = None
    qr_unreadable = False
    if recognition.qr_payload:
        try:
            qr = parse_qr(recognition.qr_payload)
        except QrError:
            qr_unreadable = True
    result = reconcile(recognition, qr, get_settings().low_confidence)
    if qr is not None:
        already_saved = session.scalar(
            select(Receipt.id).where(
                Receipt.user_id == receipt.user_id, Receipt.fn == qr.fn, Receipt.fd == qr.fd, Receipt.fp == qr.fp,
                Receipt.status == ReceiptStatus.SAVED,
            )
        )
        if already_saved is not None:
            mark_failed(session, receipt, "duplicate")
            return
        receipt.fn, receipt.fd, receipt.fp = qr.fn, qr.fd, qr.fp

    names = [item.name for item in recognition.items]
    categories = classification.classify_items(session, receipt.user_id, names, ml)
    receipt.items = [
        ReceiptItem(
            position=index, name=item.name, quantity=item.quantity, price=item.price, amount=item.amount,
            confidence=item.confidence, category_model_id=category.category_id,
        )
        for index, (item, category) in enumerate(zip(recognition.items, categories))
    ]
    receipt.merchant, receipt.purchase_dt, receipt.total = result.merchant, result.purchase_dt, result.total
    receipt.is_refund = result.is_refund
    receipt.flags = result.flags + (["qr"] if qr_unreadable else [])
    receipt.model_version = recognition.model_version
    receipt.status = ReceiptStatus.READY
    session.commit()


def _header_changes(receipt: Receipt, merchant: str | None, purchase_dt: datetime, total: Decimal) -> list[admin.FieldChange]:
    changes = []
    for field_name, before, after in (
        ("merchant", receipt.merchant, merchant),
        ("date", receipt.purchase_dt, purchase_dt),
        ("total", receipt.total, total),
    ):
        if before != after:
            changes.append(admin.FieldChange(field_name, None if before is None else str(before), str(after)))
    return changes


def _item_changes(receipt: Receipt, edits: list[ItemEdit]) -> list[admin.FieldChange]:
    """Что пользователь изменил в позициях по сравнению с результатом распознавания."""
    changes = []
    old = {item.id: item for item in receipt.items}
    kept = set()
    for edit in edits:
        item = old.get(edit.id)
        if item is None:
            changes.append(admin.FieldChange("item_added", None, edit.name))
            continue
        kept.add(item.id)
        for field_name, before, after in (
            ("item_name", item.name, edit.name),
            ("item_quantity", item.quantity, edit.quantity),
            ("item_price", item.price, edit.price),
            ("item_amount", item.amount, edit.amount),
            ("category", item.category_model_id, edit.category_id),
        ):
            if before != after:
                changes.append(admin.FieldChange(field_name, str(before), str(after)))
    changes.extend(admin.FieldChange("item_removed", item.name, None) for item_id, item in old.items() if item_id not in kept)
    return changes


def _rebuild_items(session: Session, user_id: int, receipt: Receipt, edits: list[ItemEdit]) -> list[ReceiptItem]:
    """Собирает итоговые позиции по правкам и запоминает выбор пользователя при смене категории (ФТ-15)."""
    by_id = {item.id: item for item in receipt.items}
    items = []
    for index, edit in enumerate(edits):
        original = by_id.get(edit.id)
        if original is not None and edit.category_id != original.category_model_id:
            classification.remember_choice(session, user_id, edit.name, edit.category_id)
        items.append(
            ReceiptItem(
                position=index, name=edit.name, quantity=edit.quantity, price=edit.price, amount=edit.amount,
                confidence=original.confidence if original else 1.0,
                category_model_id=original.category_model_id if original else edit.category_id,
                category_final_id=edit.category_id,
            )
        )
    return items


def confirm(session: Session, user: User, receipt_id: int, merchant: str | None, purchase_dt: datetime, total: Decimal, edits: list[ItemEdit]) -> operations.Operation:
    """Сохраняет операцию со всеми позициями в одной транзакции (подраздел 4.1.4 ТЗ)."""
    receipt = get_for_user(session, user.id, receipt_id)
    if receipt.status != ReceiptStatus.READY:
        raise Conflict("Чек ещё не обработан или уже сохранён")
    if sum((e.amount for e in edits), Decimal("0")) != total:
        raise ValidationFailed("Сумма позиций не равна итогу чека")
    for edit in edits:
        classification.get_category(session, edit.category_id)

    changes = _header_changes(receipt, merchant, purchase_dt, total) + _item_changes(receipt, edits)
    fields_total = 3 + 5 * len(receipt.items)  # продавец, дата, итог и по пять полей у каждой позиции
    receipt.items = _rebuild_items(session, user.id, receipt, edits)
    receipt.merchant, receipt.purchase_dt, receipt.total = merchant, purchase_dt, total
    receipt.status = ReceiptStatus.SAVED
    try:
        session.flush()
        lines = [operations.LineData(e.name, e.amount, e.category_id) for e in edits]
        operation = operations.create_operation(session, user.id, merchant, purchase_dt, lines, receipt.is_refund, receipt.id)
        if not receipt.is_refund:
            limits.check_after_operation(session, user, {e.category_id for e in edits}, purchase_dt)
        admin.record_corrections(session, receipt.id, user.id, merchant, fields_total, changes)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise Conflict("Этот чек уже сохранён")
    return operation


def delete_old_images(session: Session, storage: Storage) -> int:
    """Удаляет фотографии старше срока хранения (90 дней). Данные чека остаются."""
    border = utcnow() - timedelta(days=get_settings().image_retention_days)
    old = session.scalars(select(Receipt).where(Receipt.image_key.is_not(None), Receipt.created_at < border)).all()
    for receipt in old:
        storage.delete(receipt.image_key)
        receipt.image_key = None
    session.commit()
    return len(old)


def reclassify_uncategorized(session: Session, ml: MlClient) -> int:
    """Повторно классифицирует позиции непроверенных чеков, которые остались без категории."""
    fallback = classification.uncategorized_id(session)
    receipts = session.scalars(select(Receipt).where(Receipt.status == ReceiptStatus.READY)).all()
    updated = 0
    for receipt in receipts:
        todo = [item for item in receipt.items if item.category_model_id == fallback]
        if not todo:
            continue
        found = classification.classify_items(session, receipt.user_id, [i.name for i in todo], ml)
        for item, category in zip(todo, found):
            if category.category_id != fallback:
                item.category_model_id = category.category_id
                updated += 1
    session.commit()
    return updated


def delete_user_data(session: Session, storage: Storage, user_id: int) -> None:
    for receipt in session.scalars(select(Receipt).where(Receipt.user_id == user_id)):
        if receipt.image_key:
            storage.delete(receipt.image_key)
        session.delete(receipt)
    session.flush()
