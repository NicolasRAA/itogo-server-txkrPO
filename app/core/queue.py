"""Постановка задач в очередь. Модули не знают про Celery и вызывают только publish."""
from dataclasses import dataclass, field

from app.core.config import get_settings


@dataclass
class TaskQueue:
    # в режиме memory сюда складываются отправленные задачи: (имя, аргументы, очередь)
    sent: list[tuple[str, tuple, str]] = field(default_factory=list)

    def publish(self, task_name: str, args: tuple = (), queue: str = "default") -> None:
        if get_settings().queue_mode == "memory":
            self.sent.append((task_name, args, queue))
            return
        from app.workers.celery_app import celery_app

        celery_app.send_task(task_name, args=list(args), queue=queue)


task_queue = TaskQueue()
