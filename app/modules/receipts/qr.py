"""Разбор QR-кода кассового чека по 54-ФЗ (ФТ-6).

Строка QR-кода выглядит так: t=20261024T1830&s=150.00&fn=9960440300000001&i=1234&fp=3456789012&n=1
Состава покупки в ней нет, только время, сумма, признак расчёта и фискальные реквизиты.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs

REQUIRED = ("t", "s", "fn", "i", "fp", "n")
REFUND_TYPES = (2, 4)  # 1 приход, 2 возврат прихода, 3 расход, 4 возврат расхода


class QrError(ValueError):
    """Строка не похожа на QR-код кассового чека."""


@dataclass(frozen=True)
class QrData:
    purchase_dt: datetime
    total: Decimal
    fn: str
    fd: str
    fp: str
    operation_type: int

    @property
    def is_refund(self) -> bool:
        return self.operation_type in REFUND_TYPES


def _parse_time(value: str) -> datetime:
    # формат выбирается по длине: иначе «1830» разбирается как 18:03:0, а не 18:30
    pattern = {13: "%Y%m%dT%H%M", 15: "%Y%m%dT%H%M%S"}.get(len(value))
    if pattern is None:
        raise QrError(f"Непонятное время в QR-коде: {value}")
    try:
        return datetime.strptime(value, pattern)
    except ValueError:
        raise QrError(f"Непонятное время в QR-коде: {value}")


def parse_qr(payload: str) -> QrData:
    params = {key: values[0] for key, values in parse_qs(payload.strip()).items()}
    missing = [key for key in REQUIRED if key not in params]
    if missing:
        raise QrError("В QR-коде нет полей: " + ", ".join(missing))
    try:
        total = Decimal(params["s"].replace(",", ".")).quantize(Decimal("0.01"))
        operation_type = int(params["n"])
    except (InvalidOperation, ValueError):
        raise QrError("В QR-коде неверная сумма или признак расчёта")
    if total < 0:
        raise QrError("В QR-коде отрицательная сумма")
    return QrData(_parse_time(params["t"]), total, params["fn"], params["i"], params["fp"], operation_type)
