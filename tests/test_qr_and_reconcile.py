from datetime import datetime
from decimal import Decimal

import pytest

from app.integrations.ml_client import Recognition
from app.modules.receipts.qr import QrError, parse_qr
from app.modules.receipts.reconcile import reconcile
from tests.conftest import QR, make_recognition


def test_parse_qr_reads_all_fields():
    qr = parse_qr(QR)
    assert qr.purchase_dt == datetime(2026, 10, 24, 18, 30)
    assert qr.total == Decimal("150.00")
    assert (qr.fn, qr.fd, qr.fp) == ("9960440300000001", "1234", "3456789012")
    assert not qr.is_refund


def test_parse_qr_accepts_seconds_and_comma():
    qr = parse_qr("t=20261024T183045&s=99,5&fn=1&i=2&fp=3&n=2")
    assert qr.purchase_dt.second == 45
    assert qr.total == Decimal("99.50")
    assert qr.is_refund


@pytest.mark.parametrize(
    "payload",
    ["", "t=20261024T1830&s=150.00", "t=bad&s=1&fn=1&i=2&fp=3&n=1", "t=20261024T1830&s=abc&fn=1&i=2&fp=3&n=1"],
)
def test_parse_qr_rejects_garbage(payload):
    with pytest.raises(QrError):
        parse_qr(payload)


def test_reconcile_clean_receipt_has_no_flags():
    result = reconcile(make_recognition(), parse_qr(QR))
    assert result.flags == []
    assert result.total == Decimal("150.00")


def test_reconcile_prefers_qr_and_flags_the_difference():
    recognition = make_recognition()
    recognition.purchase_dt = datetime(2026, 10, 25, 18, 30)  # день и месяц распознаны неверно
    result = reconcile(recognition, parse_qr(QR))
    assert result.purchase_dt == datetime(2026, 10, 24, 18, 30)
    assert "date" in result.flags


def test_reconcile_flags_items_that_do_not_add_up():
    result = reconcile(make_recognition(qr=None, total="170.00"), None)
    assert "items_sum" in result.flags


def test_reconcile_flags_low_confidence_and_bad_arithmetic():
    recognition = make_recognition(qr=None)
    recognition.items[0].confidence = 0.4
    recognition.items[1].amount = Decimal("61.00")
    flags = reconcile(recognition, None).flags
    assert "item:0" in flags and "item:1" in flags


def test_reconcile_without_data_asks_for_review():
    flags = reconcile(Recognition(), None).flags
    assert {"merchant", "date", "total"} <= set(flags)


def test_refund_comes_from_qr():
    refund = parse_qr("t=20261024T1830&s=150.00&fn=1&i=2&fp=3&n=2")
    assert reconcile(make_recognition(), refund).is_refund
