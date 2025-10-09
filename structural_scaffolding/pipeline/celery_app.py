from __future__ import annotations

import os
from celery import Celery

# TODO: Add level 2 summerization queue
def _default_queue() -> str:
    return os.getenv("CELERY_DEFAULT_QUEUE", "l1_summary_queue")


celery_app = Celery(
    "structural_scaffolding",
    broker=os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672//"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "rpc://"),
    include=[
        "structural_scaffolding.pipeline.tasks",
        "structural_scaffolding.pipeline.workflow_tasks",
        "structural_scaffolding.pipeline.directory_tasks",
    ],
)

celery_app.conf.update(
    task_default_queue=_default_queue(),
    task_acks_late=True,
    worker_prefetch_multiplier=int(os.getenv("CELERY_PREFETCH_MULTIPLIER", "1")),
    worker_concurrency=int(os.getenv("CELERY_WORKER_CONCURRENCY", "4")),
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
)


__all__ = ["celery_app"]
