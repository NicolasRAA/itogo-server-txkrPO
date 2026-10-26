"""Пароли и токены."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import get_settings
from app.core.errors import Unauthorized

_hasher = PasswordHasher()
_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_token(subject: int, purpose: str, lifetime: timedelta) -> str:
    """Подписанный токен. Назначение (purpose) не даёт использовать токен не по адресу."""
    now = datetime.now(timezone.utc)
    payload = {"sub": str(subject), "purpose": purpose, "iat": now, "exp": now + lifetime}
    return jwt.encode(payload, get_settings().secret_key, algorithm=_ALGORITHM)


def decode_token(token: str, purpose: str) -> int:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        raise Unauthorized("Недействительный или просроченный токен")
    if payload.get("purpose") != purpose:
        raise Unauthorized("Недействительный или просроченный токен")
    return int(payload["sub"])


def create_access_token(user_id: int) -> str:
    return create_token(user_id, "access", timedelta(minutes=get_settings().access_token_minutes))


def new_refresh_token() -> tuple[str, str]:
    """Возвращает пару: сам токен для клиента и его хеш для базы."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
