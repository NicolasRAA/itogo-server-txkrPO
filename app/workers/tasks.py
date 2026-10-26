"""Задачи воркеров. Вся логика лежит в сервисах модулей, здесь только запуск и повторы."""
import logging
from datetime import timedelta

from app.core.db import SessionLocal, utcnow
from app.integrations.mailer import send_email
from app.integrations.ml_client import get_ml_client
from app.integrations.storage import get_storage
from app.modules.admin import service as admin
from app.modules.classification import service as classification
from app.modules.limits import service as limits
from app.modules.operations import service as operations
from app.modules.receipts import service as receipts
from app.modules.users import service as users
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(name="recognize_receipt", bind=True, max_retries=None)
def recognize_receipt(self, receipt_id: int) -> None:
    with SessionLocal() as session:
        try:
            receipts.process(session, receipt_id, get_storage(), get_ml_client())
        except receipts.RetryLater:
            # пауза растёт с каждой попыткой: 10, 20, 40 секунд
            raise self.retry(countdown=10 * 2 ** (self.request.retries))


@celery_app.task(name="send_email")
def send_email_task(to: str, subject: str, body: str) -> None:
    send_email(to, subject, body)


@celery_app.task(name="requeue_stuck_receipts")
def requeue_stuck_receipts() -> int:
    with SessionLocal() as session:
        return receipts.requeue_stuck(session)


@celery_app.task(name="delete_old_images")
def delete_old_images() -> int:
    with SessionLocal() as session:
        return receipts.delete_old_images(session, get_storage())


@celery_app.task(name="reclassify_uncategorized")
def reclassify_uncategorized() -> int:
    with SessionLocal() as session:
        return receipts.reclassify_uncategorized(session, get_ml_client())


@celery_app.task(name="purge_deleted_accounts")
def purge_deleted_accounts() -> int:
    """Удаляет учётные записи, закрытые по запросу пользователя, вместе со всеми данными (ФТ-3)."""
    storage = get_storage()
    with SessionLocal() as session:
        pending = users.users_pending_deletion(session)
        for user in pending:
            # порядок важен: сначала то, что ссылается на чеки и операции, затем сами чеки
            limits.delete_user_data(session, user.id)
            operations.delete_user_data(session, user.id)
            admin.delete_user_data(session, user.id)
            classification.delete_user_data(session, user.id)
            receipts.delete_user_data(session, storage, user.id)
            users.purge_user(session, user.id)
            session.commit()
        return len(pending)


@celery_app.task(name="weekly_correction_report")
def weekly_correction_report() -> float:
    """Считает долю исправленных полей за неделю и предупреждает, если она выше порога."""
    with SessionLocal() as session:
        now = utcnow()
        report = admin.correction_report(session, now - timedelta(days=7), now)
        if report.exceeds_threshold:
            log.warning("За неделю исправлено %.1f %% полей, это выше порога", report.share * 100)
        return report.share
