from fastapi import APIRouter, Cookie, Depends, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import Unauthorized
from app.modules.users import service
from app.modules.users.deps import get_current_user
from app.modules.users.models import User
from app.modules.users.schemas import ConfirmIn, LoginIn, RegisterIn, SettingsIn, TokenOut, UserOut

router = APIRouter(tags=["users"])
COOKIE_PATH = "/api/v1/auth"


def _answer_with_tokens(response: Response, access: str, refresh: str) -> TokenOut:
    # токен обновления недоступен скрипту на странице и не уходит со сторонних сайтов
    response.set_cookie(
        "refresh_token",
        refresh,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=get_settings().refresh_token_days * 86400,
        path=COOKIE_PATH,
    )
    return TokenOut(access_token=access)


@router.post("/auth/register", response_model=UserOut, status_code=201)
def register(data: RegisterIn, session: Session = Depends(get_session)):
    return service.register(session, data.email, data.password, data.consent)


@router.post("/auth/confirm", response_model=UserOut)
def confirm(data: ConfirmIn, session: Session = Depends(get_session)):
    return service.confirm_email(session, data.token)


@router.post("/auth/login", response_model=TokenOut)
def login(data: LoginIn, response: Response, session: Session = Depends(get_session)):
    access, refresh = service.login(session, data.email, data.password)
    return _answer_with_tokens(response, access, refresh)


@router.post("/auth/refresh", response_model=TokenOut)
def refresh(response: Response, refresh_token: str | None = Cookie(default=None), session: Session = Depends(get_session)):
    if refresh_token is None:
        raise Unauthorized("Войдите заново")
    access, new_refresh = service.refresh(session, refresh_token)
    return _answer_with_tokens(response, access, new_refresh)


@router.get("/users/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/users/me", response_model=UserOut)
def update_me(data: SettingsIn, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    return service.set_email_notifications(session, user, data.notify_by_email)


@router.delete("/users/me", status_code=202)
def delete_me(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    service.request_deletion(session, user)
    return {"message": "Учётная запись будет удалена вместе со всеми данными"}
