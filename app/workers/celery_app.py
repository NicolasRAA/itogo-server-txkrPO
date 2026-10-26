"""Приложение Celery: две очереди и расписание плановых задач."""
from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

celery_app = Celery("itogo", broker=get_settings().broker_url, include=["app.workers.tasks"])

celery_app.conf.update(
    task_default_queue="default",
    task_routes={"recognize_receipt": {"queue": "recognition"}},
    task_acks_late=True,  # задача подтверждается после выполнения, поэтому при падении воркера не теряется
    worker_prefetch_multiplier=1,
    timezone="UTC",
    beat_schedule={
        "requeue-stuck-receipts": {"task": "requeue_stuck_receipts", "schedule": 60.0},
        "delete-old-images": {"task": "delete_old_images", "schedule": crontab(hour=3, minute=0)},
        "reclassify-uncategorized": {"task": "reclassify_uncategorized", "schedule": crontab(hour=3, minute=30)},
        "purge-deleted-accounts": {"task": "purge_deleted_accounts", "schedule": crontab(hour=4, minute=0)},
        "weekly-correction-report": {"task": "weekly_correction_report", "schedule": crontab(hour=6, minute=0, day_of_week=1)},
    },
)
