from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.modules.classification import service
from app.modules.classification.schemas import CategoryOut
from app.modules.users.deps import get_current_user

router = APIRouter(tags=["classification"], dependencies=[Depends(get_current_user)])


@router.get("/categories", response_model=list[CategoryOut])
def categories(session: Session = Depends(get_session)):
    return service.list_categories(session)
