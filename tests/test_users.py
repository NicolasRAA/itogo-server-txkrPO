from datetime import timedelta

import pytest

from app.core.errors import Unauthorized
from app.core.security import create_token, decode_token, hash_password, verify_password
from app.core.queue import task_queue
from app.modules.users.models import User
from app.workers.tasks import purge_deleted_accounts
from tests.conftest import API

PASSWORD = "correct-horse-1"


def test_password_hash_is_not_plain_and_verifies():
    hashed = hash_password(PASSWORD)
    assert PASSWORD not in hashed
    assert verify_password(PASSWORD, hashed)
    assert not verify_password("other-password", hashed)


def test_token_cannot_be_used_for_another_purpose():
    token = create_token(7, "confirm", timedelta(minutes=5))
    assert decode_token(token, "confirm") == 7
    with pytest.raises(Unauthorized):
        decode_token(token, "access")


def test_expired_token_is_rejected():
    token = create_token(7, "access", timedelta(seconds=-1))
    with pytest.raises(Unauthorized):
        decode_token(token, "access")


def test_registration_requires_consent_and_unique_email(client):
    body = {"email": "new@example.com", "password": PASSWORD, "consent": False}
    assert client.post(f"{API}/auth/register", json=body).status_code == 422
    body["consent"] = True
    assert client.post(f"{API}/auth/register", json=body).status_code == 201
    assert client.post(f"{API}/auth/register", json=body).status_code == 409
    assert task_queue.sent[0][0] == "send_email"  # письмо с подтверждением ушло в очередь


def test_wrong_email_and_wrong_password_look_the_same(client, login):
    login("known@example.com")
    wrong_password = client.post(f"{API}/auth/login", json={"email": "known@example.com", "password": "bad-password-1"})
    wrong_email = client.post(f"{API}/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    assert wrong_password.status_code == wrong_email.status_code == 401
    assert wrong_password.json()["message"] == wrong_email.json()["message"]


def test_login_is_locked_after_five_failures(client, login):
    login("locked@example.com")
    for _ in range(5):
        client.post(f"{API}/auth/login", json={"email": "locked@example.com", "password": "bad-password-1"})
    response = client.post(f"{API}/auth/login", json={"email": "locked@example.com", "password": PASSWORD})
    assert response.status_code == 401
    assert "Повторите позже" in response.json()["message"]


def test_protected_route_needs_a_token(client):
    assert client.get(f"{API}/users/me").status_code == 401


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_refresh_token_works_once(client, login):
    login("refresh@example.com")
    response = client.post(f"{API}/auth/login", json={"email": "refresh@example.com", "password": PASSWORD})
    token = response.cookies.get("refresh_token") or response.headers["set-cookie"].split(";")[0].split("=", 1)[1]
    assert client.post(f"{API}/auth/refresh", cookies={"refresh_token": token}).status_code == 200
    # прежний токен после обмена уже недействителен
    assert client.post(f"{API}/auth/refresh", cookies={"refresh_token": token}).status_code == 401


def test_account_deletion_removes_everything(client, login, session, categories):
    headers = login("gone@example.com")
    client.put(f"{API}/limits/{categories['Продукты']}", json={"monthly_amount": "1000"}, headers=headers)
    client.post(
        f"{API}/operations",
        json={"occurred_at": "2026-10-01T12:00:00", "lines": [{"name": "Хлеб", "amount": "50", "category_id": categories["Продукты"]}]},
        headers=headers,
    )
    assert client.delete(f"{API}/users/me", headers=headers).status_code == 202
    assert client.post(f"{API}/auth/login", json={"email": "gone@example.com", "password": PASSWORD}).status_code == 401
    assert purge_deleted_accounts() == 1
    assert session.query(User).filter_by(email="gone@example.com").count() == 0
