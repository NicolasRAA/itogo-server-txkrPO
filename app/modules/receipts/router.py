from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_session
from app.integrations.storage import Storage, get_storage
from app.modules.operations.schemas import OperationOut
from app.modules.receipts import service
from app.modules.receipts.schemas import ConfirmIn, ReceiptOut
from app.modules.users.deps import get_current_user
from app.modules.users.models import User

router = APIRouter(tags=["receipts"])


@router.post("/receipts", response_model=ReceiptOut, status_code=202)
def upload(
    file: UploadFile,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    storage: Storage = Depends(get_storage),
):
    # читаем на один байт больше предела: так видно, что файл слишком большой, не загружая его целиком
    content = file.file.read(get_settings().max_image_bytes + 1)
    return service.accept_upload(session, storage, user, content)


@router.get("/receipts/{receipt_id}", response_model=ReceiptOut)
def get_receipt(receipt_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    return service.get_for_user(session, user.id, receipt_id)


@router.post("/receipts/{receipt_id}/confirm", response_model=OperationOut, status_code=201)
def confirm(receipt_id: int, data: ConfirmIn, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    edits = [service.ItemEdit(i.id, i.name, i.quantity, i.price, i.amount, i.category_id) for i in data.items]
    return service.confirm(session, user, receipt_id, data.merchant, data.purchase_dt, data.total, edits)
