"""Сверка результата распознавания с QR-кодом и арифметикой чека (ФТ-11, ФТ-13).

Модель только извлекает данные. Какому источнику верить, решает эта функция:
QR-код надёжнее изображения, поэтому при расхождении берётся значение из него,
а поле помечается, чтобы пользователь проверил его в первую очередь.
"""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.integrations.ml_client import Recognition
from app.modules.receipts.qr import QrData

TOLERANCE = Decimal("0.01")


@dataclass
class ReconcileResult:
    merchant: str | None
    purchase_dt: datetime | None
    total: Decimal | None
    is_refund: bool
    flags: list[str] = field(default_factory=list)


def _same_minute(a: datetime, b: datetime) -> bool:
    return a.replace(second=0, microsecond=0) == b.replace(second=0, microsecond=0)


def _merchant_flags(recognition: Recognition, low_confidence: float) -> list[str]:
    if recognition.merchant is None or recognition.merchant_confidence < low_confidence:
        return ["merchant"]
    return []


def _date_and_total(recognition: Recognition, qr: QrData | None, low_confidence: float):
    """Возвращает дату, итог и метки. С QR-кодом берутся его значения, без него проверяется уверенность."""
    purchase_dt, total = recognition.purchase_dt, recognition.total
    flags = []
    if qr is not None:
        if purchase_dt is not None and not _same_minute(purchase_dt, qr.purchase_dt):
            flags.append("date")
        if total is not None and abs(total - qr.total) > TOLERANCE:
            flags.append("total")
        return qr.purchase_dt, qr.total, flags
    if purchase_dt is None or recognition.date_confidence < low_confidence:
        flags.append("date")
    if total is None or recognition.total_confidence < low_confidence:
        flags.append("total")
    return purchase_dt, total, flags


def _item_flags(recognition: Recognition, total: Decimal | None, low_confidence: float) -> list[str]:
    flags = []
    items_sum = sum((i.amount for i in recognition.items), Decimal("0"))
    if total is not None and abs(items_sum - total) > TOLERANCE:
        flags.append("items_sum")
    for index, item in enumerate(recognition.items):
        wrong_arithmetic = abs(item.quantity * item.price - item.amount) > TOLERANCE
        if item.confidence < low_confidence or wrong_arithmetic:
            flags.append(f"item:{index}")
    return flags


def reconcile(recognition: Recognition, qr: QrData | None, low_confidence: float = 0.8) -> ReconcileResult:
    purchase_dt, total, header_flags = _date_and_total(recognition, qr, low_confidence)
    flags = _merchant_flags(recognition, low_confidence) + header_flags + _item_flags(recognition, total, low_confidence)
    return ReconcileResult(recognition.merchant, purchase_dt, total, qr.is_refund if qr else False, flags)
