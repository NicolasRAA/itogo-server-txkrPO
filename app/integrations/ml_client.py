"""Клиент ML-сервиса. Контракт: POST /v1/recognize и POST /v1/classify."""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol

import httpx

from app.core.config import get_settings


class MlUnavailable(Exception):
    """ML-сервис не ответил или вернул ошибку."""


@dataclass
class RecognizedItem:
    name: str
    quantity: Decimal
    price: Decimal
    amount: Decimal
    confidence: float = 1.0


@dataclass
class Recognition:
    merchant: str | None = None
    merchant_confidence: float = 1.0
    purchase_dt: datetime | None = None
    date_confidence: float = 1.0
    total: Decimal | None = None
    total_confidence: float = 1.0
    items: list[RecognizedItem] = field(default_factory=list)
    qr_payload: str | None = None
    model_version: str = "unknown"


@dataclass
class Prediction:
    category: str
    confidence: float


class MlClient(Protocol):
    def recognize(self, image: bytes) -> Recognition: ...

    def classify(self, names: list[str]) -> list[Prediction]: ...


def parse_recognition(data: dict) -> Recognition:
    """Разбирает JSON-ответ метода /v1/recognize."""
    items = [
        RecognizedItem(
            name=i["name"],
            quantity=Decimal(str(i["quantity"])),
            price=Decimal(str(i["price"])),
            amount=Decimal(str(i["amount"])),
            confidence=float(i.get("confidence", 1.0)),
        )
        for i in data.get("items", [])
    ]
    dt = data.get("purchase_dt")
    total = data.get("total")
    return Recognition(
        merchant=data.get("merchant"),
        merchant_confidence=float(data.get("merchant_confidence", 1.0)),
        purchase_dt=datetime.fromisoformat(dt) if dt else None,
        date_confidence=float(data.get("date_confidence", 1.0)),
        total=Decimal(str(total)) if total is not None else None,
        total_confidence=float(data.get("total_confidence", 1.0)),
        items=items,
        qr_payload=data.get("qr_payload"),
        model_version=data.get("model_version", "unknown"),
    )


class HttpMlClient:
    def __init__(self, base_url: str, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _post(self, path: str, **kwargs) -> dict | list:
        try:
            response = httpx.post(f"{self.base_url}{path}", timeout=self.timeout, **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MlUnavailable(str(exc)) from exc

    def recognize(self, image: bytes) -> Recognition:
        return parse_recognition(self._post("/v1/recognize", files={"image": image}))

    def classify(self, names: list[str]) -> list[Prediction]:
        data = self._post("/v1/classify", json={"names": names})
        return [Prediction(p["category"], float(p["confidence"])) for p in data]


class StubMlClient:
    """Заглушка для разработки серверной части, пока модели не готовы."""

    def recognize(self, image: bytes) -> Recognition:
        return Recognition(
            merchant="Магазин",
            purchase_dt=datetime(2026, 10, 24, 18, 30),
            total=Decimal("150.00"),
            items=[
                RecognizedItem("МОЛОКО 3,2% 930Г", Decimal("1"), Decimal("90.00"), Decimal("90.00")),
                RecognizedItem("ХЛЕБ БОРОД", Decimal("1"), Decimal("60.00"), Decimal("60.00")),
            ],
            model_version="stub-0",
        )

    def classify(self, names: list[str]) -> list[Prediction]:
        return [Prediction("Продукты", 0.9) for _ in names]


def get_ml_client() -> MlClient:
    url = get_settings().ml_service_url
    return HttpMlClient(url) if url else StubMlClient()
