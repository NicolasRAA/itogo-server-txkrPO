from decimal import Decimal

from app.modules.classification import service as classification
from app.modules.limits.service import reached_level
from tests.conftest import API, FakeMl


def add_operation(client, headers, category_id, amount, day="2026-10-10", name="Хлеб", refund=False):
    body = {
        "occurred_at": f"{day}T12:00:00", "is_refund": refund, "merchant": "Пекарня",
        "lines": [{"name": name, "amount": amount, "category_id": category_id}],
    }
    return client.post(f"{API}/operations", json=body, headers=headers)


def test_reached_level_uses_thresholds():
    limit = Decimal("100")
    assert reached_level(Decimal("79.99"), limit) is None
    assert reached_level(Decimal("80"), limit) == 80
    assert reached_level(Decimal("100"), limit) == 100
    assert reached_level(Decimal("250"), limit) == 100
    assert reached_level(Decimal("10"), Decimal("0")) is None


def test_refund_reduces_expenses(client, login, categories):
    headers = login()
    food = categories["Продукты"]
    add_operation(client, headers, food, "200")
    add_operation(client, headers, food, "50", refund=True)
    report = client.get(f"{API}/reports/by-category?year=2026&month=10", headers=headers).json()
    assert report[0]["amount"] == "150.00"


def test_filters_and_search(client, login, categories):
    headers = login()
    add_operation(client, headers, categories["Продукты"], "100", day="2026-09-05", name="Молоко")
    add_operation(client, headers, categories["Транспорт"], "40", day="2026-10-05", name="Метро")
    found = client.get(f"{API}/operations?category_id={categories['Транспорт']}", headers=headers).json()
    assert [o["lines"][0]["name"] for o in found] == ["Метро"]
    found = client.get(f"{API}/operations?date_from=2026-10-01T00:00:00", headers=headers).json()
    assert len(found) == 1
    found = client.get(f"{API}/operations?q=Молоко", headers=headers).json()
    assert len(found) == 1


def test_monthly_report_has_twelve_months(client, login, categories):
    headers = login()
    add_operation(client, headers, categories["Продукты"], "100", day="2026-03-05")
    months = client.get(f"{API}/reports/monthly?year=2026", headers=headers).json()
    assert len(months) == 12
    assert months[2]["amount"] == "100.00"
    assert months[3]["amount"] == "0.00"


def test_limit_notifications_are_not_repeated(client, login, categories):
    headers = login()
    food = categories["Продукты"]
    client.put(f"{API}/limits/{food}", json={"monthly_amount": "100"}, headers=headers)
    add_operation(client, headers, food, "85")
    add_operation(client, headers, food, "5")  # всё ещё 90 %, повторного уведомления нет
    add_operation(client, headers, food, "20")  # 110 %
    levels = [n["level"] for n in client.get(f"{API}/notifications", headers=headers).json()]
    assert sorted(levels) == [80, 100]


def test_email_about_limit_is_sent_only_when_enabled(client, login, categories):
    from app.core.queue import task_queue

    headers = login()
    food = categories["Продукты"]
    client.put(f"{API}/limits/{food}", json={"monthly_amount": "100"}, headers=headers)
    task_queue.sent.clear()
    add_operation(client, headers, food, "90")
    assert not task_queue.sent
    client.patch(f"{API}/users/me", json={"notify_by_email": True}, headers=headers)
    add_operation(client, headers, food, "20")
    assert [t for t, _, _ in task_queue.sent] == ["send_email"]


def test_user_rule_beats_the_model(session, client, login, categories):
    user_id = client.get(f"{API}/users/me", headers=login()).json()["id"]
    classification.remember_choice(session, user_id, "Молоко 3,2% 930г", categories["Готовая еда"])
    session.commit()
    result = classification.classify_items(session, user_id, ["МОЛОКО 2,5% 1Л"], FakeMl())
    assert result[0].category_id == categories["Готовая еда"] and result[0].confidence == 1.0


def test_normalize_drops_digits_and_case():
    assert classification.normalize("МОЛОКО 3,2% 930Г") == classification.normalize("молоко 2,5% 1л") == "молоко"
    assert classification.normalize("  Ёжик  ") == "ежик"


def test_unknown_model_category_falls_back(session, client, login, categories):
    user_id = client.get(f"{API}/users/me", headers=login()).json()["id"]
    result = classification.classify_items(session, user_id, ["Что-то"], FakeMl(category="Несуществующая"))
    assert result[0].category_id == classification.uncategorized_id(session)


def test_only_admin_edits_categories_and_it_is_logged(client, login):
    user, support, admin = login("u@example.com"), login("s@example.com", "support"), login("a@example.com", "admin")
    assert client.post(f"{API}/admin/categories", json={"name": "Хобби"}, headers=user).status_code == 403
    assert client.post(f"{API}/admin/categories", json={"name": "Хобби"}, headers=support).status_code == 403
    assert client.post(f"{API}/admin/categories", json={"name": "Хобби"}, headers=admin).status_code == 201
    assert client.post(f"{API}/admin/categories", json={"name": "Хобби"}, headers=admin).status_code == 409
    actions = [a["action"] for a in client.get(f"{API}/admin/audit", headers=admin).json()]
    assert actions == ["category.create"]
    assert client.get(f"{API}/admin/categories", headers=support).status_code == 200


def test_correction_report_counts_changed_fields(client, login, session, storage, categories):
    from tests.test_receipts_flow import confirm_payload, run_worker, upload

    headers, staff = login(), login("staff@example.com", "support")
    receipt_id = upload(client, headers).json()["id"]
    run_worker(session, storage, receipt_id)
    receipt = client.get(f"{API}/receipts/{receipt_id}", headers=headers).json()
    client.post(f"{API}/receipts/{receipt_id}/confirm", json=confirm_payload(receipt, categories, "Транспорт"), headers=headers)
    report = client.get(f"{API}/admin/reports/corrections", headers=staff).json()
    assert report["receipts"] == 1
    assert report["fields_total"] == 13  # продавец, дата, итог и по пять полей у двух позиций
    assert report["fields_corrected"] == 1
    assert report["by_field"] == {"category": 1}
    assert report["by_merchant"][0]["merchant"] == "Магнит"
    assert not report["exceeds_threshold"]  # 1 из 13 это около 7,7 %, порог 15 %
