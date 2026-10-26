"""Регистрация, вход и удаление учётной записи (ФТ-1, ФТ-2, ФТ-3)."""
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.errors import Conflict, NotFound, Unauthorized, ValidationFailed
from app.core.queue import task_queue
from app.core.security import (
    create_access_token,
    create_token,
    decode_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.modules.users.models import RefreshToken, User

# Сообщение одно на все случаи: оно не говорит, что именно неверно
BAD_CREDENTIALS = "Неверная почта или пароль"


def get_user(session: Session, user_id: int) -> User:
    user = session.get(User, user_id)
    if user is None or user.delete_requested_at is not None:
        raise NotFound("Пользователь не найден")
    return user


def register(session: Session, email: str, password: str, consent: bool) -> User:
    if not consent:
        raise ValidationFailed("Нужно согласие на обработку персональных данных")
    email = email.strip().lower()
    if session.scalar(select(User).where(User.email == email)) is not None:
        raise Conflict("Пользователь с такой почтой уже зарегистрирован")
    user = User(email=email, password_hash=hash_password(password), consent_at=utcnow())
    session.add(user)
    session.flush()
    token = create_token(user.id, "confirm", timedelta(days=2))
    session.commit()
    task_queue.publish("send_email", (email, "Подтверждение почты", f"Код подтверждения: {token}"))
    return user


def confirm_email(session: Session, token: str) -> User:
    user = get_user(session, decode_token(token, "confirm"))
    user.email_confirmed = True
    session.commit()
    return user


def issue_tokens(session: Session, user: User) -> tuple[str, str]:
    """Создаёт токен доступа и токен обновления. В базе лежит только хеш второго."""
    raw, token_hash = new_refresh_token()
    expires = utcnow() + timedelta(days=get_settings().refresh_token_days)
    session.add(RefreshToken(user_id=user.id, token_hash=token_hash, expires_at=expires))
    session.commit()
    return create_access_token(user.id), raw


def login(session: Session, email: str, password: str) -> tuple[str, str]:
    settings = get_settings()
    user = session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or user.delete_requested_at is not None:
        raise Unauthorized(BAD_CREDENTIALS)
    now = utcnow()
    if user.locked_until is not None and user.locked_until > now:
        raise Unauthorized("Слишком много неудачных попыток входа. Повторите позже")
    if not verify_password(password, user.password_hash):
        user.failed_attempts += 1
        if user.failed_attempts >= settings.max_login_attempts:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.failed_attempts = 0
        session.commit()  # счётчик попыток должен сохраниться, хотя вход не удался
        raise Unauthorized(BAD_CREDENTIALS)
    user.failed_attempts = 0
    user.locked_until = None
    return issue_tokens(session, user)


def refresh(session: Session, raw_token: str) -> tuple[str, str]:
    """Обменивает токен обновления на новую пару. Старый токен перестаёт действовать."""
    stored = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token)))
    if stored is None or stored.revoked or stored.expires_at < utcnow():
        raise Unauthorized("Войдите заново")
    stored.revoked = True
    return issue_tokens(session, get_user(session, stored.user_id))


def set_email_notifications(session: Session, user: User, enabled: bool) -> User:
    user.notify_by_email = enabled
    session.commit()
    return user


def request_deletion(session: Session, user: User) -> None:
    """Помечает учётную запись к удалению. Сами данные удаляет плановая задача."""
    user.delete_requested_at = utcnow()
    session.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))
    session.commit()


def users_pending_deletion(session: Session) -> list[User]:
    return list(session.scalars(select(User).where(User.delete_requested_at.is_not(None))))


def purge_user(session: Session, user_id: int) -> None:
    """Последний шаг удаления: остальные модули к этому моменту уже убрали свои данные."""
    session.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))
    session.execute(delete(User).where(User.id == user_id))
