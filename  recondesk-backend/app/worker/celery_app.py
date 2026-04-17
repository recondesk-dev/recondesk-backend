import os

from celery import Celery

celery_app = Celery(
    "recondesk",
    broker=os.environ["REDIS_URL"],
    backend=os.environ["REDIS_URL"],
)

celery_app.conf.update(
    worker_concurrency=4,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)
