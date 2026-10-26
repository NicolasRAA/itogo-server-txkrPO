"""Настройки приложения. Значения берутся из переменных окружения."""
import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "sqlite:///./itogo.db"))
    broker_url: str = field(default_factory=lambda: _env("BROKER_URL", "amqp://guest:guest@localhost//"))
    # "celery" отправляет задачи в RabbitMQ, "memory" только запоминает их (для тестов)
    queue_mode: str = field(default_factory=lambda: _env("QUEUE_MODE", "celery"))
    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY", "dev-secret-change-me-please-32-bytes"))
    ml_service_url: str = field(default_factory=lambda: _env("ML_SERVICE_URL", ""))
    storage_dir: str = field(default_factory=lambda: _env("STORAGE_DIR", "./storage"))
    s3_bucket: str = field(default_factory=lambda: _env("S3_BUCKET", ""))
    smtp_host: str = field(default_factory=lambda: _env("SMTP_HOST", ""))
    mail_from: str = field(default_factory=lambda: _env("MAIL_FROM", "noreply@itogo.example"))

    access_token_minutes: int = 15
    refresh_token_days: int = 30
    max_image_bytes: int = 10 * 1024 * 1024
    image_retention_days: int = 90
    max_login_attempts: int = 5
    lockout_minutes: int = 15
    max_recognition_attempts: int = 3
    stuck_after_minutes: int = 2
    low_confidence: float = 0.8


def get_settings() -> Settings:
    return Settings()
