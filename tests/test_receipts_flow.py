from datetime import timedelta

from app.core.db import utcnow
from app.modules.receipts import service
from app.modules.receipts.models import Receipt, ReceiptStatus
from tests.conftest import API, JPEG, FakeMl, make_recognition


def upload(client, headers, content=JPEG, name="check.jpg"):
    return client.post(f"{API}/receipts", files={"file": (name, content, "image/jpeg")}, headers=headers)


def run_worker(session, storage, receipt_id, ml=None):
    service.process(session, receipt_id, storage, ml or FakeMl())


def confirm_payload(receipt: dict, categories: dict, change_first_to: str | None = None) -> dict:
    items = [
        {"id": i["id"], "name": i["name"], "quantity": i["quantity"], "price": i["price"], "amount": i["amount"],
         "category_id": i["category_id"]}
        for i in receipt["items"]
    ]
    if change_first_to:
        items[0]["category_id"] = categories[change_first_to]
    return {"merchant": receipt["merchant"], "purchase_dt": receipt["purchase_dt"], "total": receipt["total"], "items": items}


def test_pdf_is_rejected_with_a_helpful_message(client, login):
    response = upload(client, login(), b"%PDF-1.7 ...", "check.pdf")
    assert response.status_code == 422
    assert "Загрузите фотографию в формате JPG или PNG" in response.json()["message"]


def test_oversized_and_unknown_files_are_rejected(client, login):
    headers = login()
    assert upload(client, headers, b"\xff\xd8\xff" + b"0" * (10 * 1024 * 1024)).status_code == 422
    assert upload(client, headers, b"hello").status_code == 422


def test_upload_queues_the_receipt(client, login, session):
    response = upload(client, login())
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert task_sent("recognize_receipt")
    assert session.get(Receipt, response.json()["id"]).image_key.endswith(".jpg")


def task_sent(name: str) -> bool:
    from app.core.queue import task_queue

    return any(task == name and queue == "recognition" for task, _, queue in task_queue.sent)


def test_full_scenario_from_photo_to_report(client, login, session, storage, categories):
    headers = login()
    receipt_id = upload(client, headers).json()["id"]
    run_worker(session, storage, receipt_id)

    receipt = client.get(f"{API}/receipts/{receipt_id}", headers=headers).json()
    assert receipt["status"] == "ready"
    assert receipt["flags"] == []
    assert [i["category_id"] for i in receipt["items"]] == [categories["Продукты"]] * 2

    client.put(f"{API}/limits/{categories['Готовая еда']}", json={"monthly_amount": "100"}, headers=headers)
    payload = confirm_payload(receipt, categories, change_first_to="Готовая еда")
    saved = client.post(f"{API}/receipts/{receipt_id}/confirm", json=payload, headers=headers)
    assert saved.status_code == 201
    assert saved.json()["total"] == "150.00"

    report = client.get(f"{API}/reports/by-category?year=2026&month=10", headers=headers).json()
    assert {r["category"]: r["amount"] for r in report} == {"Готовая еда": "90.00", "Продукты": "60.00"}

    notes = client.get(f"{API}/notifications", headers=headers).json()
    assert [n["level"] for n in notes] == [80]  # 90 из 100: порог 80 %, но не 100 %

    # выбор пользователя запомнился: то же название у него теперь сразу попадает в «Готовую еду»
    second_id = upload(client, headers).json()["id"]
    run_worker(session, storage, second_id, FakeMl(make_recognition(qr=None)))
    second = client.get(f"{API}/receipts/{second_id}", headers=headers).json()
    assert second["items"][0]["category_id"] == categories["Готовая еда"]
    assert second["items"][1]["category_id"] == categories["Продукты"]


def test_confirm_is_rejected_when_items_do_not_add_up(client, login, session, storage, categories):
    headers = login()
    receipt_id = upload(client, headers).json()["id"]
    run_worker(session, storage, receipt_id)
    payload = confirm_payload(client.get(f"{API}/receipts/{receipt_id}", headers=headers).json(), categories)
    payload["total"] = "151.00"
    assert client.post(f"{API}/receipts/{receipt_id}/confirm", json=payload, headers=headers).status_code == 422


def test_receipt_cannot_be_confirmed_twice(client, login, session, storage, categories):
    headers = login()
    receipt_id = upload(client, headers).json()["id"]
    run_worker(session, storage, receipt_id)
    payload = confirm_payload(client.get(f"{API}/receipts/{receipt_id}", headers=headers).json(), categories)
    assert client.post(f"{API}/receipts/{receipt_id}/confirm", json=payload, headers=headers).status_code == 201
    assert client.post(f"{API}/receipts/{receipt_id}/confirm", json=payload, headers=headers).status_code == 409


def test_same_fiscal_receipt_is_not_counted_twice(client, login, session, storage, categories):
    headers = login()
    first = upload(client, headers).json()["id"]
    run_worker(session, storage, first)
    payload = confirm_payload(client.get(f"{API}/receipts/{first}", headers=headers).json(), categories)
    client.post(f"{API}/receipts/{first}/confirm", json=payload, headers=headers)

    second = upload(client, headers).json()["id"]
    run_worker(session, storage, second)
    result = client.get(f"{API}/receipts/{second}", headers=headers).json()
    assert result["status"] == "failed"
    assert result["failure_reason"] == "duplicate"


def test_two_uploads_of_one_receipt_cannot_both_be_saved(client, login, session, storage, categories):
    headers = login()
    ids = [upload(client, headers).json()["id"] for _ in range(2)]
    for receipt_id in ids:
        run_worker(session, storage, receipt_id)  # оба чека ещё не сохранены, поэтому оба готовы к проверке
    payloads = [confirm_payload(client.get(f"{API}/receipts/{i}", headers=headers).json(), categories) for i in ids]
    codes = [client.post(f"{API}/receipts/{i}/confirm", json=p, headers=headers).status_code for i, p in zip(ids, payloads)]
    assert codes == [201, 409]  # второй останавливает уникальный индекс в базе


def test_other_users_receipt_looks_missing(client, login, session, storage):
    receipt_id = upload(client, login("owner@example.com")).json()["id"]
    assert client.get(f"{API}/receipts/{receipt_id}", headers=login("other@example.com")).status_code == 404


def test_recognition_failure_is_retried_then_given_up(client, login, session, storage):
    receipt_id = upload(client, login()).json()["id"]
    down = FakeMl(down=True)
    for _ in range(2):
        try:
            run_worker(session, storage, receipt_id, down)
        except service.RetryLater:
            pass
    assert session.get(Receipt, receipt_id).status == ReceiptStatus.QUEUED
    run_worker(session, storage, receipt_id, down)  # третья попытка, после неё чек считается не распознанным
    session.refresh(session.get(Receipt, receipt_id))
    receipt = session.get(Receipt, receipt_id)
    assert receipt.status == ReceiptStatus.FAILED
    assert receipt.failure_reason == "recognition_unavailable"


def test_classification_failure_leaves_items_uncategorized(client, login, session, storage, categories):
    receipt_id = upload(client, login()).json()["id"]
    ml = FakeMl()
    ml.classify = FakeMl(down=True).classify
    run_worker(session, storage, receipt_id, ml)
    receipt = session.get(Receipt, receipt_id)
    assert receipt.status == ReceiptStatus.READY
    assert {i.category_model_id for i in receipt.items} == {service.classification.uncategorized_id(session)}
    assert service.reclassify_uncategorized(session, FakeMl()) == 2


def test_stuck_receipts_are_queued_again(client, login, session):
    receipt_id = upload(client, login()).json()["id"]
    from app.core.queue import task_queue

    task_queue.sent.clear()
    assert service.requeue_stuck(session) == 0  # свежий чек ещё не считается зависшим
    session.get(Receipt, receipt_id).created_at = utcnow() - timedelta(minutes=5)
    session.commit()
    assert service.requeue_stuck(session) == 1
    assert task_queue.sent[0][1] == (receipt_id,)


def test_old_images_are_deleted_but_receipt_stays(client, login, session, storage):
    receipt_id = upload(client, login()).json()["id"]
    receipt = session.get(Receipt, receipt_id)
    key = receipt.image_key
    receipt.created_at = utcnow() - timedelta(days=91)
    session.commit()
    assert service.delete_old_images(session, storage) == 1
    assert session.get(Receipt, receipt_id).image_key is None
    assert not (storage.root / key).exists()
