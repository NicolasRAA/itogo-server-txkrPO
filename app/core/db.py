"""Подключение к базе данных и базовый класс моделей."""
from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

_url = get_settings().database_url
_connect_args = {"check_same_thread": False} if _url.startswith("sqlite") else {}

engine = create_engine(_url, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Общий предок всех таблиц."""


def utcnow() -> datetime:
    """Текущее время в UTC без часового пояса: так оно хранится в базе."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_session() -> Iterator[Session]:
    """Сессия на один запрос. Транзакцию подтверждает тот, кто завершает сценарий: маршрут или сервис сценария."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
