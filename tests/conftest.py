import os
import tempfile
from datetime import datetime
from decimal import Decimal

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["STORAGE_DIR"] = f"{_tmp}/storage"
os.environ["QUEUE_MODE"] = "memory"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import update  # noqa: E402

from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.core.queue import task_queue  # noqa: E402
from app.integrations.ml_client import MlUnavailable, Prediction, Recognition, RecognizedItem  # noqa: E402
from app.integrations.storage import LocalStorage  # noqa: E402
from app.main import app, create_tables  # noqa: E402
from app.modules.classification.service import seed_categories  # noqa: E402
from app.modules.users.models import User  # noqa: E402

API = "/api/v1"
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 200
QR = "t=20261024T1830&s=150.00&fn=9960440300000001&i=1234&fp=3456789012&n=1"


def make_recognition(qr: str | None = QR, total: str = "150.00") -> Recognition:
    return Recognition(
        merchant="Магнит",
        purchase_dt=datetime(2026, 10, 24, 18, 30),
        total=Decimal(total),
        items=[
            RecognizedItem("МОЛОКО 3,2% 930Г", Decimal("1"), Decimal("90.00"), Decimal("90.00")),
            RecognizedItem("ХЛЕБ БОРОД", Decimal("1"), Decimal("60.00"), Decimal("60.00")),
        ],
        qr_payload=qr,
        model_version="test-1",
    )


class FakeMl:
    """Подменяет ML-сервис: возвращает заданный результат или имитирует отказ."""

    def __init__(self, recognition: Recognition | None = None, down: bool = False, category: str = "Продукты"):
        self.recognition = recognition or make_recognition()
        self.down = down
        self.category = category

    def recognize(self, image: bytes) -> Recognition:
        if self.down:
            raise MlUnavailable("нет связи")
        return self.recognition

    def classify(self, names: list[str]) -> list[Prediction]:
        if self.down:
            raise MlUnavailable("нет связи")
        return [Prediction(self.category, 0.9) for _ in names]


@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine)
    create_tables()
    with SessionLocal() as session:
        seed_categories(session)
    task_queue.sent.clear()
    yield


@pytest.fixture
def session():
    with SessionLocal() as s:
        yield s


@pytest.fixture
def storage() -> LocalStorage:
    return LocalStorage(os.environ["STORAGE_DIR"])


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def login(client):
    def _login(email: str = "user@example.com", role: str = "user") -> dict:
        password = "correct-horse-1"
        client.post(f"{API}/auth/register", json={"email": email, "password": password, "consent": True})
        if role != "user":
            with SessionLocal() as s:
                s.execute(update(User).where(User.email == email).values(role=role))
                s.commit()
        token = client.post(f"{API}/auth/login", json={"email": email, "password": password}).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _login


@pytest.fixture
def categories(client, login) -> dict[str, int]:
    headers = login("categories@example.com")
    return {c["name"]: c["id"] for c in client.get(f"{API}/categories", headers=headers).json()}
