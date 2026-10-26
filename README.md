# ИС «Итого»: серверная часть (стартовый срез первой очереди)

Каркас серверной части по архитектуре из практической работы 3: модульный монолит на FastAPI,
воркеры Celery и клиент ML-сервиса. Сам ML-сервис в срез не входит: вместо него работает заглушка.

## Структура

```
app/
  core/           настройки, база данных, ошибки, безопасность, очередь
  integrations/   клиент ML-сервиса, хранилище файлов, почта
  modules/        users, receipts, classification, operations, limits, admin
  workers/        приложение Celery и задачи
tests/            45 тестов (pytest)
tools/metrics.py  метрики кода (практическая работа 4)
```

В каждом модуле: `models.py` (таблицы), `schemas.py` (формат запросов и ответов), `service.py` (бизнес-логика),
`router.py` (маршруты). К данным другого модуля обращаются только через его `service.py`.

## Запуск

Нужен Python 3.11 или новее (скрипт метрик `tools/metrics.py` работает и на 3.8).

```
pip install -r requirements-dev.txt
python -m pytest                       # тесты
python -m pytest --cov=app             # тесты и покрытие
python tools/metrics.py app tests      # метрики кода
radon cc -s -a app                     # цикломатическая сложность
```

Приложение (нужен PostgreSQL, для разработки подойдёт SQLite):

```
export DATABASE_URL=sqlite:///./itogo.db QUEUE_MODE=memory
uvicorn app.main:app --reload
celery -A app.workers.celery_app worker -Q recognition,default   # воркеры, нужен RabbitMQ
celery -A app.workers.celery_app beat                             # планировщик, один экземпляр
```

## Что не входит в срез

Клиентская часть, сам ML-сервис, миграции Alembic, восстановление пароля (ФТ-2),
доступ поддержки к данным пользователя (ФТ-28).
