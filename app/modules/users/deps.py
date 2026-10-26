"""Зависимости FastAPI: текущий пользователь и проверка роли."""
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_token
from app.modules.users import service
from app.modules.users.models import User

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(get_session),
) -> User:
    if credentials is None:
        raise Unauthorized("Требуется вход")
    return service.get_user(session, decode_token(credentials.credentials, "access"))


def require_staff(user: User = Depends(get_current_user)) -> User:
    if user.role not in ("support", "admin"):
        raise Forbidden("Недостаточно прав")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise Forbidden("Недостаточно прав")
    return user
