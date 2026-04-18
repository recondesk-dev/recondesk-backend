import os

from celery import Celery

# Default to in-memory broker so importing tasks works without Redis (API thread worker).
_redis = os.environ.get("REDIS_URL") or "memory://"

celery_app = Celery(
    "recondesk",
    broker=_redis,
    backend=_redis,
)

celery_app.conf.update(
    worker_concurrency=4,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)
