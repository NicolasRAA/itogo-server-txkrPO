from decimal import Decimal

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.db import get_session, utcnow
from app.modules.limits import service
from app.modules.limits.schemas import LimitIn, LimitOut, NotificationOut
from app.modules.users.deps import get_current_user
from app.modules.users.models import User

router = APIRouter(tags=["limits"])


@router.get("/limits", response_model=list[LimitOut])
def get_limits(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    return service.usage(session, user.id, utcnow())


@router.put("/limits/{category_id}", response_model=LimitOut)
def put_limit(category_id: int, data: LimitIn, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    service.set_limit(session, user.id, category_id, data.monthly_amount)
    session.commit()
    return next(item for item in service.usage(session, user.id, utcnow()) if item.category_id == category_id)


@router.delete("/limits/{category_id}", status_code=204)
def delete_limit(category_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    service.remove_limit(session, user.id, category_id)
    session.commit()
    return Response(status_code=204)


@router.get("/notifications", response_model=list[NotificationOut])
def notifications(unread: bool = False, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    return service.list_notifications(session, user.id, unread)


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def read_notification(notification_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    notification = service.mark_read(session, user.id, notification_id)
    session.commit()
    return notification
