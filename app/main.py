"""Точка входа: сборка FastAPI-приложения из роутеров модулей."""
from fastapi import FastAPI

from app.core.db import Base, engine
from app.core.errors import register_handlers
from app.modules.admin.router import router as admin_router
from app.modules.classification.router import router as classification_router
from app.modules.limits.router import router as limits_router
from app.modules.operations.router import router as operations_router
from app.modules.receipts.router import router as receipts_router
from app.modules.users.router import router as users_router

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(title="ИС «Итого»", version="0.1.0")
    register_handlers(app)
    for router in (
        users_router, receipts_router, classification_router, operations_router, limits_router, admin_router,
    ):
        app.include_router(router, prefix=API_PREFIX)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


def create_tables() -> None:
    """Для разработки и тестов. В эксплуатации структуру базы ведут миграции Alembic."""
    Base.metadata.create_all(engine)


app = create_app()
